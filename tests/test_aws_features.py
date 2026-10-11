"""AWS feature paths (alert signup, photo moderation, simulation), with AWS calls stubbed."""

import json

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from api.main import app
from api.routers import alerts
from lambdas.moderate_photo import app as moderate
from lambdas.refresh_forecast import app as refresh

client = TestClient(app)
SIGNUP = {"email": "citizen@example.com", "city": "new_delhi", "min_level": "orange",
          "consent": True, "website": ""}


class Recorder:
    """Stands in for a boto3 client: records calls, returns canned responses."""

    def __init__(self, **responses):
        self.calls, self.responses = [], responses

    def __getattr__(self, name):
        def call(**kwargs):
            self.calls.append((name, kwargs))
            res = self.responses.get(name, {})
            if isinstance(res, Exception):
                raise res
            return res
        return call

    def names(self):
        return [n for n, _ in self.calls]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no network in tests")
    monkeypatch.setattr("models.forecast.get_forecast", boom)


@pytest.fixture
def sns(monkeypatch):
    rec = Recorder()
    monkeypatch.setenv("ALERT_TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:alerts")
    monkeypatch.delenv("RATE_LIMIT_TABLE", raising=False)
    monkeypatch.setattr(alerts.aws, "client", lambda service: rec)
    alerts._ip_signups.clear()
    yield rec
    alerts._ip_signups.clear()


# ── alert signup ─────────────────────────────────────────────
def test_subscribe_route_and_filter_policy(sns):
    r = client.post("/api/v1/alerts/subscribe", json=SIGNUP)
    assert r.status_code == 202
    (name, kw), = sns.calls
    assert name == "subscribe" and kw["Protocol"] == "email" and kw["Endpoint"] == SIGNUP["email"]
    assert json.loads(kw["Attributes"]["FilterPolicy"]) == {
        "city": ["new_delhi"], "level_num": [{"numeric": [">=", 2]}]}


def test_subscribe_honeypot_and_bad_input_never_reach_sns(sns):
    assert client.post("/api/v1/alerts/subscribe", json={**SIGNUP, "website": "spam"}).status_code == 202
    assert client.post("/api/v1/alerts/subscribe", json={**SIGNUP, "consent": False}).status_code == 400
    assert client.post("/api/v1/alerts/subscribe", json={**SIGNUP, "city": "kochi"}).status_code == 422
    assert client.post("/api/v1/alerts/subscribe", json={**SIGNUP, "email": "not-an-email"}).status_code == 422
    assert sns.calls == []


def test_subscribe_is_rate_limited_per_ip_with_the_same_answer(sns):
    answers = [client.post("/api/v1/alerts/subscribe", json=SIGNUP) for _ in range(8)]
    assert {a.status_code for a in answers} == {202} and len({a.text for a in answers}) == 1
    assert len(sns.calls) == alerts.MAX_SIGNUPS_PER_HOUR


