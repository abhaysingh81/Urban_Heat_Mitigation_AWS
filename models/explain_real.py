"""SHAP lookups for the real-data model (artifacts in models/artifacts/real)."""

from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd

from pipeline.config import REAL_MODEL_DIR, city_real_features_file


@lru_cache(maxsize=1)
def _shap_df() -> pd.DataFrame:
    return pd.read_parquet(REAL_MODEL_DIR / "shap_values.parquet")


def global_importance() -> list[dict]:
    f = REAL_MODEL_DIR / "feature_importance.json"
    if not f.exists():
        return []
    # Map to the legacy schema the UI expects: feature / importance / direction
    out = []
    for d in json.loads(f.read_text()):
        out.append({"feature": d["feature"], "importance": d["mean_abs_shap"],
                    "direction": "positive"})
    return out


def cell_explanation(city_id: str, grid_id: str):
    sdf = _shap_df()
    row = sdf[(sdf["grid_id"] == grid_id) & (sdf["city_id"] == city_id)]
    feats = pd.read_parquet(city_real_features_file(city_id))
    frow = feats[feats["grid_id"] == grid_id]
    if row.empty or frow.empty:
        return None  # SHAP is computed on a sample of cells
    row, frow = row.iloc[0], frow.iloc[0]
    cols = [c for c in sdf.columns if c not in ("grid_id", "city_id", "base_value")]
    vals = sorted(({"feature": c, "value": float(frow[c]) if pd.notna(frow.get(c)) else 0.0,
                    "shap": round(float(row[c]), 4)} for c in cols),
                  key=lambda x: -abs(x["shap"]))
    base = float(row["base_value"])
    return {"grid_id": grid_id, "city_id": city_id,
            "predicted_lst": round(base + sum(v["shap"] for v in vals), 2),
            "base_value": round(base, 2), "shap_values": vals[:15]}


def top_drivers_for_hotspots(city_id: str):
    sdf = _shap_df()
    feats = pd.read_parquet(city_real_features_file(city_id))
    hot_ids = feats[feats["tier"].isin(["critical", "high"])]["grid_id"]
    h = sdf[(sdf["city_id"] == city_id) & (sdf["grid_id"].isin(hot_ids))]
    cols = [c for c in sdf.columns if c not in ("grid_id", "city_id", "base_value")]
    imp = {c: {"mean_abs_shap": round(float(h[c].abs().mean()), 4) if len(h) else 0.0,
               "mean_shap": round(float(h[c].mean()), 4) if len(h) else 0.0,
               "direction": "heating" if len(h) and h[c].mean() > 0 else "cooling"}
           for c in cols}
    return [{"feature": k, **v} for k, v in
            sorted(imp.items(), key=lambda kv: -kv[1]["mean_abs_shap"])[:10]]
