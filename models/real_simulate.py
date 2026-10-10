"""
Intensity-based scenario simulator for real-data cities, compatible with the
existing /scenarios/simulate response and adding {low, mid, high} ranges.

Each targeted cell's cooling = published-range endpoints x cell suitability x
intensity (x tree survival). Cells outside the target set are unchanged.
"""

from __future__ import annotations

import numpy as np

from models.optimizer import COOLING_TYPES, _suitability, cooling_range
from models.risk import cell_components
from pipeline.config import REAL_INTERVENTIONS

HOTSPOT_TIERS = ("critical", "high")


def _tier(lst, mean, std):
    return np.select([lst > mean + 2 * std, lst > mean + std, lst > mean, lst > mean - std],
                     ["critical", "high", "moderate", "normal"], default="cool")


def simulate(city_id: str, interventions: dict[str, float], target_cells=None,
             tree_survival: float = 0.7) -> dict:
    for k in interventions:
        if k not in REAL_INTERVENTIONS:
            raise ValueError(f"Unknown intervention: {k}")
    df = cell_components(city_id)
    df = df[df["lst_hazard"].notna()].reset_index(drop=True)
    lst = df["lst_hazard"].to_numpy()
    mean, std = lst.mean(), lst.std()
    tiers_before = _tier(lst, mean, std)

    if target_cells:
        mask = df["grid_id"].isin(target_cells).to_numpy()
    else:
        mask = np.isin(tiers_before, HOTSPOT_TIERS)
    n_target = int(mask.sum())

    suit = _suitability(df)
    lo = np.zeros(len(df)); mid = np.zeros(len(df)); hi = np.zeros(len(df))
    cost_lakh = 0.0
    for kind, intensity in interventions.items():
        if kind not in COOLING_TYPES or intensity <= 0:
            continue
        l, m, h = cooling_range(kind, suit[kind].to_numpy() * intensity, tree_survival)
        lo += np.where(mask, l, 0); mid += np.where(mask, m, 0); hi += np.where(mask, h, 0)
        cost_lakh += REAL_INTERVENTIONS[kind]["cost_lakh_per_cell"] * intensity * n_target

    after = lst + mid
    tiers_after = _tier(after, mean, std)
    hb = int(np.isin(tiers_before, HOTSPOT_TIERS).sum())
    ha = int(np.isin(tiers_after, HOTSPOT_TIERS).sum())
    d = mid[mask] if n_target else mid
    cost_m = cost_lakh / 10.0  # INR lakh -> INR million
    return {
        "summary": {
            "cells_modified": n_target,
            "mean_cooling_c": round(float(d.mean()), 2),
            "max_cooling_c": round(float(d.min()), 2),
            "hotspots_before": hb, "hotspots_after": ha,
            "hotspot_reduction_pct": round((hb - ha) / max(hb, 1) * 100, 1),
            "cost_estimate_m": round(cost_m, 1),
            "cost_efficiency_c_per_m": round(abs(float(d.mean())) / max(cost_m, 0.1), 3) if cost_m else 0,
            "cooling_range_c": {"low": round(float(lo[mask].mean()), 2) if n_target else 0.0,
                                "mid": round(float(d.mean()), 2),
                                "high": round(float(hi[mask].mean()), 2) if n_target else 0.0},
            "is_estimate": True,
        },
        "cell_results": [
            {"grid_id": g, "lst_before": round(float(b), 2), "lst_after": round(float(a), 2),
             "delta_t": round(float(dt), 2), "tier_before": tb, "tier_after": ta}
            for g, b, a, dt, tb, ta in zip(df["grid_id"], lst, after, mid, tiers_before, tiers_after)
        ],
    }