def test_subscribe_uses_the_dynamodb_counter_when_configured(sns, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TABLE", "rate")
    sns.responses["update_item"] = {"Attributes": {"hits": {"N": "6"}}}
    assert client.post("/api/v1/alerts/subscribe", json=SIGNUP).status_code == 202
    assert sns.names() == ["update_item"]            # over the limit: counted, not subscribed
    key = sns.calls[0][1]["Key"]["id"]["S"]
    assert key.startswith("signup#") and "testclient" not in key   # the IP is stored hashed


# ── photo moderation ─────────────────────────────────────────
KEY = "report_photos/new_delhi/" + "a" * 32 + ".jpg"
EVENT = {"source": "aws.s3", "detail-type": "Object Created",
         "detail": {"bucket": {"name": "data"}, "object": {"key": KEY}}}
JPEG = {"ContentType": "image/jpeg", "ContentLength": 200_000}


def _moderate(monkeypatch, s3_responses, rek_responses, event=EVENT):
    s3, rek = Recorder(**s3_responses), Recorder(**rek_responses)
    monkeypatch.setattr(moderate, "s3", s3)
    monkeypatch.setattr(moderate, "rekognition", rek)
    return moderate.handler(event, None), s3, rek


def test_safe_photo_is_tagged_and_labels_stay_outside_the_trigger_prefix(monkeypatch):
    res, s3, rek = _moderate(monkeypatch, {"head_object": JPEG},
                             {"detect_moderation_labels": {"ModerationLabels": []},
                              "detect_labels": {"Labels": [{"Name": "Tree", "Confidence": 91.23}]}})
    assert res["results"][KEY] == "approved" and "delete_object" not in s3.names()
    tag = dict(s3.calls)["put_object_tagging"]["Tagging"]["TagSet"]
    assert tag == [{"Key": "moderation", "Value": "approved"}]
    sidecar = dict(s3.calls)["put_object"]["Key"]
    assert sidecar.startswith("report_labels/") and not sidecar.startswith("report_photos/")


def test_flagged_photo_is_deleted_and_never_tagged(monkeypatch):
    res, s3, _ = _moderate(monkeypatch, {"head_object": JPEG},
                           {"detect_moderation_labels": {"ModerationLabels": [{"Name": "Explicit"}]}})
    assert res["results"][KEY] == "deleted_flagged"
    assert "delete_object" in s3.names() and "put_object_tagging" not in s3.names()


def test_wrong_type_oversize_and_unreadable_files_are_deleted(monkeypatch):
    res, s3, rek = _moderate(monkeypatch, {"head_object": {"ContentType": "text/html", "ContentLength": 10}}, {})
    assert res["results"][KEY] == "deleted_invalid" and rek.calls == []
    res, s3, rek = _moderate(monkeypatch, {"head_object": {**JPEG, "ContentLength": 50_000_000}}, {})
    assert res["results"][KEY] == "deleted_invalid" and rek.calls == []
    bad = ClientError({"Error": {"Code": "InvalidImageFormatException"}}, "DetectModerationLabels")
    res, s3, _ = _moderate(monkeypatch, {"head_object": JPEG}, {"detect_moderation_labels": bad})
    assert res["results"][KEY] == "deleted_unreadable" and "put_object_tagging" not in s3.names()


def test_moderation_error_leaves_the_photo_untagged_and_retries(monkeypatch):
    throttled = ClientError({"Error": {"Code": "ThrottlingException"}}, "DetectModerationLabels")
    s3, rek = Recorder(head_object=JPEG), Recorder(detect_moderation_labels=throttled)
    monkeypatch.setattr(moderate, "s3", s3)
    monkeypatch.setattr(moderate, "rekognition", rek)
    with pytest.raises(ClientError):
        moderate.handler(EVENT, None)
    assert "put_object_tagging" not in s3.names() and "delete_object" not in s3.names()


def test_other_prefixes_and_empty_events_are_ignored(monkeypatch):
    other = {"detail": {"bucket": {"name": "data"}, "object": {"key": "briefs/x.jpg"}}}
    for event in (other, {}, {"Records": []}):
        res, s3, rek = _moderate(monkeypatch, {}, {}, event)
        assert res["results"] == {} and s3.calls == [] and rek.calls == []


# ── reports: only keys this API issued ───────────────────────
def test_report_keeps_only_a_photo_key_issued_for_that_city(fake_city):
    from api import store
    body = {"lat": 28.55, "lon": 77.06, "kind": "no_shade"}
    for key, kept in ((KEY, True), ("briefs/secret.pdf", False),
                      (KEY.replace("new_delhi", "mumbai"), False), (KEY + "/../x", False)):
        r = client.post(f"/api/v1/reports?city={fake_city}", json={**body, "photo_key": key})
        assert r.status_code == 200
        saved = [d for d in store.list_reports(fake_city) if d["id"] == r.json()["id"]][0]
        assert saved["photo_key"] == (key if kept else None)


# ── simulation never leaks into real data ────────────────────
def test_citizen_endpoint_flags_a_simulated_level(fake_city):
    r = client.get(f"/api/v1/citizen?city={fake_city}&lat=28.55&lon=77.06&simulate=red")
    assert r.status_code == 200 and r.json()["alert_level"] == "red" and r.json()["simulated"] is True
    r = client.get(f"/api/v1/citizen?city={fake_city}&lat=28.55&lon=77.06")
    assert r.json()["simulated"] is False


def test_refresh_simulation_keeps_the_real_risk_file_and_labels_the_alert(fake_city, monkeypatch):
    rec = Recorder(synthesize_speech={"AudioStream": type("S", (), {"read": lambda self: b"mp3"})()},
                   generate_presigned_url="https://example.invalid/audio")
    day = {"date": "2026-10-11", "tmax_c": 30.0, "heat_index_c": 30.0, "alert_level": "green"}
    monkeypatch.setattr(refresh, "get_forecast", lambda city, days: {"today": day, "days": [day]})
    monkeypatch.setattr(refresh.aws, "client", lambda service: rec)
    monkeypatch.setattr(refresh.aws, "DATA_BUCKET", "data")
    monkeypatch.setattr(refresh, "TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:alerts")

    out = refresh.handler({"simulate": "red", "cities": [fake_city]})["results"][0]
    assert out["alert_sent"] and out["simulated"] and out["alert_level"] == "red"
    puts = {kw["Key"]: kw for name, kw in rec.calls if name == "put_object"}
    assert json.loads(puts[f"risk_today/{fake_city}.json"]["Body"])["alert_level"] == "green"
    assert f"advisories/{fake_city}/simulated-2026-10-11.mp3" in puts
    publish = dict(rec.calls)["publish"]
    assert publish["Subject"].startswith("[SIMULATION]") and "SIMULATION" in publish["Message"]
    assert publish["MessageAttributes"]["level_num"]["StringValue"] == "3"

    with pytest.raises(ValueError):
        refresh.handler({"simulate": "purple", "cities": [fake_city]})


# ── knowledge base (Bedrock Retrieve) ────────────────────────
def _kb(monkeypatch, results=None, error=None):
    from agent import heat_officer
    from api import aws
    rec = Recorder(retrieve=error or {"retrievalResults": results or []})
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "KB123")
    monkeypatch.setattr(aws, "client", lambda service: rec)
    return heat_officer, rec


