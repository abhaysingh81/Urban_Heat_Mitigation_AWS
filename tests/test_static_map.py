"""Feature I map: Amazon Location static map in the HTML heat card."""

import io
import json

import pytest

import pipeline.config as cfg
from api import email_alerts, shelters, static_map, store
from models.risk import ward_table


class FakeAws:
    def __init__(self, fail=False):
        self.fail, self.map_calls, self.puts = fail, [], []

    def client(self, service):
        outer = self

        class Maps:
            def get_static_map(self, **kw):
                if outer.fail:
                    raise RuntimeError("AccessDenied")
                outer.map_calls.append(kw)
                return {"Blob": io.BytesIO(b"\xff\xd8jpeg"), "ContentType": "image/jpeg"}

        class S3:
            def put_object(self, **kw):
                outer.puts.append(kw)
        return {"geo-maps": Maps(), "s3": S3()}[service]


@pytest.fixture()
def city(fake_city, monkeypatch):
    w = ward_table(fake_city)
    spots = [{"name": f"Clinic {i}", "type": "clinic", "lat": float(r.lat) + 0.002, "lon": float(r.lon) + 0.002}
             for i, r in enumerate(w.head(5).itertuples())]
    spots.append({"name": "A Park", "type": "park", "lat": float(w.lat.iloc[0]), "lon": float(w.lon.iloc[0])})
    cfg.city_cooling_spots_file(fake_city).write_text(json.dumps(spots))
    shelters._refuges.cache_clear()
    monkeypatch.setenv("STATIC_MAP_ENABLED", "true")
    monkeypatch.setenv("FRONTEND_BUCKET", "site-bucket")
    monkeypatch.setenv("CORS_ORIGINS", "https://d123.cloudfront.net")
    yield fake_city, w.head(5).to_dict("records")
    shelters._refuges.cache_clear()


def test_disabled_without_the_switch(city, monkeypatch):
    monkeypatch.delenv("STATIC_MAP_ENABLED")
    assert static_map.render(city[0], city[1]) is None


def test_renders_stores_and_returns_a_public_url(city, monkeypatch):
    fake = FakeAws()
    monkeypatch.setattr(static_map.aws, "client", fake.client)
    url = static_map.render(city[0], city[1], day="2026-10-11")
    assert url == "https://d123.cloudfront.net/alert-maps/new_delhi/2026-10-11.jpg"
    put = fake.puts[0]
    assert put["Bucket"] == "site-bucket" and put["Key"] == "alert-maps/new_delhi/2026-10-11.jpg"
    assert put["ContentType"] == "image/jpeg" and put["Body"].startswith(b"\xff\xd8")
    call = fake.map_calls[0]
    assert call["FileName"] == "map" and 64 <= call["Width"] <= 1400 and 64 <= call["Height"] <= 1400
    assert call["PoliticalView"] == "IND" and "Zoom" not in call          # BoundingBox decides the view
    ov = call["CompactOverlay"]
    assert ov.count("label=") == 5 and "#c81e3a" in ov and "#1f6feb" in ov and "A Park" not in ov
    w, s, e, n = map(float, call["BoundingBox"].split(","))
    assert w < e and s < n


def test_full_or_closed_refuges_are_left_off_the_map(city, monkeypatch):
    fake = FakeAws()
    monkeypatch.setattr(static_map.aws, "client", fake.client)
    for r in shelters.refuges(city[0]):
        store.save_shelter_status(city[0], r["id"], "closed")
    static_map.render(city[0], city[1], day="d")
    assert "#1f6feb" not in fake.map_calls[0]["CompactOverlay"]


def test_failure_means_no_map_not_no_alert(city, monkeypatch):
    monkeypatch.setattr(static_map.aws, "client", FakeAws(fail=True).client)
    assert static_map.render(city[0], city[1]) is None


def test_overlay_respects_the_length_limit():
    zones = [{"rank": i, "lat": 28.5, "lon": 77.1} for i in range(1, 6)]
    refuges = [{"lat": 28.5 + i * 1e-4, "lon": 77.1} for i in range(500)]
    assert len(static_map.overlay(zones, refuges)) <= static_map.MAX_OVERLAY


def test_card_shows_the_map_with_alt_text_and_text_link():
    res = {"alert_level": "red", "forecast_tmax_c": 46, "forecast_heat_index_c": 50,
           "top_wards": [{"rank": 1, "ward_name": "Zone 1-1"}]}
    _, html, text = email_alerts.build_card("Delhi", res, ("Stay cool", "ठंडे रहें"),
                                            map_url="https://d123.cloudfront.net/alert-maps/x.jpg")
    assert '<img src="https://d123.cloudfront.net/alert-maps/x.jpg"' in html and 'alt="Map of the' in html
    assert "cool refuges: https://d123.cloudfront.net/alert-maps/x.jpg" in text
    _, html2, _ = email_alerts.build_card("Delhi", res, ("a", "b"))
    assert "<img" not in html2
