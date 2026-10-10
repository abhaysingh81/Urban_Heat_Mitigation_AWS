"""
Golden-path smoke test / demo rehearsal.

    python scripts/smoke_golden_path.py [--city new_delhi] [--offline] [--base http://localhost:8000]

Walks the whole chain once: forecast refresh -> ward risk -> optimizer ->
Hindi+English brief -> citizen payload -> citizen report -> report summary.
Without --base it runs the FastAPI app in-process (needs the built real data).
--offline replaces the live forecast with a fixed hot day, so it works with no network.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="new_delhi")
    ap.add_argument("--base", default=None, help="hit a deployed API instead of running in-process")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()

    if a.base:
        import requests

        class C:
            def get(self, p, **k): return requests.get(a.base + p, timeout=60, **k)
            def post(self, p, **k): return requests.post(a.base + p, timeout=120, **k)
            def put(self, p, **k): return requests.put(a.base + p, timeout=60, **k)
        client = C()
    else:
        if a.offline:
            import models.forecast as fc
            fc.get_forecast = lambda city, days=3: {"city_id": city, "days": [], "today": {
                "date": "2026-10-10", "tmax_c": 44.0, "humidity_pct": 30, "heat_index_c": 45.0, "alert_level": "orange"}} | {
                "days": [{"date": "2026-10-10", "tmax_c": 44.0, "humidity_pct": 30, "heat_index_c": 45.0, "alert_level": "orange"}]}
            import agent.heat_officer as ho
            ho.tool_forecast = lambda city: {"today_max_temp_c": 44.0, "today_heat_index_c": 45.0, "today_alert_level": "orange"}
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)

    city, steps, failed = a.city, [], False

    def step(name, ok, detail=""):
        nonlocal failed
        failed |= not ok
        steps.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")

    r = client.get("/health"); step("health", r.status_code == 200)
    r = client.get(f"/api/v1/risk/today?city={city}"); ok = r.status_code == 200
    today = r.json() if ok else {}
    step("forecast -> risk today", ok and bool(today.get("top_wards")),
         f"alert={today.get('alert_level')} stale={today.get('stale')} source={today.get('source')}")
    r = client.get(f"/api/v1/risk/wards?city={city}"); wards = r.json().get("wards", []) if r.status_code == 200 else []
    step("ward risk table", len(wards) > 3, f"{len(wards)} wards, top={wards[0]['ward_name'] if wards else None}")
    r = client.post(f"/api/v1/plans/optimize?city={city}", json={
        "budget_lakh": 5000, "equity_weight": 0.5, "compare": True, "save": True})
    plan = r.json() if r.status_code == 200 else {}
    ic = plan.get("impact_card", {})
    step("optimizer within budget", r.status_code == 200 and ic.get("spent_lakh", 1e18) <= 5000,
         f"spent={ic.get('spent_lakh')} people={ic.get('people_protected')}")
    if plan.get("plan_id"):
        s = client.put(f"/api/v1/plans/{plan['plan_id']}/status", json={"status": "approved"})
        step("plan approval + audit", s.status_code == 200)
    if wards:
        r = client.post(f"/api/v1/brief?city={city}", json={"ward_id": wards[0]["ward_id"], "budget_lakh": 5000})
        b = r.json() if r.status_code == 200 else {}
        step("Hindi+English brief (numbers verified)", r.status_code == 200 and b.get("numbers_verified") is True,
             f"source={b.get('source')} pdf={'yes' if b.get('pdf_url') else 'no'}")
        lat, lon = wards[0]["lat"], wards[0]["lon"]
        r = client.get(f"/api/v1/citizen?city={city}&lat={lat}&lon={lon}")
        c = r.json() if r.status_code == 200 else {}
        step("citizen payload", r.status_code == 200 and bool(c.get("message_hi")),
             f"level={c.get('alert_level')} spots={len(c.get('nearest_cooling_spots', []))}")
        r = client.post(f"/api/v1/reports?city={city}", json={"lat": lat, "lon": lon, "kind": "no_shade"})
        step("citizen report", r.status_code == 200)
        r = client.get(f"/api/v1/reports/summary?city={city}")
        step("report feeds back into candidate sites", r.status_code == 200 and r.json().get("total_reports", 0) >= 1)
    r = client.get("/api/v1/model-card"); step("model card", r.status_code == 200)
    print(f"\n{sum(steps)}/{len(steps)} steps passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
