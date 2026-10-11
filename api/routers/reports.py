"""Anonymous citizen/officer ground-truth reports ("no shade here")."""

import re
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api import auth, aws, live, store
from api.routers.risk import require_real
from api.data_source import read_features
from pipeline.real.gridspec import GridSpec

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
KINDS = ("no_shade", "no_water", "very_hot", "cool_spot")
PHOTO_KEY = re.compile(r"report_photos/([a-z_]+)/[0-9a-f]{32}\.jpg")  # the shape upload_url hands out


class ReportBody(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    kind: str
    note: str = ""
    photo_key: str | None = None


def cell_for(city_id: str, lat: float, lon: float) -> str:
    """Round a location to its 500 m grid cell id (privacy: no exact coordinates kept)."""
    spec = GridSpec.for_city(city_id)
    r, c, ok = spec.lonlat_to_cell_rc([lon], [lat])
    if not ok[0]:
        raise HTTPException(400, "Location is outside this city's analysis area")
    row = spec.rows - 1 - int(r[0])
    return f"cell_{int(c[0]) * spec.rows + row:04d}"


@router.post("")
async def create_report(body: ReportBody, city_id: str = Depends(require_real)):
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {KINDS}")
    # only accept a key this API issued for this city, never an arbitrary object in the bucket
    m = PHOTO_KEY.fullmatch(body.photo_key or "")
    photo_key = body.photo_key if m and m.group(1) == city_id else None
    doc = store.save_report(city_id, cell_for(city_id, body.lat, body.lon), body.kind, body.note, photo_key)
    live.broadcast(live.report_event("report.created", doc))   # officer screens update without a refresh
    return {"id": doc["id"], "grid_id": doc["grid_id"], "kind": doc["kind"]}


@router.post("/upload-url")
async def upload_url(city_id: str = Depends(require_real)):
    """Presigned S3 PUT for an optional photo. Only available when deployed on AWS."""
    if not aws.DATA_BUCKET:
        raise HTTPException(501, "Photo upload needs the AWS deployment (DATA_BUCKET)")
    import uuid
    key = f"report_photos/{city_id}/{uuid.uuid4().hex}.jpg"
    url = aws.client("s3").generate_presigned_url(
        "put_object", Params={"Bucket": aws.DATA_BUCKET, "Key": key, "ContentType": "image/jpeg"},
        ExpiresIn=600)
    return {"upload_url": url, "photo_key": key}


@router.get("/summary")
async def summary(city_id: str = Depends(require_real)):
    """Reported cells, most-reported first — candidate sites for the optimizer."""
    reps = store.list_reports(city_id)
    problem = Counter(r["grid_id"] for r in reps if r["kind"] != "cool_spot")
    
    # Expose up to 10 recent approved photos
    photos = []
    if aws.DATA_BUCKET:
        s3 = aws.client("s3")
        for r in sorted([x for x in reps if x.get("photo_key")], key=lambda x: x["created_at"], reverse=True):
            if not PHOTO_KEY.fullmatch(r["photo_key"]):
                continue
            try:
                tags = s3.get_object_tagging(Bucket=aws.DATA_BUCKET, Key=r["photo_key"])
                tag_dict = {t["Key"]: t["Value"] for t in tags.get("TagSet", [])}
                if tag_dict.get("moderation") == "approved":
                    url = s3.generate_presigned_url(
                        "get_object", Params={"Bucket": aws.DATA_BUCKET, "Key": r["photo_key"]}, ExpiresIn=3600)
                    photos.append({"id": r["id"], "kind": r["kind"], "photo_url": url, "created_at": r["created_at"]})
                    if len(photos) >= 10: break
            except Exception:
                pass
                
    return {"city_id": city_id, "total_reports": len(reps),
            "hot_spots_reported": [{"grid_id": g, "reports": n} for g, n in problem.most_common(20)],
            "recent_photos": photos}


class ReportStatusBody(BaseModel):
    status: str
    note: str = ""


def _officer_view(r: dict) -> dict:
    return {"id": r["id"], "city_id": r["city_id"], "grid_id": r["grid_id"], "kind": r["kind"],
            "note": r.get("note", ""), "status": r.get("status", "new"), "created_at": r["created_at"],
            "has_photo": bool(r.get("photo_key")), "audit": r.get("audit", [])}


@router.get("")
async def list_reports(city_id: str = Depends(require_real),
                       user: dict = Depends(auth.require_role(auth.WARD_OFFICER, auth.CITY_PLANNER))):
    """Officer view: every report for the city, newest first, with its verification status."""
    reps = sorted(store.list_reports(city_id), key=lambda r: r["created_at"], reverse=True)[:200]
    return {"city_id": city_id, "statuses": store.REPORT_STATUSES, "reports": [_officer_view(r) for r in reps]}


@router.put("/{report_id}/status")
async def set_report_status(report_id: str, body: ReportStatusBody,
                            user: dict = Depends(auth.require_role(auth.WARD_OFFICER, auth.CITY_PLANNER))):
    """Field verification: mark a report verified, dispatched (e.g. a water tanker sent), resolved or rejected."""
    try:
        doc = store.set_report_status(report_id, body.status, actor=user["name"], note=body.note)
    except KeyError:
        raise HTTPException(404, "report not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    live.broadcast(live.report_event("report.updated", doc))
    return _officer_view(doc)
