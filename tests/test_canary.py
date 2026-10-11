"""Uptime canary script (infra/canary/python/heartbeat.py) — CloudWatch Synthetics."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infra" / "canary" / "python"))
import heartbeat  # noqa: E402

OK = {"/health": {"status": "ok"},
      "/api/v1/risk/today": {"alert_level": "orange", "stale": False},
      "/api/v1/citizen": {"message_en": "Very hot.", "nearest_cooling_spots": [{}, {}]}}


def fake_fetch(responses, page=b'<div id="root"></div>'):
    def fetch(url, timeout=20.0):
        if url.startswith("https://site"):
            return page
        path = "/" + url.split("/", 3)[3].split("?")[0]
        if path not in responses:
            raise Exception(f"{url} answered HTTP 404")
        return json.dumps(responses[path]).encode()
    return fetch


def test_all_checks_pass(monkeypatch):
    monkeypatch.setattr(heartbeat, "fetch", fake_fetch(OK))
    done = heartbeat.check("https://api", "https://site", "new_delhi", "28.6", "77.2")
    assert done == ["health", "risk-today (orange)", "citizen (2 places)", "citizen page"]


@pytest.mark.parametrize("broken", [
    {"/health": {"status": "down"}},
    {"/api/v1/risk/today": {"alert_level": "purple"}},
    {"/api/v1/citizen": {"message_en": ""}},
])
def test_any_bad_answer_fails_the_run(monkeypatch, broken):
    monkeypatch.setattr(heartbeat, "fetch", fake_fetch({**OK, **broken}))
    with pytest.raises(Exception):
        heartbeat.check("https://api", "https://site", "new_delhi", "28.6", "77.2")


def test_page_without_the_app_shell_fails(monkeypatch):
    monkeypatch.setattr(heartbeat, "fetch", fake_fetch(OK, page=b"<html>503 Service Unavailable</html>"))
    with pytest.raises(Exception, match="app shell"):
        heartbeat.check("https://api", "https://site", "new_delhi", "28.6", "77.2")
