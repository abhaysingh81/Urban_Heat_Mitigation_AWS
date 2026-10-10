"""
Budget + equity optimizer.

Given a budget (INR lakh), choose at most one cooling intervention per 500 m
cell, greedily by  benefit / cost,  never exceeding the budget:

    benefit = |cooling_mid_C| x hazard_weight x ((1 - lambda) + lambda * vulnerable_people_weight)

    vulnerable_people_weight = (people / p90 people) x (0.3 + 0.7 * vulnerability)

lambda = 0 maximises raw cooling per rupee in the hottest, most suitable cells;
lambda = 1 maximises cooling delivered to vulnerable *people*. The two generally
disagree, which is the trade-off the equity toggle exposes.
Cooling-centre sites are chosen first from a share of the budget, maximising
*uncovered vulnerable people* within walking distance (own cell plus a
fraction of the four neighbours).

Cooling is always reported as {low, mid, high}: published-range endpoints
scaled by how suitable each cell is (space to plant, roof share, foot
traffic ...), tree effects scaled by survival rate and ramped over years.
These are planning estimates, not measurements.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from models.risk import cell_components
from pipeline.config import REAL_INTERVENTIONS

COOLING_TYPES = [k for k, v in REAL_INTERVENTIONS.items() if k != "cooling_centre"]
HORIZON_YEARS = 10
MIN_USEFUL_COOLING_C = 0.2  # a cell must reach this (mid) to count as "protected"
NEIGHBOUR_WEIGHT = 0.25     # share of an adjacent cell's people a centre also serves


@dataclass
class PlanRequest:
    city_id: str
    budget_lakh: float
    interventions: list[str] = field(default_factory=lambda: list(COOLING_TYPES))
    equity_weight: float = 0.0       # 0 = max cooling-per-rupee, 1 = favour vulnerable
    tree_survival: float = 0.7       # fraction of plantings that persist
    centre_share: float = 0.15       # share of budget reserved for cooling centres
    include_centres: bool = True


def _suitability(df: pd.DataFrame) -> dict[str, pd.Series]:
    imperv = df["frac_impervious"].fillna(df["frac_impervious"].median()).clip(0, 1)
    veg = df["frac_vegetation"].fillna(df["frac_vegetation"].median()).clip(0, 1)
    tree = df.get("frac_tree", pd.Series(0.0, index=df.index)).fillna(0).clip(0, 1)
    bd = df.get("building_density", pd.Series(np.nan, index=df.index))
    bd_norm = (bd / bd.quantile(0.9)).clip(0, 1) if bd.notna().any() else pd.Series(0.5, index=df.index)
    bd_norm = bd_norm.fillna(0.5)
    pd_norm = (df["pop_density"] / max(df["pop_density"].quantile(0.9), 1e-9)).clip(0, 1)
    return {
        "tree_cover": (0.3 + 0.7 * (1 - veg)).clip(0, 1) * (1 - tree),
        "cool_roofs": imperv * bd_norm,
        "shade_structures": imperv * pd_norm,
        "cool_pavement": imperv * (1 - tree),
    }


def cooling_range(kind: str, suit: np.ndarray, survival: float, year: float | None = None):
    """(low, mid, high) cooling in °C (negative), scaled by suitability."""
    cfg = REAL_INTERVENTIONS[kind]
    weak, strong = cfg["cooling_range_c"][1], cfg["cooling_range_c"][0]  # e.g. -0.8, -3.0
    scale = suit * (survival if cfg["uses_survival"] else 1.0)
    if year is not None and cfg["years_to_full"] > 0:
        scale = scale * min(1.0, year / cfg["years_to_full"])
    low, high = weak * scale, strong * scale
    return low, (low + high) / 2.0, high


def _options(df: pd.DataFrame, req: PlanRequest) -> pd.DataFrame:
    suit = _suitability(df)
    hazard_w = 0.2 + 0.8 * df["hazard_pct"]
    p90 = max(float(df["pop_total"].quantile(0.9)), 1.0)
    vpw = ((df["pop_total"] / p90).clip(0, 3) * (0.3 + 0.7 * df["vuln_pct"])).to_numpy()
    rows = []
    for kind in req.interventions:
        if kind not in COOLING_TYPES:
            continue
        s = suit[kind].to_numpy()
        low, mid, high = cooling_range(kind, s, req.tree_survival)
        cost = REAL_INTERVENTIONS[kind]["cost_lakh_per_cell"]
        benefit = (np.abs(mid) * hazard_w.to_numpy()
                   * ((1 - req.equity_weight) + req.equity_weight * vpw))
        rows.append(pd.DataFrame({
            "idx": df.index, "kind": kind, "cost": cost, "benefit": benefit,
            "score": benefit / cost, "low": low, "mid": mid, "high": high,
        }))
    opts = pd.concat(rows, ignore_index=True)
    return opts[(opts["mid"].abs() >= MIN_USEFUL_COOLING_C) & (opts["benefit"] > 0)]


def _place_centres(df: pd.DataFrame, budget: float, req: PlanRequest) -> list[dict]:
    cost = REAL_INTERVENTIONS["cooling_centre"]["cost_lakh_per_cell"]
    n_max = int(budget // cost)
    if n_max <= 0:
        return []
    pop = df.set_index(["row", "col"])["pop_total"]
    vuln = df.set_index(["row", "col"])["vuln_pct"]
    vp = (pop * (0.3 + 0.7 * vuln))  # vulnerable-people weight per cell
    vp_d = vp.to_dict()
    covered: dict[tuple, float] = {}  # cell -> share already served (0..1)
    chosen = []
    cand = df[["grid_id", "row", "col", "ward_id", "ward_name", "pop_total"]].copy()
    cand = cand[cand["pop_total"] > 0]
    # restrict to the top candidates by own vulnerable-people weight for speed
    cand["w"] = [vp_d.get((r, c), 0) for r, c in zip(cand["row"], cand["col"])]
    cand = cand.nlargest(min(len(cand), 600), "w")
    for _ in range(n_max):
        best, best_gain = None, 0.0
        for r, c, gid in zip(cand["row"], cand["col"], cand["grid_id"]):
            gain = vp_d.get((r, c), 0) * (1 - covered.get((r, c), 0))
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nb = (r + dr, c + dc)
                gain += NEIGHBOUR_WEIGHT * vp_d.get(nb, 0) * (1 - covered.get(nb, 0))
            if gain > best_gain:
                best, best_gain = (r, c, gid), gain
        if best is None or best_gain <= 0:
            break
        r, c, gid = best
        covered[(r, c)] = 1.0
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb = (r + dr, c + dc)
            covered[nb] = max(covered.get(nb, 0), NEIGHBOUR_WEIGHT)
        chosen.append({"grid_id": gid, "gain": best_gain})
    return chosen


def optimize(req: PlanRequest) -> dict:
    if req.budget_lakh <= 0:
        raise ValueError("budget_lakh must be positive")
    if not 0 <= req.equity_weight <= 1:
        raise ValueError("equity_weight must be in [0, 1]")
    if not 0 < req.tree_survival <= 1:
        raise ValueError("tree_survival must be in (0, 1]")

    df = cell_components(req.city_id).reset_index(drop=True)
    df["pop_total"] = df["pop_total"].fillna(0)
    by_gid = df.set_index("grid_id")

    centre_budget = req.budget_lakh * req.centre_share if req.include_centres else 0.0
    centre_sites = _place_centres(df, centre_budget, req) if centre_budget else []
    centre_cost = REAL_INTERVENTIONS["cooling_centre"]["cost_lakh_per_cell"]
    spent = centre_cost * len(centre_sites)

    remaining = req.budget_lakh - spent
    opts = _options(df, req)
    # best single option per cell, then fill greedily by score, skipping what doesn't fit
    best = opts.sort_values("score", ascending=False).drop_duplicates("idx")
    selected = []
    for row in best.itertuples():
        if row.cost <= remaining + 1e-9:
            selected.append(row)
            remaining -= row.cost
            spent += row.cost
        if remaining < min(REAL_INTERVENTIONS[k]["cost_lakh_per_cell"] for k in COOLING_TYPES
                           if k in req.interventions or not req.interventions):
            break

    items = []
    for r in selected:
        cell = df.loc[r.idx]
        items.append({
            "grid_id": cell["grid_id"], "ward_id": cell["ward_id"], "ward_name": cell["ward_name"],
            "lat": round(float(cell["centroid_lat"]), 5), "lon": round(float(cell["centroid_lon"]), 5),
            "intervention": r.kind, "label": REAL_INTERVENTIONS[r.kind]["label"],
            "cost_lakh": float(r.cost), "people": int(round(cell["pop_total"])),
            "cooling_c": {"low": round(float(r.low), 2), "mid": round(float(r.mid), 2),
                          "high": round(float(r.high), 2)},
            "vulnerability": round(float(cell["vuln_pct"]), 3),
        })
    for s in centre_sites:
        cell = by_gid.loc[s["grid_id"]]
        items.append({
            "grid_id": s["grid_id"], "ward_id": cell["ward_id"], "ward_name": cell["ward_name"],
            "lat": round(float(cell["centroid_lat"]), 5), "lon": round(float(cell["centroid_lon"]), 5),
            "intervention": "cooling_centre", "label": REAL_INTERVENTIONS["cooling_centre"]["label"],
            "cost_lakh": float(centre_cost), "people": int(round(s["gain"])),
            "cooling_c": {"low": 0.0, "mid": 0.0, "high": 0.0},
            "vulnerability": round(float(cell["vuln_pct"]), 3),
        })

    return _summarise(req, df, items, spent)


def _summarise(req: PlanRequest, df: pd.DataFrame, items: list[dict], spent: float) -> dict:
    cooling = [i for i in items if i["intervention"] != "cooling_centre"]
    centres = [i for i in items if i["intervention"] == "cooling_centre"]
    people_cooled = sum(i["people"] for i in cooling)
    # distinct vulnerable people served by centres (weighted estimate from placement)
    people_centres = sum(i["people"] for i in centres)
    people_total = people_cooled + people_centres

    def wmean(key):
        if not cooling or people_cooled == 0:
            return 0.0
        return float(sum(i["cooling_c"][key] * i["people"] for i in cooling) / people_cooled)

    # timeline: effect by year as trees mature (survival already in the ranges)
    timeline = []
    for year in range(0, HORIZON_YEARS + 1):
        total = 0.0
        for i in cooling:
            cfg = REAL_INTERVENTIONS[i["intervention"]]
            ramp = 1.0 if cfg["years_to_full"] == 0 else min(1.0, year / cfg["years_to_full"])
            total += i["cooling_c"]["mid"] * ramp * i["people"]
        timeline.append({"year": year,
                         "pop_weighted_cooling_mid_c": round(total / people_cooled, 2) if people_cooled else 0.0})

    by_ward: dict[str, dict] = {}
    for i in items:
        w = by_ward.setdefault(i["ward_id"], {"ward_id": i["ward_id"], "ward_name": i["ward_name"],
                                              "cost_lakh": 0.0, "n_actions": 0, "people": 0})
        w["cost_lakh"] += i["cost_lakh"]; w["n_actions"] += 1; w["people"] += i["people"]

    ben_vuln = (sum(i["vulnerability"] * i["people"] for i in items) / people_total) if people_total else 0.0
    vuln_share = (sum(i["cost_lakh"] for i in items if i["vulnerability"] >= 0.75)
                  / spent) if spent else 0.0
    by_type: dict[str, dict] = {}
    for i in items:
        t = by_type.setdefault(i["intervention"], {"intervention": i["intervention"],
                                                   "label": i["label"], "count": 0, "cost_lakh": 0.0})
        t["count"] += 1; t["cost_lakh"] += i["cost_lakh"]

    return {
        "request": {"city_id": req.city_id, "budget_lakh": req.budget_lakh,
                    "equity_weight": req.equity_weight, "tree_survival": req.tree_survival,
                    "interventions": req.interventions, "centre_share": req.centre_share},
        "items": items,
        "by_ward": sorted(by_ward.values(), key=lambda w: -w["cost_lakh"]),
        "by_type": list(by_type.values()),
        "impact_card": {
            "budget_lakh": req.budget_lakh,
            "spent_lakh": round(spent, 1),
            "n_actions": len(items),
            "people_protected": int(people_total),
            "cost_per_person_inr": round(spent * 1e5 / people_total, 0) if people_total else None,
            "cooling_c": {"low": round(wmean("low"), 2), "mid": round(wmean("mid"), 2),
                          "high": round(wmean("high"), 2)},
            "share_of_spend_in_high_vulnerability_cells": round(vuln_share, 3),
            "beneficiary_vulnerability": round(ben_vuln, 3),
            "assumptions": [
                "Cooling = published-range endpoints scaled by cell suitability; an estimate, not a measurement.",
                f"Tree survival assumed {req.tree_survival:.0%}; tree cooling ramps up over years.",
                "Costs are planning-grade placeholders per 500 m cell, not quotes.",
                "People protected = population (WorldPop or proxy) in treated cells plus centre catchments.",
                "Vulnerability uses population density, green deficit and crowding; no age or income data in v1.",
            ],
        },
        "timeline": timeline,
    }


def compare_equity(req: PlanRequest) -> dict:
    """Run the same budget at lambda=0 and lambda=1 for the UI's equity toggle."""
    a = optimize(PlanRequest(**{**req.__dict__, "equity_weight": 0.0}))
    b = optimize(PlanRequest(**{**req.__dict__, "equity_weight": 1.0}))
    def brief(p):
        ic = p["impact_card"]
        return {"people_protected": ic["people_protected"], "cooling_mid_c": ic["cooling_c"]["mid"],
                "high_vulnerability_spend_share": ic["share_of_spend_in_high_vulnerability_cells"],
                "beneficiary_vulnerability": ic["beneficiary_vulnerability"],
                "spent_lakh": ic["spent_lakh"]}
    return {"efficiency": brief(a), "equity": brief(b)}