def _hit(text, score, uri="s3://data/kb-docs/ndma_guidelines.pdf"):
    return {"content": {"text": text}, "score": score, "location": {"s3Location": {"uri": uri}}}


def test_guidance_uses_knowledge_base_hits_with_source_labels(monkeypatch):
    ho, rec = _kb(monkeypatch, [_hit("Open cooling centres from 12 to 4 pm.", 0.71),
                                _hit("Unrelated passage.", 0.05)])
    sources = []
    text = ho.tool_search_guidance("cooling spaces", sources)
    assert rec.calls[0][1]["knowledgeBaseId"] == "KB123"
    assert "[S1] Open cooling centres" in text and "(source: ndma_guidelines.pdf)" in text
    assert "Unrelated" not in text                      # below KB_MIN_SCORE
    assert sources == ["ndma_guidelines.pdf"]


def test_guidance_falls_back_to_the_local_file(monkeypatch):
    from agent import heat_officer
    monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)
    local = heat_officer.tool_search_guidance("hydration")
    assert "Drink water" in local
    for results, error in (([], None), ([_hit("weak", 0.01)], None), (None, RuntimeError("AccessDenied"))):
        ho, _ = _kb(monkeypatch, results, error)
        sources = []
        assert ho.tool_search_guidance("hydration", sources) == local and sources == []


# ── map area names ───────────────────────────────────────────
def test_nearest_place_names_and_distance_cap():
    import numpy as np
    from pipeline.real.areas import nearest_names
    places = [{"name": "Bani Park", "lat": 26.93, "lon": 75.79}, {"name": "Amber", "lat": 26.99, "lon": 75.85}]
    lon, lat = np.array([75.791, 75.849, 76.40]), np.array([26.931, 26.989, 27.40])
    assert nearest_names(lon, lat, places) == ["Bani Park", "Amber", None]   # last point is ~70 km away
    assert nearest_names(lon, lat, []) == [None, None, None]


def test_grid_payload_carries_area_names(fake_city):
    import pipeline.config as cfg
    from api import data_source
    df = data_source.read_features(fake_city)
    cfg.city_grid_file(fake_city).write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"grid_id": g}, "geometry": {"type": "Polygon", "coordinates": [[
            [x, y], [x + .005, y], [x + .005, y + .0045], [x, y + .0045], [x, y]]]}}
        for g, x, y in zip(df["grid_id"][:6], df["centroid_lon"][:6], df["centroid_lat"][:6])]}))
    data_source._real_grid.cache_clear()
    grid = client.get(f"/api/v1/grid?city={fake_city}").json()["features"]
    assert len(grid) == 6 and "area_name" not in grid[0]["properties"]   # no file yet: nothing invented
    gid = grid[0]["properties"]["grid_id"]
    cfg.city_area_names_file(fake_city).write_text(json.dumps({"names": ["Test Nagar"], "cells": {gid: 0}}))
    data_source._real_grid.cache_clear()
    props = {f["properties"]["grid_id"]: f["properties"] for f in
             client.get(f"/api/v1/grid?city={fake_city}").json()["features"]}
    assert props[gid]["area_name"] == "Test Nagar"
    assert {"lst_mean", "tier", "delta_above_mean", "ward_name"} <= set(props[gid])   # existing metrics kept
    assert sum("area_name" in p for p in props.values()) == 1


