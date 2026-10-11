"""Feature L (live cool-refuge status) and Feature A (CloudWatch activity on /aws)."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import pipeline.config as cfg
from api import live, shelters, store
from api.main import app

client = TestClient(app)

SPOTS = [
    {"name": "Near Clinic", "type": "clinic", "lat": 28.551, "lon": 77.061},
    {"name": "Mid Library", "type": "library", "lat": 28.556, "lon": 77.066},
    {"name": "Far Shelter", "type": "shelter", "lat": 28.565, "lon": 77.075},
    {"name": "Some Park", "type": "park", "lat": 28.552, "lon": 77.062},
    {"name": "Water Tap", "type": "drinking_water", "lat": 28.553, "lon": 77.063},
]


@pytest.fixture()
def city(fake_city, monkeypatch):
    cfg.city_cooling_spots_file(fake_city).write_text(json.dumps(SPOTS))
    shelters._refuges.cache_clear()
    monkeypatch.setattr("models.forecast.get_forecast", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    for var in ("OFFICER_TOKEN", "COGNITO_USER_POOL_ID", "COGNITO_CLIENT_ID"):
        monkeypatch.delenv(var, raising=False)
    yield fake_city
    shelters._refuges.cache_clear()


def _id(city_id, name):
    return next(r["id"] for r in shelters.refuges(city_id) if r["name"] == name)


def test_only_indoor_refuges_are_tracked_with_stable_ids(city):
    refs = shelters.refuges(city)
    assert {r["name"] for r in refs} == {"Near Clinic", "Mid Library", "Far Shelter"}
    assert shelters.spot_id(city, SPOTS[0]) == _id(city, "Near Clinic")      # same place -> same id
    assert len({r["id"] for r in refs}) == 3


def test_status_is_stored_audited_and_goes_stale(city):
    sid = _id(city, "Near Clinic")
    store.save_shelter_status(city, sid, "busy", actor="ward 12")
    doc = store.save_shelter_status(city, sid, "full", actor="ward 12", note="queue outside")
    assert doc["status"] == "full" and [h["status"] for h in doc["history"]] == ["busy", "full"]
    assert shelters.live_status(doc)["status"] == "full"
    later = datetime.now(timezone.utc) + timedelta(hours=shelters.STALE_HOURS + 1)
    old = shelters.live_status(doc, now=later)
    assert old["status"] == "unknown" and old["last_status"] == "full" and old["stale"]
    with pytest.raises(ValueError):
        store.save_shelter_status(city, sid, "overflowing")


def test_api_lists_and_updates_refuges_and_broadcasts(city, monkeypatch):
    sent = []
    monkeypatch.setattr(live, "broadcast", lambda e: sent.append(e) or 1)
    sid = _id(city, "Mid Library")
    r = client.put(f"/api/v1/shelters/{sid}/status?city=new_delhi", json={"status": "full"})
    assert r.status_code == 200 and r.json()["status"] == "full"
    assert sent and sent[0]["type"] == "shelter.updated" and sent[0]["shelter"]["id"] == sid
    lst = client.get("/api/v1/shelters?city=new_delhi&lat=28.551&lon=77.061").json()
    assert [x["name"] for x in lst["refuges"]] == ["Near Clinic", "Mid Library", "Far Shelter"]   # nearest first
    assert lst["counts"]["full"] == 1 and lst["counts"]["unknown"] == 2
    assert client.get("/api/v1/shelters?city=new_delhi&status=full").json()["refuges"][0]["id"] == sid
    assert client.get("/api/v1/shelters?city=new_delhi&q=library").json()["refuges"][0]["name"] == "Mid Library"


def test_api_rejects_bad_status_unknown_refuge_and_needs_officer(city, monkeypatch):
    sid = _id(city, "Near Clinic")
    assert client.put(f"/api/v1/shelters/{sid}/status?city=new_delhi", json={"status": "melting"}).status_code == 422
    assert client.put("/api/v1/shelters/0123456789ab/status?city=new_delhi", json={"status": "open"}).status_code == 404
    monkeypatch.setenv("OFFICER_TOKEN", "s3cret")
    url = f"/api/v1/shelters/{sid}/status?city=new_delhi"
    assert client.put(url, json={"status": "open"}).status_code == 401
    assert client.put(url, json={"status": "open"}, headers={"X-Officer-Token": "s3cret"}).status_code == 200
    assert client.get("/api/v1/shelters?city=kochi").status_code == 404                 # preview city


def test_citizen_page_skips_full_and_closed_refuges(city):
    near, mid = _id(city, "Near Clinic"), _id(city, "Mid Library")
    store.save_shelter_status(city, near, "full")
    store.save_shelter_status(city, mid, "closed")
    d = client.get("/api/v1/citizen?city=new_delhi&lat=28.551&lon=77.061").json()
    names = [s["name"] for s in d["nearest_cooling_spots"]]
    assert "Near Clinic" not in names and "Mid Library" not in names and len(names) == 3
    assert d["refuges_skipped_full_or_closed"] == 2
    statuses = {s["name"]: s["status"] for s in d["nearest_cooling_spots"]}
    assert statuses["Some Park"] is None and statuses["Far Shelter"] == "unknown"   # parks not tracked


# ── Feature A: CloudWatch activity ──────────────────────────
class FakeCloudWatch:
    def __init__(self):
        self.calls = []

    def get_metric_data(self, MetricDataQueries, StartTime, EndTime):
        self.calls.append((MetricDataQueries, StartTime, EndTime))
        values = {"requests": [120.0, 80.0], "errors": [1.0], "throttles": [], "p95": [850.4, 912.6],
                  "alerts": [1.0, 0.0, 1.0], "refresh_ok": [1.0] * 7, "refresh_failed": [0.0] * 7}
        return {"MetricDataResults": [{"Id": q["Id"], "Values": values[q["Id"]]} for q in MetricDataQueries]}


def test_activity_is_unavailable_outside_lambda(monkeypatch):
    from api.routers import system
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    system._cache.pop("cw", None)
    assert system.get_cloudwatch_activity() == "unavailable"


def test_activity_sums_cloudwatch_metrics_on_lambda(monkeypatch):
    from api.routers import system
    fake = FakeCloudWatch()
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "heatrelief-ApiFunction-x")
    monkeypatch.setattr(system.aws, "client", lambda service: fake)
    system._cache.pop("cw", None)
    a = system.get_cloudwatch_activity()
    assert a["api_requests_24h"] == 200 and a["api_errors_24h"] == 1 and a["api_throttles_24h"] == 0
    assert a["api_p95_ms_24h"] == 912.6 and a["alerts_sent_7d"] == 2 and a["daily_refresh_ok_7d"] == 7
    dims = fake.calls[0][0][0]["MetricStat"]["Metric"]["Dimensions"]
    assert dims == [{"Name": "FunctionName", "Value": "heatrelief-ApiFunction-x"}]
    assert system.get_cloudwatch_activity() is a and len(fake.calls) == 2       # cached: no new calls
    system._cache.pop("cw", None)


def test_activity_failure_degrades(monkeypatch):
    from api.routers import system

    class Boom:
        def get_metric_data(self, **k):
            raise RuntimeError("AccessDenied")
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "fn")
    monkeypatch.setattr(system.aws, "client", lambda service: Boom())
    system._cache.pop("cw", None)
    assert system.get_cloudwatch_activity() == "unavailable"
    system._cache.pop("cw", None)
