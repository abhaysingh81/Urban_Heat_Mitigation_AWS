import time

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _saved_plan():
    r = client.post("/api/v1/plans/optimize?city=new_delhi", json={"budget_lakh": 500, "save": True})
    assert r.status_code == 200, r.text
    return r.json()["plan_id"]


def test_status_change_needs_token_when_configured(fake_city, monkeypatch):
    monkeypatch.setattr("models.forecast.get_forecast", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    pid = _saved_plan()
    monkeypatch.setenv("OFFICER_TOKEN", "s3cret")
    url = f"/api/v1/plans/{pid}/status"
    assert client.put(url, json={"status": "approved"}).status_code == 401
    assert client.put(url, json={"status": "approved"}, headers={"X-Officer-Token": "nope"}).status_code == 401
    assert client.put(url, json={"status": "approved"}, headers={"X-Officer-Token": "s3cret"}).status_code == 200


def test_slow_llm_falls_back_to_template_within_budget(fake_city, monkeypatch):
    from agent import heat_officer as ho
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    monkeypatch.setenv("BRIEF_DEADLINE_S", "6")
    monkeypatch.setattr(ho, "tool_forecast", lambda c: {"unavailable": True})

    def slow(*a, **k):
        time.sleep(8)
        return {"en": "x", "hi": "y"}
    monkeypatch.setattr(ho, "_run_llm", slow)
    wid = ho.ward_table(fake_city)["ward_id"].iloc[0]
    t = time.monotonic()
    out = ho.generate_brief(fake_city, wid, 1000, 0.5)
    assert time.monotonic() - t < 7.5
    assert out["source"] == "template" and "timed out" in out["note"]