# ── pipeline: one code path for both STAC catalogues ─────────
def test_stac_assets_offsets_and_tiles_for_both_catalogues():
    pytest.importorskip("rasterio")
    from types import SimpleNamespace as NS
    from pipeline.real import stac
    pc = NS(id="pc", properties={"s2:processing_baseline": "05.11"},
            assets={"B04": NS(href="https://pc/B04.tif"), "lwir11": NS(href="https://pc/ST_B10.TIF")})
    es = NS(id="es", properties={"s2:processing_baseline": "05.11", "earthsearch:boa_offset_applied": True},
            assets={"red": NS(href="https://sentinel-cogs.s3.us-west-2.amazonaws.com/x/B04.tif"),
                    "lwir11": NS(href="s3://usgs-landsat/collection02/x_ST_B10.TIF"),
                    "data": NS(href="s3://copernicus-dem-30m/t/t.tif")})
    assert stac.asset_href(pc, "B04") == "https://pc/B04.tif"
    assert stac.asset_href(es, "B04").endswith("/x/B04.tif")
    assert stac.asset_href(es, "lwir11").startswith("s3://usgs-landsat/")          # requester pays: stays s3://
    assert stac.asset_href(es, "data") == "https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/t/t.tif"
    with pytest.raises(KeyError):
        stac.asset_href(es, "B12")
    assert stac.sentinel2_boa_offset(pc) == 1000.0 and stac.sentinel2_boa_offset(es) == 0.0
    assert stac.sentinel2_boa_offset(NS(properties={"s2:processing_baseline": "03.01"})) == 0.0
    tiles = stac.worldcover_tile_urls((75.65, 26.75, 75.95, 27.05))
    assert [t.split("_")[-2] for t in tiles] == ["N24E075", "N27E075"]
    assert [t.split("_")[-2] for t in stac.worldcover_tile_urls((72.77, 18.89, 72.98, 19.27))] == ["N18E072"]
    assert len(stac.worldcover_tile_urls((75.0, 24.0, 78.0, 27.0))) == 1          # edges on tile boundaries


def test_brief_reports_knowledge_base_sources(fake_city, monkeypatch):
    import agent.heat_officer as ho
    from models.risk import ward_table
    ward = ward_table(fake_city).iloc[0]["ward_id"]
    facts = ho.gather_facts(fake_city, ward, 3000.0, 0.5, forecast={"unavailable": True})
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")

    def fake(c, w, b, e, log, extra=""):
        log.append(facts["ward"])
        log.append({ho.GUIDANCE_LOG_KEY: "[S1] Keep centres open 12 to 4 pm. (source: hap.pdf)", "sources": ["hap.pdf"]})
        return {"en": "Keep cooling centres open 12 to 4 pm [S1].", "hi": "कूलिंग सेंटर 12 से 4 बजे तक खुले रखें [S1]।"}
    monkeypatch.setattr(ho, "_run_llm", fake)
    out = ho.generate_brief(fake_city, ward, 3000.0, 0.5, use_llm=True, facts=facts)
    assert out["source"] == "bedrock" and out["sources"] == ["hap.pdf"]

    # guidance alone does not count as calling the data tools
    monkeypatch.setattr(ho, "_run_llm", lambda c, w, b, e, log, extra="": (
        log.append({ho.GUIDANCE_LOG_KEY: "x", "sources": ["hap.pdf"]}) or {"en": "Stay cool.", "hi": "ठंडे रहें।"}))
    out = ho.generate_brief(fake_city, ward, 3000.0, 0.5, use_llm=True, facts=facts)
    assert out["source"] == "template" and out["sources"] == []

    from agent.brief_pdf import build_pdf
    assert build_pdf({**out, "sources": ["hap.pdf"]})[:4] == b"%PDF"
