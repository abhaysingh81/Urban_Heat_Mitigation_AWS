"""
Scenario Lab: what happens to a city under given conditions if we build X.

Inputs
  conditions     see models.conditions (today / hot season / custom, climate
                 shift, power cut, water shortage)
  actions        list of {key, intensity 0–1 (share of each target cell's
                 capacity), params}; access interventions (cooling centres,
                 water points) take params.count = number of sites instead
  target         {"mode": "hotspots" | "wards" | "city", "ward_ids": [...]}

Outputs: surface cooling (low/mid/high), an *estimated* air and feels-like
change in the treated area, hotspot cells and people in hotspots before and
after, ward risk before/after on the same scale, cost (capital, yearly upkeep,
10-year total), water demand, a maturity timeline and per-cell results for the
map. Everything is an estimate from published ranges, labelled as such.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from models import conditions as cond
from models import ward_factors as wf
from models.interventions import (
    ACCESS_KEYS, AIR_PER_SURFACE, CELL_AREA_HA, CELL_AREA_M2, LIBRARY,
    combine_cooling, cooling_for_units, water_l_day,
)
from models.ward_factors import TREE_CANOPY_M2

HORIZON_YEARS = 10
TARGET_MODES = ("hotspots", "wards", "city")


def target_mask(cells: pd.DataFrame, target: dict | None) -> np.ndarray:
    target = target or {"mode": "hotspots"}
    mode = target.get("mode", "hotspots")
    if mode not in TARGET_MODES:
        raise ValueError(f"target.mode must be one of {TARGET_MODES}")
    if mode == "city":
        return np.ones(len(cells), bool)
    if mode == "wards":
        ids = set(target.get("ward_ids") or [])
        if not ids:
            raise ValueError("target.mode='wards' needs ward_ids")
        m = cells["ward_id"].isin(ids).to_numpy()
        if not m.any():
            raise ValueError("none of the ward_ids exist in this city")
        return m
    return cells["is_hotspot"].to_numpy() > 0


def place_access(cells: pd.DataFrame, key: str, n: int, candidates: np.ndarray,
                 dist: np.ndarray) -> tuple[list[int], np.ndarray]:
    """Greedy: each new site goes where (vulnerable people) × (distance to the nearest
    existing site) is largest; distances are updated after every pick."""
    dist = dist.copy()
    pop = cells["pop_total"].fillna(0).to_numpy()
    vuln = cells["vuln_pct"].fillna(0).to_numpy()
    need = pop * (0.3 + 0.7 * vuln)
    lat0 = float(cells["centroid_lat"].mean())
    xy = wf._xy_m(cells["centroid_lat"], cells["centroid_lon"], lat0)
    chosen: list[int] = []
    for _ in range(max(0, int(n))):
        gain = np.where(candidates, need * np.minimum(dist, wf.DIST_CAP_M) / wf.DIST_CAP_M, -1)
        i = int(np.argmax(gain))
        if gain[i] <= 0:
            break
        chosen.append(i)
        d_new = np.hypot(*(xy - xy[i]).T)
        dist = np.minimum(dist, d_new)
    return chosen, dist


def project(cells: pd.DataFrame, units: dict[str, np.ndarray], params: dict[str, dict] | None = None,
            survival: float = 0.7, year: float | None = None,
            access_sites: dict[str, list[int]] | None = None, water_shortage: bool = False) -> dict:
    """Apply per-cell unit counts; return combined cooling and the projected cell table."""
    params = params or {}
    n = len(cells)
    lo = np.zeros(n); mid = np.zeros(n); hi = np.zeros(n)
    canopy_add = np.zeros(n)
    for key, u in units.items():
        if key in ACCESS_KEYS:
            continue
        cap = LIBRARY[key].capacity(cells).to_numpy()
        l, m, h = cooling_for_units(key, u, survival, params.get(key), year)
        lo += l; mid += m; hi += h
        if key == "street_trees":
            canopy_add += np.asarray(u) * TREE_CANOPY_M2 * survival / CELL_AREA_M2
        if key == "pocket_parks":
            canopy_add += np.asarray(u) * 0.6 * survival / CELL_AREA_HA
    lo, mid, hi = combine_cooling(lo), combine_cooling(mid), combine_cooling(hi)
    after = cells.copy()
    after["lst_hazard"] = cells["lst_hazard"] + mid
    after["frac_tree"] = (cells["frac_tree"].fillna(0) + canopy_add).clip(0, 1)
    after["green_deficit"] = (cells["green_deficit"].fillna(0.5) - canopy_add).clip(0, 1)
    access_sites = access_sites or {}
    xy = None
    for key, col in (("cooling_centres", "dist_refuge_m"), ("water_atms", "dist_water_m")):
        sites = access_sites.get(key) or []
        if not sites:
            continue
        if xy is None:
            xy = wf._xy_m(cells["centroid_lat"], cells["centroid_lon"], float(cells["centroid_lat"].mean()))
        base = np.full(n, wf.DIST_CAP_M) if (key == "water_atms" and water_shortage) else after[col].to_numpy()
        d = base.copy()
        for i in sites:
            d = np.minimum(d, np.hypot(*(xy - xy[i]).T))
        after[col] = d
    return {"low": lo, "mid": mid, "high": hi, "cells_after": after}


def _ward_compare(cells, after, weights, water_shortage, water_after_explicit):
    ref = wf.aggregate(cells)
    before = wf.score(wf.aggregate(cells, water_shortage=water_shortage), ref, weights)
    # after: if water points were built, their distances are already in `after`
    aft = wf.score(wf.aggregate(after, water_shortage=water_shortage and not water_after_explicit), ref, weights)
    m = before[["ward_id", "ward_name", "risk_score", "band"]].merge(
        aft[["ward_id", "risk_score", "band"]], on="ward_id", suffixes=("_before", "_after"))
    m["change"] = (m["risk_score_after"] - m["risk_score_before"]).round(1)
    return m


def simulate(city_id: str, conditions_req: cond.ConditionsRequest, actions: list[dict],
             target: dict | None = None, survival: float = 0.7, preset: str = "balanced") -> dict:
    if not 0 < survival <= 1:
        raise ValueError("survival must be in (0, 1]")
    conditions = cond.resolve(city_id, conditions_req)
    cells = wf.base_cells(city_id)
    cells = cells[cells["lst_hazard"].notna()].reset_index(drop=True)
    mask = target_mask(cells, target)
    n = len(cells)

    units: dict[str, np.ndarray] = {}
    params: dict[str, dict] = {}
    access_sites: dict[str, list[int]] = {}
    for a in actions:
        key = a.get("key")
        if key not in LIBRARY:
            raise ValueError(f"unknown intervention '{key}'")
        params[key] = a.get("params") or {}
        if key in ACCESS_KEYS:
            count = int(params[key].get("count", 0))
            if not 0 <= count <= 500:
                raise ValueError("count must be between 0 and 500")
            col = "dist_refuge_m" if key == "cooling_centres" else "dist_water_m"
            dist = cells[col].to_numpy()
            if key == "water_atms" and conditions["water_shortage"]:
                dist = np.full(n, wf.DIST_CAP_M)
            sites, _ = place_access(cells, key, count, mask, dist)
            access_sites[key] = sites
            u = np.zeros(n); u[sites] = 1
            units[key] = u
            continue
        intensity = float(a.get("intensity", 0))
        if not 0 <= intensity <= 1:
            raise ValueError("intensity must be between 0 and 1")
        cap = LIBRARY[key].capacity(cells).to_numpy()
        units[key] = np.where(mask, np.floor(cap * intensity * 100) / 100, 0.0)

    proj = project(cells, units, params, survival, access_sites=access_sites,
                   water_shortage=conditions["water_shortage"])
    lo, mid, hi, after = proj["low"], proj["mid"], proj["high"], proj["cells_after"]

    pop = cells["pop_total"].fillna(0).to_numpy()
    treated = mask & (mid < -1e-6)
    pw = lambda x: float((x[treated] * pop[treated]).sum() / max(pop[treated].sum(), 1)) if treated.any() else 0.0
    surf = {"low": round(pw(lo), 2), "mid": round(pw(mid), 2), "high": round(pw(hi), 2)}
    air = {k: round(surf[k] * AIR_PER_SURFACE[k], 2) for k in surf}

    lst = cells["lst_hazard"].to_numpy()
    mean, std = lst.mean(), lst.std()
    hot_before = lst > mean + std
    hot_after = (lst + mid) > mean + std
    wts = wf.resolve_weights(None, preset, conditions["power_cut"])
    wards = _ward_compare(cells, after, wts, conditions["water_shortage"], bool(access_sites.get("water_atms")))

    breakdown, capex, opex, water = [], 0.0, 0.0, 0.0
    for key, u in units.items():
        iv = LIBRARY[key]
        total_units = float(np.asarray(u).sum())
        if total_units <= 0:
            continue
        c = total_units * iv.capex_inr; o = total_units * iv.opex_inr_yr
        wl = float(water_l_day(key, u, params.get(key)).sum())
        capex += c; opex += o; water += wl
        cap = iv.capacity(cells).to_numpy()
        _, m_only, _ = cooling_for_units(key, u, survival, params.get(key))
        breakdown.append({
            "key": key, "label": iv.label, "unit": iv.unit, "units": round(total_units, 1),
            "cells": int((np.asarray(u) > 0).sum()), "capex_lakh": round(c / 1e5, 1),
            "opex_lakh_yr": round(o / 1e5, 1), "water_kl_day": round(wl / 1000, 1),
            "department": iv.department, "years_to_full": iv.years_to_full,
            "cooling_mid_c_alone": round(float(m_only[m_only < 0].mean()) if (m_only < 0).any() else 0.0, 2),
        })

    timeline = []
    for year in range(0, HORIZON_YEARS + 1):
        p = project(cells, units, params, survival, year=year)
        timeline.append({"year": year, "surface_cooling_mid_c": round(pw(p["mid"]), 2)})

    t, rh = conditions["tmax_c"], conditions["humidity_pct"]
    fl_before = cond.feels_like(t, rh, 0.0)
    fl_after = cond.feels_like(t, rh, air["mid"])

    changed = wards[wards["change"] != 0].sort_values("change").head(10)
    return {
        "city_id": city_id, "conditions": conditions,
        "target": target or {"mode": "hotspots"}, "cells_targeted": int(mask.sum()),
        "summary": {
            "cells_treated": int(treated.sum()),
            "people_in_treated_cells": int(pop[treated].sum()),
            "surface_cooling_c": surf,
            "air_cooling_c_estimate": air,
            "feels_like_c": {"before": fl_before, "after": fl_after,
                             "note": "Treated areas, at the chosen conditions; air change assumed "
                                     f"{AIR_PER_SURFACE['low']:.0%}–{AIR_PER_SURFACE['high']:.0%} of surface change."},
            "hotspot_cells": {"before": int(hot_before.sum()), "after": int(hot_after.sum())},
            "people_in_hotspots": {"before": int(pop[hot_before].sum()), "after": int(pop[hot_after].sum())},
            "wards_by_band": {
                "before": wards["band_before"].value_counts().to_dict(),
                "after": wards["band_after"].value_counts().to_dict()},
            "cost": {"capex_lakh": round(capex / 1e5, 1), "opex_lakh_yr": round(opex / 1e5, 1),
                     "ten_year_lakh": round((capex + 10 * opex) / 1e5, 1)},
            "water_kl_day": round(water / 1000, 1),
            "is_estimate": True,
        },
        "breakdown": breakdown,
        "timeline": timeline,
        "ward_changes": changed.to_dict("records"),
        "access_sites": {k: [{"grid_id": cells.loc[i, "grid_id"], "ward_id": cells.loc[i, "ward_id"],
                              "lat": round(float(cells.loc[i, "centroid_lat"]), 5),
                              "lon": round(float(cells.loc[i, "centroid_lon"]), 5)} for i in v]
                         for k, v in access_sites.items()},
        "cell_results": [
            {"grid_id": g, "lst_before": round(float(b), 2), "lst_after": round(float(b + d), 2),
             "delta_t": round(float(d), 2)}
            for g, b, d in zip(cells["grid_id"], lst, mid)
        ],
        "assumptions": [
            "Cooling = published-range endpoints × share of each cell's capacity used; effects saturate when stacked.",
            "Capacity comes from land cover: roofs ≈ 40% and roads ≈ 25% of sealed surface; parks only on open land.",
            f"Tree and park effects scaled by survival {survival:.0%} and ramp up over years.",
            "Costs are planning-grade placeholders, not quotes. Air and feels-like changes are estimates.",
        ],
    }
