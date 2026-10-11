"""
Nightly ward briefs with Amazon Bedrock batch inference.

Every night (EventBridge Scheduler, 00:30 IST) one batch job writes the English + Hindi brief for
every ward of every real-data city, so an officer's "Write ward brief" returns at once instead of
waiting on a live model call (and can never hit the ~30 s API Gateway limit). Batch inference is
billed below on-demand inference.

  submit   facts for every ward (one optimiser run per city, not per ward) -> one Converse-format
           JSONL record per ward -> s3://<data bucket>/batch/briefs/<run>/input/records.jsonl
           -> CreateModelInvocationJob (modelInvocationType="Converse", so the record format does not
           depend on the model family)
  collect  EventBridge "Batch Inference Job State Change" (Completed / PartiallyCompleted) ->
           read every *.out file under the run's output prefix -> each draft goes through the same
           number check as live briefs -> accepted drafts are cached; a draft that fails the check
           is replaced by the deterministic template brief -> briefs_cache/<city>/<ward>.json

The API serves a cached brief only for the default budget and equity weight, and only while it is
fresh (CACHE_MAX_AGE_H). Without a data bucket everything runs against RUNTIME_DIR, which is how
the tests exercise the whole cycle.

API facts (Bedrock user guide, batch inference): records are {"recordId", "modelInput"} lines in a
.jsonl file; 100 to 100,000 records per job; timeout 24 to 168 hours; output lines carry
recordId + modelOutput or error; the job-state event has detail.batchJobName / status.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from agent.heat_officer import (
    GUIDANCE, SYSTEM_PROMPT, summarise_ward_plan, template_brief, tool_cooling_spots, tool_forecast,
    tool_ward_risk,
)
from agent.numbers_check import collect_allowed, find_unsupported
from api import aws
from models.optimizer import PlanRequest, optimize
from models.risk import ward_table
from pipeline.config import CITIES, REAL_CITIES

DEFAULT_BUDGET_LAKH = 5000.0          # same defaults as the /api/v1/brief request body
DEFAULT_EQUITY = 0.5
MIN_RECORDS, MAX_RECORDS = 100, 100_000
CACHE_MAX_AGE_H = 36
JOB_PREFIX = "heatrelief-briefs-"
PREFIX = "batch/briefs"

BATCH_RULES = SYSTEM_PROMPT + """
In this request there are no tools to call: the FACTS block below holds every tool result for this
ward. Use only numbers that appear in FACTS."""


# ── storage: S3 data bucket on AWS, RUNTIME_DIR locally ──────
def _put(key: str, body: bytes, content_type: str = "application/json") -> None:
    if aws.DATA_BUCKET:
        aws.client("s3").put_object(Bucket=aws.DATA_BUCKET, Key=key, Body=body, ContentType=content_type)
    else:
        f = aws.RUNTIME_DIR / key
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(body)


def _get(key: str) -> bytes | None:
    try:
        if aws.DATA_BUCKET:
            return aws.client("s3").get_object(Bucket=aws.DATA_BUCKET, Key=key)["Body"].read()
        f = aws.RUNTIME_DIR / key
        return f.read_bytes() if f.exists() else None
    except Exception:
        return None


def _list(prefix: str) -> list[str]:
    if aws.DATA_BUCKET:
        keys, kwargs = [], {"Bucket": aws.DATA_BUCKET, "Prefix": prefix}
        while True:
            page = aws.client("s3").list_objects_v2(**kwargs)
            keys += [o["Key"] for o in page.get("Contents", [])]
            if not page.get("IsTruncated"):
                return keys
            kwargs["ContinuationToken"] = page["NextContinuationToken"]
    root = aws.RUNTIME_DIR
    return sorted(str(p.relative_to(root)) for p in (root / prefix).rglob("*") if p.is_file()) \
        if (root / prefix).exists() else []


def cache_key(city_id: str, ward_id: str) -> str:
    return f"briefs_cache/{city_id}/{ward_id}.json"


# ── facts + records ──────────────────────────────────────────
def city_facts(city_id: str, budget_lakh: float = DEFAULT_BUDGET_LAKH, equity: float = DEFAULT_EQUITY,
               forecast: dict | None = None) -> dict[str, dict]:
    """{ward_id: facts} with the same shape as heat_officer.gather_facts, one optimiser run per city."""
    plan = optimize(PlanRequest(city_id=city_id, budget_lakh=budget_lakh, equity_weight=equity))
    if forecast is None:
        try:
            forecast = tool_forecast(city_id)
        except Exception:
            forecast = {"unavailable": True}
    out = {}
    for ward_id in ward_table(city_id)["ward_id"]:
        out[ward_id] = {"city": CITIES[city_id]["name"], "ward": tool_ward_risk(city_id, ward_id),
                        "plan": summarise_ward_plan(plan, ward_id, budget_lakh),
                        "cooling": tool_cooling_spots(city_id, ward_id), "forecast": forecast}
    return out


def record(city_id: str, ward_id: str, facts: dict, max_tokens: int = 1500) -> dict:
    """One JSONL line in the Converse request format."""
    text = ("FACTS (tool results for this ward, JSON):\n" + json.dumps(facts, ensure_ascii=False)
            + "\n\nWrite the heat action brief for this ward now. Output only the JSON object.")
    return {"recordId": f"{city_id}|{ward_id}",
            "modelInput": {"system": [{"text": BATCH_RULES}],
                           "messages": [{"role": "user", "content": [{"text": text}]}],
                           "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.2}}}


def submit(cities: list[str] | None = None, run_id: str | None = None, facts_by_city: dict | None = None) -> dict:
    """Write the records and start the batch job. Needs BEDROCK_MODEL_ID and BATCH_ROLE_ARN on AWS."""
    cities = cities or list(REAL_CITIES)
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")   # also valid in a job name
    lines, facts_all = [], {}
    for c in cities:
        facts = (facts_by_city or {}).get(c) or city_facts(c)
        facts_all[c] = facts
        lines += [json.dumps(record(c, w, f), ensure_ascii=False) for w, f in facts.items()]
    if not MIN_RECORDS <= len(lines) <= MAX_RECORDS:
        return {"submitted": False, "reason": f"{len(lines)} records; a batch job needs {MIN_RECORDS}–{MAX_RECORDS}"}
    base = f"{PREFIX}/{run_id}"
    _put(f"{base}/input/records.jsonl", ("\n".join(lines) + "\n").encode())
    _put(f"{base}/facts.json", json.dumps(facts_all, ensure_ascii=False).encode())
    out = {"submitted": True, "run_id": run_id, "records": len(lines), "job_arn": None}
    if aws.DATA_BUCKET:
        model, role = os.environ.get("BEDROCK_MODEL_ID"), os.environ.get("BATCH_ROLE_ARN")
        if not model or not role:
            return {**out, "submitted": False, "reason": "BEDROCK_MODEL_ID and BATCH_ROLE_ARN are required"}
        resp = aws.client("bedrock").create_model_invocation_job(
            jobName=f"{JOB_PREFIX}{run_id}", roleArn=role, modelId=model,
            modelInvocationType="Converse", timeoutDurationInHours=24,
            inputDataConfig={"s3InputDataConfig": {"s3Uri": f"s3://{aws.DATA_BUCKET}/{base}/input/records.jsonl",
                                                   "s3InputFormat": "JSONL"}},
            outputDataConfig={"s3OutputDataConfig": {"s3Uri": f"s3://{aws.DATA_BUCKET}/{base}/output/"}})
        out["job_arn"] = resp["jobArn"]
    _put(f"{PREFIX}/latest.json", json.dumps({**out, "submitted_at": datetime.now(timezone.utc).isoformat()}).encode())
    return out


# ── collect ──────────────────────────────────────────────────
def _draft_text(model_output: dict) -> str:
    """Text of a Converse response: output.message.content[*].text."""
    parts = (((model_output or {}).get("output") or {}).get("message") or {}).get("content") or []
    return "".join(p.get("text", "") for p in parts)


def _parse_draft(text: str) -> dict | None:
    import re
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) and isinstance(d.get("en"), str) and isinstance(d.get("hi"), str) else None


def collect(run_id: str) -> dict:
    """Verify every output record of a finished run and write the brief cache."""
    base = f"{PREFIX}/{run_id}"
    facts_all = json.loads(_get(f"{base}/facts.json") or b"{}")
    counts = {"accepted": 0, "template": 0, "errors": 0}
    now = datetime.now(timezone.utc).isoformat()
    for key in _list(f"{base}/output/"):
        if not key.endswith(".out") or key.endswith("manifest.json.out"):
            continue
        for line in (_get(key) or b"").decode().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            city_id, _, ward_id = rec.get("recordId", "").partition("|")
            facts = facts_all.get(city_id, {}).get(ward_id)
            if not facts:
                counts["errors"] += 1
                continue
            draft = None if rec.get("error") else _parse_draft(_draft_text(rec.get("modelOutput")))
            bad = find_unsupported(draft["en"] + "\n" + draft["hi"], collect_allowed(facts, GUIDANCE)) if draft else None
            if draft and not bad:
                brief, source, note = draft, "bedrock-batch", None
                counts["accepted"] += 1
            else:
                brief, source = template_brief(facts), "template"
                note = (f"batch draft used numbers not in the facts: {bad}" if draft
                        else f"batch record failed: {(rec.get('error') or {}).get('errorMessage', 'no usable JSON')}")
                counts["template"] += 1
            _put(cache_key(city_id, ward_id), json.dumps({
                "city_id": city_id, "ward_id": ward_id, "source": source, "note": note,
                "brief_en": brief["en"], "brief_hi": brief["hi"], "sources": [], "numbers_verified": True,
                "facts": facts, "budget_lakh": DEFAULT_BUDGET_LAKH, "equity_weight": DEFAULT_EQUITY,
                "generated_at": now, "run_id": run_id}, ensure_ascii=False).encode())
    return {"run_id": run_id, **counts}


def run_id_from_job_name(job_name: str) -> str | None:
    return job_name[len(JOB_PREFIX):] if job_name.startswith(JOB_PREFIX) else None


# ── read path for the API ────────────────────────────────────
def cached_brief(city_id: str, ward_id: str, budget_lakh: float, equity_weight: float,
                 max_age_h: float = CACHE_MAX_AGE_H) -> dict | None:
    if abs(budget_lakh - DEFAULT_BUDGET_LAKH) > 1e-6 or abs(equity_weight - DEFAULT_EQUITY) > 1e-6:
        return None
    raw = _get(cache_key(city_id, ward_id))
    if not raw:
        return None
    doc = json.loads(raw)
    age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(doc["generated_at"])).total_seconds() / 3600
    return doc if age_h <= max_age_h else None
