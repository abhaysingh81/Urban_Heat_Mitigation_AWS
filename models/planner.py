"""
Ward Planner: a constrained, multi-intervention city heat plan with work orders.

An officer sets a capital budget phased over years, an objective, which
interventions are allowed (with optional unit caps), per-ward floors and
ceilings, mandatory and excluded wards, an optional water budget, and the
planning conditions. The planner then:

1. places access sites (cooling centres, drinking-water points) from a share of
   the budget where vulnerable people are farthest from an existing one;
2. funds ward floors (mandatory wards and the equity floor) first;
3. fills the rest greedily by marginal benefit per rupee (benefit averaged over a
   10-year horizon, so slow-maturing trees are not over-valued), in steps of 25% of a
   cell's capacity, several interventions per cell, with saturating returns
   (lazy greedy: a stale score is re-computed before it is accepted);
4. phases the chosen actions into years by the annual budget, in priority
   order, and adds procurement lead times to get quarters;
5. projects ward risk after the plan on the same scale as today, and writes
   work orders per ward (units, cells, cost, upkeep, water, department,
   quarters, KPIs).

Objectives (benefit per step = |marginal surface cooling| × weight):
  cooling  weight = hazard (hottest cells first, regardless of people)
  people   weight = people in the cell
  equity   weight = people × (0.3 + 0.7 × vulnerability)
  risk     weight = people × ward risk score today
All results are planning estimates.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from models import conditions as cond
from models import ward_factors as wf
from models.interventions import (
    ACCESS_KEYS, COOLING_KEYS, LIBRARY, MAX_CELL_COOLING_C, combine_cooling, cooling_for_units, water_l_day,
)
from models.scenario_lab import place_access, project, _ward_compare

OBJECTIVES = ("people", "cooling", "equity", "risk")
STEP = 0.25
MAX_CANDIDATE_CELLS = 2500
PROTECTED_COOLING_C = -0.2


@dataclass
class PlanSpec:
    city_id: str
    budget_lakh: float
    years: int = 3
    objective: str = "equity"
    interventions: list[str] = field(default_factory=lambda: list(COOLING_KEYS) + list(ACCESS_KEYS))
    unit_caps: dict[str, float] = field(default_factory=dict)
    params: dict[str, dict] = field(default_factory=dict)
    access_share: float = 0.15
    ward_min_share: float = 0.0
    ward_max_share: float = 0.25
    type_max_share: float = 0.40     # no single intervention may take more than this share of the budget
    mandatory_wards: list[str] = field(default_factory=list)
    excluded_wards: list[str] = field(default_factory=list)
    water_budget_kl_day: float | None = None
    survival: float = 0.7
    preset: str = "balanced"
    conditions: cond.ConditionsRequest = field(default_factory=cond.ConditionsRequest)


def _validate(s: PlanSpec):
    if s.budget_lakh <= 0:
        raise ValueError("budget_lakh must be positive")
    if not 1 <= s.years <= 10:
        raise ValueError("years must be between 1 and 10")
    if s.objective not in OBJECTIVES:
        raise ValueError(f"objective must be one of {OBJECTIVES}")
    bad = [k for k in s.interventions if k not in LIBRARY]
    if bad:
        raise ValueError(f"unknown interventions {bad}; valid: {list(LIBRARY)}")
    if not s.interventions:
        raise ValueError("choose at least one intervention")
    if not 0 <= s.access_share <= 0.6:
        raise ValueError("access_share must be between 0 and 0.6")
    if not 0 <= s.ward_min_share <= 0.2:
        raise ValueError("ward_min_share must be between 0 and 0.2")
    if not 0.01 <= s.ward_max_share <= 1:
        raise ValueError("ward_max_share must be between 0.01 and 1")
    if not 0 < s.survival <= 1:
        raise ValueError("survival must be in (0, 1]")
    if not 0.05 <= s.type_max_share <= 1:
        raise ValueError("type_max_share must be between 0.05 and 1")
    if set(s.mandatory_wards) & set(s.excluded_wards):
        raise ValueError("a ward cannot be both mandatory and excluded")
    if s.water_budget_kl_day is not None and s.water_budget_kl_day < 0:
        raise ValueError("water_budget_kl_day must be non-negative")


def horizon_factor(key: str, params: dict | None = None, horizon: int = 10) -> float:
    years = LIBRARY[key].years_to_full
    if key == "street_trees" and (params or {}).get("species") == "fast_shade":
        years = 5
    if years <= 0:
        return 1.0
    return float(np.mean([min(1.0, y / years) for y in range(1, horizon + 1)]))


class _State:
    def __init__(self, cells, spec, weight, keys):
        self.cells, self.spec, self.weight, self.keys = cells, spec, weight, keys
        n = len(cells)
        self.caps = {k: LIBRARY[k].capacity(cells).to_numpy() for k in keys}
        self.units = {k: np.zeros(n) for k in keys}
        self.steps = {k: np.zeros(n, int) for k in keys}
        self.s_mid = np.zeros(n)  # summed (pre-saturation) mid cooling per cell
        self.ward = cells["ward_id"].to_numpy()
        self.ward_spent: dict[str, float] = {}
        self.spent = 0.0
        self.water_l = 0.0
        self.type_units = {k: 0.0 for k in keys}
        self.type_spent = {k: 0.0 for k in keys}
        self.order: list[tuple[int, str, float, float]] = []  # (cell, key, units, cost_lakh)
        self.per_step_mid = {}
        for k in keys:
            _, m, _ = cooling_for_units(k, self.caps[k] * STEP, spec.survival, spec.params.get(k))
            # score on the average effect over the planning horizon, so slow-maturing
            # trees and parks compete fairly with immediate measures like cool roofs
            self.per_step_mid[k] = m * horizon_factor(k, spec.params.get(k))

    def step_cost(self, i, k):
        return self.caps[k][i] * STEP * LIBRARY[k].capex_inr / 1e5

    def score(self, i, k):
        if self.steps[k][i] >= int(1 / STEP) or self.caps[k][i] <= 0:
            return None
        cost = self.step_cost(i, k)
        if cost <= 0:
            return None
        d = self.per_step_mid[k][i]
        marg = abs(combine_cooling(self.s_mid[i] + d) - combine_cooling(self.s_mid[i]))
        if marg <= 1e-6:
            return None
        return marg * self.weight[i] / cost

    def fits(self, i, k, budget_left, ward_cap):
        cost = self.step_cost(i, k)
        if cost > budget_left + 1e-9:
            return False
        w = self.ward[i]
        if self.ward_spent.get(w, 0.0) + cost > ward_cap + 1e-9:
            return False
        if self.type_spent[k] + cost > self.spec.type_max_share * self.spec.budget_lakh + 1e-9:
            return False
        u = self.caps[k][i] * STEP
        cap = self.spec.unit_caps.get(k)
        if cap is not None and self.type_units[k] + u > cap + 1e-9:
            return False
        if self.spec.water_budget_kl_day is not None:
            wl = float(water_l_day(k, [u], self.spec.params.get(k))[0])
            if wl > 0 and self.water_l + wl > self.spec.water_budget_kl_day * 1000 + 1e-6:
                return False
        return True

    def take(self, i, k):
        u = self.caps[k][i] * STEP
        cost = self.step_cost(i, k)
        self.units[k][i] += u
        self.steps[k][i] += 1
        self.s_mid[i] += self.per_step_mid[k][i]
        self.ward_spent[self.ward[i]] = self.ward_spent.get(self.ward[i], 0.0) + cost
        self.spent += cost
        self.type_units[k] += u
        self.type_spent[k] += cost
        self.water_l += float(water_l_day(k, [u], self.spec.params.get(k))[0])
        self.order.append((i, k, u, cost))


def _greedy(st: _State, cand: np.ndarray, budget_total: float, ward_cap: float,
            stop_at: dict[str, float] | None = None):
    """Lazy greedy over (cell, intervention) steps restricted to `cand` cells.
    stop_at: ward -> spend target; when given, only wards below target are funded."""
    heap = []
    for i in np.flatnonzero(cand):
        for k in st.keys:
            s = st.score(i, k)
            if s is not None:
                heap.append((-s, int(i), k))
    heapq.heapify(heap)
    while heap:
        neg, i, k = heapq.heappop(heap)
        if stop_at is not None and st.ward_spent.get(st.ward[i], 0.0) >= stop_at.get(st.ward[i], 0.0):
            continue
        s = st.score(i, k)
        if s is None:
            continue
        if heap and s < -heap[0][0] - 1e-12:  # stale: re-queue with fresh score
            heapq.heappush(heap, (-s, i, k))
            continue
        if not st.fits(i, k, budget_total - st.spent, ward_cap):
            continue
        st.take(i, k)
        nxt = st.score(i, k)
        if nxt is not None:
            heapq.heappush(heap, (-nxt, i, k))
        if budget_total - st.spent < 0.5:
            break


def plan(spec: PlanSpec) -> dict:
    _validate(spec)
    conditions = cond.resolve(spec.city_id, spec.conditions)
    cells = wf.base_cells(spec.city_id)
    cells = cells[cells["lst_hazard"].notna()].reset_index(drop=True)
    all_wards = set(cells["ward_id"])
    unknown = [w for w in spec.mandatory_wards + spec.excluded_wards if w not in all_wards]
    if unknown:
        raise ValueError(f"unknown ward ids {unknown[:5]}")
    included = ~cells["ward_id"].isin(spec.excluded_wards).to_numpy()
    if not included.any():
        raise ValueError("every ward is excluded")

    wts = wf.resolve_weights(None, spec.preset, conditions["power_cut"])
    ref = wf.aggregate(cells)
    today = wf.score(wf.aggregate(cells, water_shortage=conditions["water_shortage"]), ref, wts)
    ward_risk = dict(zip(today["ward_id"], today["risk_score"]))

    pop = cells["pop_total"].fillna(0).to_numpy()
    vuln = cells["vuln_pct"].fillna(0).to_numpy()
    hazard = cells["hazard_pct"].fillna(0).to_numpy()
    wrisk = cells["ward_id"].map(ward_risk).fillna(0).to_numpy() / 100
    weight = {"cooling": 0.2 + 0.8 * hazard, "people": pop, "equity": pop * (0.3 + 0.7 * vuln),
              "risk": pop * wrisk}[spec.objective]

    budget = spec.budget_lakh
    ward_cap = spec.ward_max_share * budget
    cool_keys = [k for k in spec.interventions if k in COOLING_KEYS]
    access_keys = [k for k in spec.interventions if k in ACCESS_KEYS]
    st = _State(cells, spec, weight, cool_keys)

    # 1. access sites
    access_sites: dict[str, list[int]] = {}
    access_spent = 0.0
    if access_keys and spec.access_share > 0:
        share_each = {"cooling_centres": 0.6, "water_atms": 0.4}
        tot = sum(share_each[k] for k in access_keys)
        for k in access_keys:
            b = budget * spec.access_share * share_each[k] / tot
            n = int(b // (LIBRARY[k].capex_inr / 1e5))
            if spec.water_budget_kl_day is not None:  # access sites use water too; keep half for cooling
                room = spec.water_budget_kl_day * 1000 * 0.5 - st.water_l
                n = min(n, max(0, int(room // LIBRARY[k].water_l_day)))
            col = "dist_refuge_m" if k == "cooling_centres" else "dist_water_m"
            dist = cells[col].to_numpy()
            if k == "water_atms" and conditions["water_shortage"]:
                dist = np.full(len(cells), wf.DIST_CAP_M)
            sites, _ = place_access(cells, k, n, included, dist)
            access_sites[k] = sites
            cost = len(sites) * LIBRARY[k].capex_inr / 1e5
            access_spent += cost
            for i in sites:
                w = st.ward[i]
                st.ward_spent[w] = st.ward_spent.get(w, 0.0) + LIBRARY[k].capex_inr / 1e5
                st.water_l += LIBRARY[k].water_l_day
                st.order.append((i, k, 1.0, LIBRARY[k].capex_inr / 1e5))
    st.spent += access_spent

    # candidate cells: most heat-exposed people first, all mandatory-ward cells included
    prio = (0.2 + 0.8 * hazard) * (pop + 1)
    cand = included.copy()
    if cand.sum() > MAX_CANDIDATE_CELLS:
        thr = np.sort(prio[included])[-MAX_CANDIDATE_CELLS]
        cand = included & ((prio >= thr) | cells["ward_id"].isin(spec.mandatory_wards).to_numpy())

    # 2. floors: mandatory wards and the equity floor
    floors = {}
    if spec.ward_min_share > 0:
        floors = {w: spec.ward_min_share * budget for w in set(cells.loc[included, "ward_id"])}
    for w in spec.mandatory_wards:
        floors[w] = max(floors.get(w, 0.0), max(spec.ward_min_share, 0.03) * budget)
    if sum(floors.values()) > budget - access_spent + 1e-6:
        raise ValueError("ward floors add up to more than the budget; lower ward_min_share or mandatory wards")
    if floors and cool_keys:
        floor_cells = cand & cells["ward_id"].isin(list(floors)).to_numpy()
        _greedy(st, floor_cells, budget, ward_cap, stop_at=floors)

    # 3. global fill
    if cool_keys:
        _greedy(st, cand, budget, ward_cap)

    # 4. phase into years
    annual = budget / spec.years
    year_spend = [0.0] * spec.years
    scheduled = []
    yr = 0
    for (i, k, u, cost) in st.order:
        while yr < spec.years - 1 and year_spend[yr] + cost > annual + 1e-6:
            yr += 1
        year_spend[yr] += cost
        start_q = yr * 4 + 1
        scheduled.append((i, k, u, cost, yr + 1, start_q, start_q + LIBRARY[k].lead_quarters))

    return _report(spec, conditions, cells, st, access_sites, scheduled, year_spend, wts, ward_risk)


def _report(spec, conditions, cells, st, access_sites, scheduled, year_spend, wts, ward_risk):
    n = len(cells)
    units = {k: np.zeros(n) for k in spec.interventions}
    for (i, k, u, *_rest) in scheduled:
        units[k][i] += u
    proj = project(cells, units, spec.params, spec.survival, access_sites=access_sites,
                   water_shortage=conditions["water_shortage"])
    mid, lo, hi = proj["mid"], proj["low"], proj["high"]
    wards = _ward_compare(cells, proj["cells_after"], wts, conditions["water_shortage"],
                          bool(access_sites.get("water_atms")))
    wmap = wards.set_index("ward_id")

    pop = cells["pop_total"].fillna(0).to_numpy()
    cooled = mid <= PROTECTED_COOLING_C
    access_cells = np.zeros(n, bool)
    for col in ("dist_refuge_m", "dist_water_m"):
        improved = (proj["cells_after"][col].to_numpy() < 1000) & (cells[col].to_numpy() >= 1000)
        access_cells |= improved
    protected = cooled | access_cells
    lst = cells["lst_hazard"].to_numpy()
    mean, std = lst.mean(), lst.std()
    hot_before, hot_after = lst > mean + std, (lst + mid) > mean + std

    items = []
    for (i, k, u, cost, year, sq, fq) in scheduled:
        c = cells.loc[i]
        iv = LIBRARY[k]
        items.append({
            "grid_id": c["grid_id"], "ward_id": c["ward_id"], "ward_name": c["ward_name"],
            "lat": round(float(c["centroid_lat"]), 5), "lon": round(float(c["centroid_lon"]), 5),
            "intervention": k, "label": iv.label, "unit": iv.unit, "units": round(float(u), 2),
            "cost_lakh": round(float(cost), 2), "people": int(round(pop[i])),
            "cooling_c": {"low": round(float(lo[i]), 2), "mid": round(float(mid[i]), 2),
                          "high": round(float(hi[i]), 2)},
            "vulnerability": round(float(c["vuln_pct"]), 3), "year": year,
            "start_quarter": sq, "finish_quarter": fq, "department": iv.department,
        })

    # work orders per ward
    orders: dict[str, dict] = {}
    for it in items:
        w = orders.setdefault(it["ward_id"], {"ward_id": it["ward_id"], "ward_name": it["ward_name"],
                                              "lines": {}, "capex_lakh": 0.0})
        ln = w["lines"].setdefault(it["intervention"], {
            "intervention": it["intervention"], "label": it["label"], "unit": it["unit"], "units": 0.0,
            "cells": [], "capex_lakh": 0.0, "opex_lakh_yr": 0.0, "water_kl_day": 0.0,
            "department": it["department"], "start_quarter": it["start_quarter"],
            "finish_quarter": it["finish_quarter"], "kpis": list(LIBRARY[it["intervention"]].kpis)})
        iv = LIBRARY[it["intervention"]]
        ln["units"] += it["units"]
        if it["grid_id"] not in [c["grid_id"] for c in ln["cells"]]:
            ln["cells"].append({"grid_id": it["grid_id"], "lat": it["lat"], "lon": it["lon"]})
        ln["capex_lakh"] += it["cost_lakh"]
        ln["opex_lakh_yr"] += it["units"] * iv.opex_inr_yr / 1e5
        ln["water_kl_day"] += float(water_l_day(it["intervention"], [it["units"]],
                                                spec.params.get(it["intervention"]))[0]) / 1000
        ln["start_quarter"] = min(ln["start_quarter"], it["start_quarter"])
        ln["finish_quarter"] = max(ln["finish_quarter"], it["finish_quarter"])
        w["capex_lakh"] += it["cost_lakh"]
    ward_idx = cells.groupby("ward_id").indices
    work_orders = []
    for wid, w in orders.items():
        idx = ward_idx[wid]
        lines = []
        for ln in w["lines"].values():
            for kf in ("units", "capex_lakh", "opex_lakh_yr", "water_kl_day"):
                ln[kf] = round(ln[kf], 1 if kf != "units" else 2)
            ln["n_cells"] = len(ln["cells"])
            lines.append(ln)
        lines.sort(key=lambda x: -x["capex_lakh"])
        r = wmap.loc[wid] if wid in wmap.index else None
        work_orders.append({
            "ward_id": wid, "ward_name": w["ward_name"], "capex_lakh": round(w["capex_lakh"], 1),
            "opex_lakh_yr": round(sum(l["opex_lakh_yr"] for l in lines), 1),
            "water_kl_day": round(sum(l["water_kl_day"] for l in lines), 1),
            "people": int(pop[idx].sum()), "people_protected": int(pop[idx][protected[idx]].sum()),
            "risk_before": None if r is None else float(r["risk_score_before"]),
            "risk_after": None if r is None else float(r["risk_score_after"]),
            "band_before": None if r is None else r["band_before"],
            "band_after": None if r is None else r["band_after"],
            "cooling_mid_c": round(float((mid[idx] * pop[idx]).sum() / max(pop[idx].sum(), 1)), 2),
            "lines": lines,
        })
    work_orders.sort(key=lambda w: -(w["risk_before"] or 0))

    by_type, by_dept = {}, {}
    for it in items:
        iv = LIBRARY[it["intervention"]]
        t = by_type.setdefault(it["intervention"], {"intervention": it["intervention"], "label": iv.label,
                                                    "unit": iv.unit, "units": 0.0, "count": 0, "cost_lakh": 0.0})
        t["units"] += it["units"]; t["count"] += 1; t["cost_lakh"] += it["cost_lakh"]
        d = by_dept.setdefault(iv.department, {"department": iv.department, "cost_lakh": 0.0, "actions": 0})
        d["cost_lakh"] += it["cost_lakh"]; d["actions"] += 1
    for t in by_type.values():
        t["units"] = round(t["units"], 1); t["cost_lakh"] = round(t["cost_lakh"], 1)
    for d in by_dept.values():
        d["cost_lakh"] = round(d["cost_lakh"], 1)

    opex = sum(w["opex_lakh_yr"] for w in work_orders)
    water = sum(w["water_kl_day"] for w in work_orders)
    people_protected = int(pop[protected].sum())
    treated = mid < -1e-6
    pw = lambda x: float((x[treated] * pop[treated]).sum() / max(pop[treated].sum(), 1)) if treated.any() else 0.0
    surf = {"low": round(pw(lo), 2), "mid": round(pw(mid), 2), "high": round(pw(hi), 2)}

    timeline = []
    for year in range(0, 11):
        p = project(cells, units, spec.params, spec.survival, year=year)
        timeline.append({"year": year, "pop_weighted_cooling_mid_c": round(pw(p["mid"]), 2)})

    from models.interventions import AIR_PER_SURFACE
    t, rh = conditions["tmax_c"], conditions["humidity_pct"]
    return {
        "request": _spec_json(spec),
        "conditions": conditions,
        "weights": wts,
        "items": items,
        "work_orders": work_orders,
        "by_ward": [{"ward_id": w["ward_id"], "ward_name": w["ward_name"], "cost_lakh": w["capex_lakh"],
                     "n_actions": sum(len(l["cells"]) for l in w["lines"]), "people": w["people"]}
                    for w in sorted(work_orders, key=lambda w: -w["capex_lakh"])],
        "by_type": sorted(by_type.values(), key=lambda t: -t["cost_lakh"]),
        "by_department": sorted(by_dept.values(), key=lambda d: -d["cost_lakh"]),
        "budget_by_year": [{"year": y + 1, "capex_lakh": round(float(v), 1)} for y, v in enumerate(year_spend)],
        "impact_card": {
            "budget_lakh": spec.budget_lakh, "spent_lakh": round(st.spent, 1),
            "n_actions": len(items), "wards_funded": len(work_orders),
            "people_protected": people_protected,
            "cost_per_person_inr": round(st.spent * 1e5 / people_protected) if people_protected else None,
            "cooling_c": surf,
            "feels_like_c": {"before": cond.feels_like(t, rh, 0),
                             "after": cond.feels_like(t, rh, surf["mid"] * AIR_PER_SURFACE["mid"])},
            "opex_lakh_yr": round(opex, 1), "ten_year_cost_lakh": round(st.spent + 10 * opex, 1),
            "water_kl_day": round(water, 1),
            "people_in_hotspots": {"before": int(pop[hot_before].sum()), "after": int(pop[hot_after].sum())},
            "wards_by_band": {"before": wards["band_before"].value_counts().to_dict(),
                              "after": wards["band_after"].value_counts().to_dict()},
            "share_of_spend_in_high_vulnerability_cells": round(
                sum(i["cost_lakh"] for i in items if i["vulnerability"] >= 0.75) / st.spent, 3) if st.spent else 0.0,
            "assumptions": [
                "Cooling = published-range endpoints × share of each cell's capacity used; stacked effects saturate.",
                "Capacity from land cover: roofs ≈ 40% and roads ≈ 25% of sealed surface; parks only on open land.",
                f"Tree and park effects scaled by survival {spec.survival:.0%}, ramping up over years.",
                f"Protected = surface cooling of at least {abs(PROTECTED_COOLING_C)} °C, or a new cool refuge / water "
                "point within 1 km where there was none.",
                "Costs and upkeep are planning-grade placeholders per unit, not quotes.",
            ],
        },
        "timeline": timeline,
    }


def _spec_json(s: PlanSpec) -> dict:
    from dataclasses import asdict
    d = asdict(s)
    return d


def compare_objectives(spec: PlanSpec) -> list[dict]:
    out = []
    for obj in OBJECTIVES:
        p = plan(PlanSpec(**{**spec.__dict__, "objective": obj}))
        ic = p["impact_card"]
        out.append({"objective": obj, "people_protected": ic["people_protected"],
                    "cooling_mid_c": ic["cooling_c"]["mid"], "spent_lakh": ic["spent_lakh"],
                    "cost_per_person_inr": ic["cost_per_person_inr"],
                    "high_vulnerability_spend_share": ic["share_of_spend_in_high_vulnerability_cells"],
                    "severe_wards_after": ic["wards_by_band"]["after"].get("severe", 0),
                    "people_in_hotspots_after": ic["people_in_hotspots"]["after"]})
    return out
