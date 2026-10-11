"""Nightly ward briefs with Amazon Bedrock batch inference (agent/batch_briefs.py)."""

import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from agent import batch_briefs as bb
from api import aws
from api.main import app
from lambdas.brief_batch import app as lam

client = TestClient(app)


@pytest.fixture()
def city(fake_city, monkeypatch):
    monkeypatch.setattr(bb, "tool_forecast", lambda c: {"today_max_temp_c": 44.2, "today_heat_index_c": 47.1,
                                                         "today_alert_level": "orange"})
    monkeypatch.setattr("agent.heat_officer.tool_forecast", lambda c: {"unavailable": True})
    monkeypatch.setattr(bb, "MIN_RECORDS", 5)          # the fake city has 36 wards, not 100+
    return fake_city


def _converse(text):
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": "end_turn"}


def test_records_use_the_converse_format_and_carry_the_facts(city):
    facts = bb.city_facts(city)
    ward_id, f = next(iter(facts.items()))
    rec = bb.record(city, ward_id, f)
    assert rec["recordId"] == f"{city}|{ward_id}"
    mi = rec["modelInput"]
    assert set(mi) == {"system", "messages", "inferenceConfig"} and mi["messages"][0]["role"] == "user"
    assert str(f["ward"]["risk_score"]) in mi["messages"][0]["content"][0]["text"]
    assert f["forecast"]["today_max_temp_c"] == 44.2


def test_too_few_records_is_not_submitted(city, monkeypatch):
    monkeypatch.setattr(bb, "MIN_RECORDS", 100)
    out = bb.submit([city], run_id="r0")
    assert out["submitted"] is False and "records" in out["reason"]


def test_full_cycle_submit_collect_and_serve(city):
    out = bb.submit([city], run_id="20261011-003000")
    assert out["submitted"] and out["records"] > 5
    facts = json.loads(bb._get("batch/briefs/20261011-003000/facts.json"))[city]
    wards = list(facts)
    good, bad, err = wards[0], wards[1], wards[2]
    w = facts[good]["ward"]
    good_text = json.dumps({"en": f"{w['ward_name']} ranks {w['rank']} of {w['of_wards']}.",
                            "hi": f"{w['ward_name']} {w['of_wards']} में से {w['rank']} नंबर पर है।"})
    lines = [
        {"recordId": f"{city}|{good}", "modelInput": {}, "modelOutput": _converse("Here:\n" + good_text)},
        {"recordId": f"{city}|{bad}", "modelInput": {},
         "modelOutput": _converse(json.dumps({"en": "Plant 987654 trees.", "hi": "987654 पेड़।"}))},
        {"recordId": f"{city}|{err}", "modelInput": {}, "error": {"errorCode": 400, "errorMessage": "bad request"}},
    ]
    bb._put("batch/briefs/20261011-003000/output/job123/records.jsonl.out",
            ("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n").encode())
    bb._put("batch/briefs/20261011-003000/output/job123/manifest.json.out", b'{"totalRecordCount": 3}')

    res = lam.handler({"source": "aws.bedrock", "detail-type": "Batch Inference Job State Change",
                       "detail": {"batchJobName": "heatrelief-briefs-20261011-003000", "status": "Completed"}})
    assert res == {"run_id": "20261011-003000", "accepted": 1, "template": 2, "errors": 0}

    g = bb.cached_brief(city, good, 5000.0, 0.5)
    assert g["source"] == "bedrock-batch" and w["ward_name"] in g["brief_en"]
    b = bb.cached_brief(city, bad, 5000.0, 0.5)
    assert b["source"] == "template" and "987654" in b["note"] and "987654" not in b["brief_en"]
    assert "bad request" in bb.cached_brief(city, err, 5000.0, 0.5)["note"]
    assert bb.cached_brief(city, good, 9000.0, 0.5) is None              # other budgets are not cached

    r = client.post("/api/v1/brief?city=new_delhi", json={"ward_id": good, "make_pdf": False})
    assert r.status_code == 200 and r.json()["cached"] is True and r.json()["source"] == "bedrock-batch"
    r2 = client.post("/api/v1/brief?city=new_delhi", json={"ward_id": good, "make_pdf": False, "fresh": True})
    assert r2.json()["cached"] is False


def test_stale_cache_is_ignored(city):
    old = (datetime.now(timezone.utc) - timedelta(hours=bb.CACHE_MAX_AGE_H + 1)).isoformat()
    bb._put(bb.cache_key(city, "Z0000"), json.dumps({"generated_at": old, "brief_en": "x"}).encode())
    assert bb.cached_brief(city, "Z0000", 5000.0, 0.5) is None


def test_other_job_events_are_ignored_or_logged():
    assert "ignored" in lam.handler({"source": "aws.bedrock", "detail-type": "Batch Inference Job State Change",
                                     "detail": {"batchJobName": "someone-else", "status": "Completed"}})
    assert lam.handler({"source": "aws.bedrock", "detail-type": "Batch Inference Job State Change",
                        "detail": {"batchJobName": "heatrelief-briefs-x", "status": "InProgress"}})["status"] == "InProgress"


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}


class FakeBedrock:
    def __init__(self):
        self.calls = []

    def create_model_invocation_job(self, **kw):
        self.calls.append(kw)
        return {"jobArn": "arn:aws:bedrock:us-east-1:111122223333:model-invocation-job/abc"}


def test_submit_on_aws_starts_a_converse_batch_job(city, monkeypatch):
    s3, br = FakeS3(), FakeBedrock()
    monkeypatch.setattr(aws, "DATA_BUCKET", "data-bkt")
    monkeypatch.setattr(aws, "client", lambda svc: {"s3": s3, "bedrock": br}[svc])
    monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-test")
    monkeypatch.setenv("BATCH_ROLE_ARN", "arn:aws:iam::111122223333:role/batch")
    out = bb.submit([city], run_id="20261011-003000")
    call = br.calls[0]
    assert out["job_arn"].endswith("/abc") and call["modelInvocationType"] == "Converse"
    assert call["jobName"] == "heatrelief-briefs-20261011-003000" and 24 <= call["timeoutDurationInHours"] <= 168
    assert call["inputDataConfig"]["s3InputDataConfig"]["s3Uri"] == \
        "s3://data-bkt/batch/briefs/20261011-003000/input/records.jsonl"
    assert call["outputDataConfig"]["s3OutputDataConfig"]["s3Uri"] == "s3://data-bkt/batch/briefs/20261011-003000/output/"
    lines = s3.objects["batch/briefs/20261011-003000/input/records.jsonl"].decode().strip().splitlines()
    assert len(lines) == out["records"] and all("recordId" in json.loads(l) for l in lines)


def test_submit_on_aws_needs_model_and_role(city, monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(aws, "DATA_BUCKET", "data-bkt")
    monkeypatch.setattr(aws, "client", lambda svc: s3)
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.delenv("BATCH_ROLE_ARN", raising=False)
    assert bb.submit([city], run_id="r1")["submitted"] is False
