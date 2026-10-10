import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no network in tests")
    monkeypatch.setattr("models.forecast.get_forecast", boom)
    monkeypatch.setattr("agent.heat_officer.tool_forecast", boom)


def test_health_and_version_headers(fake_city):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers["X-Model-Version"] == "test-v0" and r.headers["X-Data-Date"] == "2026-10-10"


def test_preview_city_gets_clear_404_on_risk():
    r = client.get("/api/v1/risk/wards?city=kochi")
    assert r.status_code == 404 and "synthetic preview" in r.json()["detail"]


def test_unknown_city_404():
    assert client.get("/api/v1/risk/wards?city=atlantis").status_code == 404


def test_risk_wards(fake_city):
    r = client.get("/api/v1/risk/wards?city=new_delhi").json()
    assert r["n_wards"] > 3 and "formula" in r["method"] and "age structure" in r["method"]["not_included"]


def test_risk_today_degrades_to_climatology_without_forecast(fake_city):
    r = client.get("/api/v1/risk/today?city=new_delhi").json()
    assert r["stale"] is True and r["source"] == "hot-season climatology" and r["top_wards"]


def test_optimize_save_and_lifecycle(fake_city):
    r = client.post("/api/v1/plans/optimize?city=new_delhi",
                    json={"budget_lakh": 2000, "equity_weight": 0.5, "compare": True, "save": True})
    assert r.status_code == 200
    plan = r.json()
    assert plan["impact_card"]["spent_lakh"] <= 2000 and "equity_comparison" in plan
    pid = plan["plan_id"]
    assert client.put(f"/api/v1/plans/{pid}/status", json={"status": "approved"}).status_code == 200
    assert client.put(f"/api/v1/plans/{pid}/status", json={"status": "draft"}).status_code == 200
    assert client.put(f"/api/v1/plans/{pid}/status", json={"status": "implemented"}).status_code == 400
    assert client.get(f"/api/v1/plans/{pid}").json()["status"] == "draft"


@pytest.mark.parametrize("body", [{"budget_lakh": -5}, {"budget_lakh": 100, "equity_weight": 3},
                                  {"budget_lakh": 100, "interventions": ["moon_base"]}])
def test_optimize_rejects_bad_input(fake_city, body):
    assert client.post("/api/v1/plans/optimize?city=new_delhi", json=body).status_code in (400, 422)


def test_brief_with_pdf_fallback(fake_city):
    ward = client.get("/api/v1/risk/wards?city=new_delhi").json()["wards"][0]["ward_id"]
    r = client.post("/api/v1/brief?city=new_delhi", json={"ward_id": ward, "budget_lakh": 2000})
    assert r.status_code == 200
    b = r.json()
    assert b["numbers_verified"] and b["brief_en"] and b["brief_hi"] and b["source"] == "template"
    assert client.post("/api/v1/brief?city=new_delhi", json={"ward_id": "nope"}).status_code == 404


def test_reports_round_trip_and_privacy(fake_city):
    r = client.post("/api/v1/reports?city=new_delhi", json={"lat": 28.52, "lon": 77.03, "kind": "no_shade"})
    assert r.status_code == 200 and "lat" not in r.json()
    assert client.post("/api/v1/reports?city=new_delhi", json={"lat": 28.52, "lon": 77.03, "kind": "x"}).status_code == 400
    assert client.post("/api/v1/reports?city=new_delhi", json={"lat": 10, "lon": 10, "kind": "no_shade"}).status_code == 400
    s = client.get("/api/v1/reports/summary?city=new_delhi").json()
    assert s["total_reports"] == 1 and s["hot_spots_reported"][0]["reports"] == 1


def test_citizen_payload(fake_city):
    r = client.get("/api/v1/citizen?city=new_delhi&lat=28.52&lon=77.03").json()
    assert r["alert_level"] in ("green", "yellow", "orange", "red")
    assert r["message_en"] and r["message_hi"] and r["nearest_cooling_spots"]


def test_model_card(fake_city):
    assert client.get("/api/v1/model-card").json()["model_version"] == "test-v0"


def test_real_scenario_simulate_returns_range(fake_city):
    r = client.post("/api/v1/scenarios/simulate?city=new_delhi",
                    json={"interventions": [{"type": "tree_cover", "intensity": 0.7}]})
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["is_estimate"] and s["cooling_range_c"]["high"] <= s["cooling_range_c"]["mid"] <= s["cooling_range_c"]["low"] <= 0


def test_exports(fake_city):
    csv = client.get("/api/v1/risk/wards.csv?city=new_delhi")
    assert csv.status_code == 200 and csv.text.startswith("ward_id,") and "attachment" in csv.headers["content-disposition"]
    plan = client.post("/api/v1/plans/optimize?city=new_delhi", json={"budget_lakh": 1500, "save": True}).json()
    pid = plan["plan_id"]
    assert client.get(f"/api/v1/plans/{pid}/export?format=csv").text.startswith("grid_id,")
    gj = client.get(f"/api/v1/plans/{pid}/export?format=geojson").json()
    assert gj["type"] == "FeatureCollection" and len(gj["features"]) == len(plan["items"])
    assert client.get(f"/api/v1/plans/{pid}/export?format=xml").status_code == 400
    assert client.get("/api/v1/plans/nope/export").status_code == 404
