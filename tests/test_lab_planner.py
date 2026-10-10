import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app
from models import conditions as cond
from models import planner as P
from models import scenario_lab as sl
from models import ward_factors as wf
from models.interventions import LIBRARY, combine_cooling, cooling_for_units

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no network in tests")
    monkeypatch.setattr("models.forecast.get_forecast", boom)


@pytest.fixture(autouse=True)
def _clear_cache():
    wf._base_cells.cache_clear()
    yield
    wf._base_cells.cache_clear()


# ── interventions ───────────────────────────────────────────
def test_cooling_is_linear_to_reference_then_flat():
    ref = LIBRARY["cool_roofs"].ref_units
    _, half, _ = cooling_for_units("cool_roofs", [ref / 2])
    _, full, _ = cooling_for_units("cool_roofs", [ref])
    _, over, _ = cooling_for_units("cool_roofs", [ref * 3])
    assert half[0] == pytest.approx(full[0] / 2) and over[0] == pytest.approx(full[0])


def test_stacked_cooling_saturates():
    assert abs(combine_cooling(-6.0)) < 6.0 and combine_cooling(-0.1) == pytest.approx(-0.1, abs=0.01)


def test_trees_ramp_up_and_survival_scales():
    _, y0, _ = cooling_for_units("street_trees", [1000], survival=1.0, year=0)
    _, y8, _ = cooling_for_units("street_trees", [1000], survival=1.0, year=8)
    _, low_surv, _ = cooling_for_units("street_trees", [1000], survival=0.5)
    assert y0[0] == 0 and y8[0] < 0 and low_surv[0] == pytest.approx(y8[0] / 2)


# ── conditions ──────────────────────────────────────────────
def test_today_falls_back_without_network(fake_city):
    c = cond.resolve(fake_city, cond.ConditionsRequest(mode="today", climate_shift_c=2))
    assert "unavailable" in c["source"] and c["tmax_c"] == pytest.approx(c["base_tmax_c"] + 2, abs=0.11)


def test_custom_needs_tmax(fake_city):
    with pytest.raises(ValueError):
        cond.resolve(fake_city, cond.ConditionsRequest(mode="custom"))


# ── ward factors ────────────────────────────────────────────
def test_ward_profile_has_12_factors_and_explains(fake_city):
    p = wf.ward_profile(fake_city)
    assert len(p["factors"]) == 12 and p["n_wards"] > 3
    top = p["wards"][0]
    assert set(top["groups"]) == {"hazard", "exposure", "sensitivity", "coping"} and len(top["drivers"]) == 3
    assert abs(sum(p["weights"].values()) - 1) < 1e-3


def test_weights_change_ranking(fake_city):
    a = [w["ward_id"] for w in wf.ward_profile(fake_city, "heat_first")["wards"]]
    b = [w["ward_id"] for w in wf.ward_profile(fake_city, weights={"hazard": 0, "exposure": 0,
                                                                     "sensitivity": 0, "coping": 1})["wards"]]
    assert a != b


def test_water_shortage_raises_risk(fake_city):
    base = {w["ward_id"]: w["risk_score"] for w in wf.ward_profile(fake_city, "access_first")["wards"]}
    short = {w["ward_id"]: w["risk_score"] for w in
             wf.ward_profile(fake_city, "access_first", water_shortage=True)["wards"]}
    assert sum(short.values()) >= sum(base.values())


# ── scenario lab ────────────────────────────────────────────
def test_simulate_cools_and_reports_cost(fake_city):
    r = sl.simulate(fake_city, cond.ConditionsRequest(),
                    [{"key": "cool_roofs", "intensity": 0.5}, {"key": "street_trees", "intensity": 0.5},
                     {"key": "cooling_centres", "params": {"count": 3}}])
    s = r["summary"]
    assert s["surface_cooling_c"]["high"] <= s["surface_cooling_c"]["mid"] <= s["surface_cooling_c"]["low"] < 0
    assert s["cost"]["capex_lakh"] > 0 and s["cost"]["ten_year_lakh"] > s["cost"]["capex_lakh"]
    assert s["people_in_hotspots"]["after"] <= s["people_in_hotspots"]["before"]
    assert len(r["access_sites"]["cooling_centres"]) == 3
    assert r["timeline"][0]["surface_cooling_mid_c"] >= r["timeline"][-1]["surface_cooling_mid_c"]
    json.dumps(r)  # fully serialisable


def test_simulate_ward_target_only_touches_those_wards(fake_city):
    wid = wf.base_cells(fake_city)["ward_id"].iloc[0]
    r = sl.simulate(fake_city, cond.ConditionsRequest(), [{"key": "cool_roofs", "intensity": 1}],
                    {"mode": "wards", "ward_ids": [wid]})
    cells = wf.base_cells(fake_city).set_index("grid_id")
    touched = {c["grid_id"] for c in r["cell_results"] if c["delta_t"] < 0}
    assert touched and all(cells.loc[g, "ward_id"] == wid for g in touched)


def test_simulate_rejects_unknown_intervention(fake_city):
    with pytest.raises(ValueError):
        sl.simulate(fake_city, cond.ConditionsRequest(), [{"key": "magic", "intensity": 1}])


