"""
Nightly ward briefs (Amazon Bedrock batch inference) — see agent/batch_briefs.py.

Two triggers, one function:
  * EventBridge Scheduler (00:30 IST)                      -> submit a batch job for every real city
  * EventBridge "Batch Inference Job State Change" (bedrock) -> collect when the job has finished
Metrics go out as CloudWatch Embedded Metric Format log lines (namespace HeatRelief).
"""

from __future__ import annotations

import json
import time

from agent import batch_briefs

DONE = ("Completed", "PartiallyCompleted")


def emf(**metrics):
    print(json.dumps({"_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
        "Namespace": "HeatRelief", "Dimensions": [[]],
        "Metrics": [{"Name": k, "Unit": "Count"} for k in metrics]}]}, **metrics}))


def handler(event=None, context=None):
    event = event or {}
    if event.get("source") == "aws.bedrock" and event.get("detail-type") == "Batch Inference Job State Change":
        detail = event.get("detail", {})
        run_id = batch_briefs.run_id_from_job_name(detail.get("batchJobName", ""))
        status = detail.get("status")
        if not run_id:
            return {"ignored": "not a HeatRelief brief job"}
        if status not in DONE:
            if status in ("Failed", "Stopped", "Expired"):
                emf(BatchBriefJobsFailed=1)
                print(f"brief batch {run_id} ended {status}: {detail.get('failureMessage', '')}")
            return {"run_id": run_id, "status": status}
        out = batch_briefs.collect(run_id)
        emf(BatchBriefsAccepted=out["accepted"], BatchBriefsTemplate=out["template"],
            BatchBriefsErrors=out["errors"])
        return out
    out = batch_briefs.submit(cities=event.get("cities"))
    emf(BatchBriefJobsSubmitted=int(out.get("submitted", False)))
    print(json.dumps(out))
    return out
