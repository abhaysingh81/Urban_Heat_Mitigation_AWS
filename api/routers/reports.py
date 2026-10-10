"""Anonymous citizen/officer ground-truth reports ("no shade here")."""

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api import aws, store
from api.routers.risk import require_real
from api.data_source import read_features
from pipeline.real.gridspec import GridSpec

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
KINDS = ("no_shade", "no_water", "very_hot", "cool_spot")


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
    doc = store.save_report(city_id, cell_for(city_id, body.lat, body.lon), body.kind, body.note, body.photo_key)
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
    return {"city_id": city_id, "total_reports": len(reps),
            "hot_spots_reported": [{"grid_id": g, "reports": n} for g, n in problem.most_common(20)]}