# ── planner ─────────────────────────────────────────────────
def test_plan_respects_budget_ward_and_type_caps(fake_city):
    p = P.plan(P.PlanSpec(fake_city, 3000, years=3, ward_max_share=0.2, type_max_share=0.4))
    ic = p["impact_card"]
    assert ic["spent_lakh"] <= 3000 + 1e-6
    assert all(w["capex_lakh"] <= 0.2 * 3000 + 0.5 for w in p["work_orders"])
    cool = [t for t in p["by_type"] if t["intervention"] not in ("cooling_centres", "water_atms")]
    assert all(t["cost_lakh"] <= 0.4 * 3000 + 0.5 for t in cool)
    assert len(p["budget_by_year"]) == 3 and all(y["capex_lakh"] <= 1000 + 200 for y in p["budget_by_year"])
    json.dumps(p)


def test_plan_mandatory_excluded_and_water_budget(fake_city):
    wards = sorted(set(wf.base_cells(fake_city)["ward_id"]))
    must, skip = wards[-1], wards[0]
    p = P.plan(P.PlanSpec(fake_city, 2000, mandatory_wards=[must], excluded_wards=[skip],
                          water_budget_kl_day=50))
    funded = {w["ward_id"] for w in p["work_orders"]}
    assert must in funded and skip not in funded
    assert p["impact_card"]["water_kl_day"] <= 50 + 0.1


def test_plan_lowers_risk_and_writes_work_orders(fake_city):
    p = P.plan(P.PlanSpec(fake_city, 4000))
    wo = p["work_orders"][0]
    assert wo["lines"] and {"department", "units", "start_quarter", "kpis"} <= set(wo["lines"][0])
    assert any(w["risk_after"] < w["risk_before"] for w in p["work_orders"])


def test_plan_rejects_bad_specs(fake_city):
    with pytest.raises(ValueError):
        P.plan(P.PlanSpec(fake_city, 100, objective="vibes"))
    with pytest.raises(ValueError):
        P.plan(P.PlanSpec(fake_city, 100, ward_min_share=0.2))  # floors exceed budget


# ── API ─────────────────────────────────────────────────────
def test_api_lab_and_planner_round_trip(fake_city):
    assert len(client.get("/api/v1/lab/interventions").json()["interventions"]) == len(LIBRARY)
    r = client.post("/api/v1/lab/simulate?city=new_delhi",
                    json={"conditions": {"climate_shift_c": 1.5, "power_cut": True},
                          "actions": [{"key": "cool_roofs", "intensity": 0.5}]})
    assert r.status_code == 200 and r.json()["conditions"]["power_cut"] is True
    w = client.get("/api/v1/planner/wards?city=new_delhi&preset=equity_first&w_coping=2").json()
    assert w["weights"]["coping"] > w["weights"]["exposure"]
    p = client.post("/api/v1/planner/plan?city=new_delhi",
                    json={"budget_lakh": 2000, "compare": True, "save": True})
    assert p.status_code == 200, p.text
    body = p.json()
    assert len(body["objective_comparison"]) == 4 and body["plan_id"]
    csv = client.get(f"/api/v1/planner/plan/{body['plan_id']}/work-orders.csv")
    assert csv.status_code == 200 and "department" in csv.text.splitlines()[0]
    assert client.get(f"/api/v1/plans/{body['plan_id']}/export?format=geojson").status_code == 200


def test_api_planner_validation_and_preview_city(fake_city):
    assert client.post("/api/v1/planner/plan?city=new_delhi",
                       json={"budget_lakh": 100, "interventions": ["magic"]}).status_code == 400
    assert client.post("/api/v1/planner/plan?city=kochi", json={"budget_lakh": 100}).status_code == 404


# ── city boundary + gap filling ─────────────────────────────
def test_mask_and_prediction_fill_gaps(fake_city):
    import json as _json
    import pandas as pd
    import pipeline.config as cfg
    from api import data_source
    d = cfg.city_processed_dir(fake_city)
    df = pd.read_parquet(cfg.city_real_features_file(fake_city))
    inside = df["grid_id"].iloc[:300].tolist()
    gap = inside[5]
    df.loc[df["grid_id"] == gap, ["lst_c", "lst_mean"]] = None          # no satellite reading
    df.to_parquet(cfg.city_real_features_file(fake_city), index=False)
    pd.DataFrame({"grid_id": df["grid_id"], "lst_pred": 44.0, "lst_q10": 42.0, "lst_q90": 46.0}) \
        .to_parquet(d / "predictions_real.parquet", index=False)
    (d / "city_mask.json").write_text(_json.dumps({"inside": inside, "clipped": {}}))
    t = data_source.read_features(fake_city)
    assert len(t) == 300 and set(t["grid_id"]) == set(inside)          # nothing outside, no gaps inside
    row = t[t["grid_id"] == gap].iloc[0]
    assert row["lst_source"] == "predicted" and row["lst_mean"] == 44.0 and row["tier"] in (
        "critical", "high", "moderate", "normal", "cool")
    wf._base_cells.cache_clear()
    assert set(wf.base_cells(fake_city)["grid_id"]) == set(inside)      # risk/planner use the same cells
