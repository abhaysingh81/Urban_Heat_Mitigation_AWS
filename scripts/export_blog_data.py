"""
Export the real-tier numbers the blog (BLOG/) displays, straight from the
pipeline, model card, risk engine, optimizer and brief template, so the
blog never carries hand-typed figures.

    python -m scripts.export_blog_data

Writes BLOG/src/data/real/*.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from agent.heat_officer import gather_facts, template_brief
from models.optimizer import PlanRequest, compare_equity, optimize
from models.risk import ward_table
from pipeline.config import CITIES, city_real_features_file, load_city_mask

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "BLOG" / "src" / "data" / "real"
REAL = ["new_delhi", "mumbai", "jaipur", "bengaluru"]
BUDGETS_LAKH = [1000, 2500, 5000, 10000]  # ₹10 cr … ₹100 cr
EQUITY = [0.0, 0.5, 1.0]


def _r(x, nd=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def grid(city_id: str) -> dict:
    df = pd.read_parquet(city_real_features_file(city_id))
    mask = load_city_mask(city_id)
    if mask is not None:
        df = df[df["grid_id"].isin(mask["inside"])]
    r0, c0 = int(df["row"].min()), int(df["col"].min())
    rows, cols = int(df["row"].max()) - r0 + 1, int(df["col"].max()) - c0 + 1

    def layer(col, nd):
        a = [None] * (rows * cols)
        for r, c, v in zip(df["row"], df["col"], df[col]):
            a[(int(r) - r0) * cols + (int(c) - c0)] = _r(v, nd)
        return a

    # Row 0 in the fishnet is the southern edge; flip so row 0 draws at the top.
    def flip(a):
        return [v for rr in range(rows - 1, -1, -1) for v in a[rr * cols:(rr + 1) * cols]]

    return {
        "city": city_id, "name": CITIES[city_id]["name"], "rows": rows, "cols": cols,
        "cells": int(len(df)), "wards": int(df["ward_id"].nunique()),
        "lst": flip(layer("lst_c", 1)), "ndvi": flip(layer("ndvi_mean", 2)),
        "imperv": flip(layer("frac_impervious", 2)), "pop": flip(layer("pop_density", 0)),
        "lst_stats": {"min": _r(df["lst_c"].min()), "max": _r(df["lst_c"].max()),
                      "mean": _r(df["lst_c"].mean()), "p5": _r(df["lst_c"].quantile(.05)),
                      "p95": _r(df["lst_c"].quantile(.95))},
    }


def model() -> dict:
    card = json.loads((ROOT / "models/artifacts/real/model_card.json").read_text())
    v = card["shipped_variant"]
    ev = card["evaluation"][v]["leave_one_city_out"]
    base = card["evaluation"]["spatial"]["baseline_linear_ndvi_impervious"]
    blk = card["block_cv_5km"]
    return {
        "version": card["model_version"], "variant": v, "n_cells": card["n_cells"],
        "n_features": len(card["features"]), "target": card["target"],
        "loco": {c: {k: ev[c][k] for k in ("n", "pearson_r", "rmse", "bias", "r2")} for c in REAL},
        "baseline_r": {c: base[c]["pearson_r"] for c in REAL},
        "block_cv": {c: {k: blk["per_city"][c][k] for k in ("pearson_r", "rmse")} for c in REAL},
        "coverage_raw": blk["q10_q90_coverage"], "coverage_calibrated": blk["calibrated_coverage"],
        "band_widen_c": blk["band_widen_c"],
        "shap": card["top_drivers_shap"], "limitations": card["limitations"],
        "quality_gate": card["quality_gate"],
    }


def wards(city_id: str) -> dict:
    full = ward_table(city_id)
    t = full.sort_values("risk_score", ascending=False).head(12)
    keep = ["ward_id", "ward_name", "rank", "risk_score", "hazard", "exposure", "vulnerability",
            "population", "lst_mean"]
    top = [{k: (_r(r[k], 3) if isinstance(r[k], float) else r[k]) for k in keep if k in t.columns}
           for _, r in t.iterrows()]
    return {"of_wards": int(len(full)), "top": top}


def sites(city_id: str, g: dict, budget_lakh: float = 5000) -> dict:
    """Plan sites as indices into the exported (flipped) grid, for λ = 0 and λ = 1."""
    df = pd.read_parquet(city_real_features_file(city_id), columns=["grid_id", "row", "col"])
    r0, c0 = int(df["row"].min()), int(df["col"].min())
    mask = load_city_mask(city_id)
    if mask is not None:
        inside = df[df["grid_id"].isin(mask["inside"])]
        r0, c0 = int(inside["row"].min()), int(inside["col"].min())
    rc = {gid: (int(r) - r0, int(c) - c0) for gid, r, c in zip(df["grid_id"], df["row"], df["col"])}
    out = {}
    for lam in (0.0, 1.0):
        p = optimize(PlanRequest(city_id=city_id, budget_lakh=budget_lakh, equity_weight=lam))
        pts = []
        for i in p["items"]:
            if i["grid_id"] not in rc:
                continue
            r, c = rc[i["grid_id"]]
            pts.append([(g["rows"] - 1 - r) * g["cols"] + c, 1 if i["intervention"] == "cooling_centre" else 0,
                        i["people"]])
        out[str(lam)] = pts
    return {"budget_lakh": budget_lakh, **out}


def plans(city_id: str) -> list[dict]:
    out = []
    for b in BUDGETS_LAKH:
        for lam in EQUITY:
            p = optimize(PlanRequest(city_id=city_id, budget_lakh=b, equity_weight=lam))
            ic = p["impact_card"]
            out.append({
                "budget_lakh": b, "equity_weight": lam,
                "people_protected": ic["people_protected"], "n_actions": ic["n_actions"],
                "spent_lakh": ic["spent_lakh"], "cooling_c": ic["cooling_c"],
                "cost_per_person_inr": ic["cost_per_person_inr"],
                "high_vuln_share": ic["share_of_spend_in_high_vulnerability_cells"],
                "by_type": [{"label": t["label"], "count": t["count"], "cost_lakh": round(t["cost_lakh"], 1)}
                            for t in p["by_type"]],
            })
    return out


def brief() -> dict:
    top = ward_table("new_delhi").sort_values("risk_score", ascending=False).iloc[0]
    fc = {"today_max_temp_c": 44.0, "today_alert_level": "orange", "source": "illustrative"}
    facts = gather_facts("new_delhi", top["ward_id"], 5000.0, 0.5, forecast=fc)
    return {"ward_id": top["ward_id"], "forecast_note": "Forecast fixed at 44 °C for this example.",
            **template_brief(facts)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    all_sites = {}
    for c in REAL:
        g = grid(c)
        (OUT / f"grid_{c}.json").write_text(json.dumps(g, separators=(",", ":")))
        all_sites[c] = sites(c, g)
    (OUT / "sites.json").write_text(json.dumps(all_sites, separators=(",", ":")))
    (OUT / "model.json").write_text(json.dumps(model(), indent=1, ensure_ascii=False))
    (OUT / "wards.json").write_text(json.dumps({c: wards(c) for c in REAL}, indent=1, default=str))
    (OUT / "plans.json").write_text(json.dumps({c: plans(c) for c in REAL}, indent=1))
    (OUT / "brief.json").write_text(json.dumps(brief(), indent=1, ensure_ascii=False))
    for f in sorted(OUT.iterdir()):
        print(f"{f.name:28s} {f.stat().st_size/1024:8.1f} KB")


if __name__ == "__main__":
    main()
