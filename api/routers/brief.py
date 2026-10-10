"""Heat Officer brief generation + PDF."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api import aws
from api.routers.risk import require_real
from models.risk import ward_table

router = APIRouter(prefix="/api/v1/brief", tags=["brief"])


class BriefBody(BaseModel):
    ward_id: str
    budget_lakh: float = Field(5000.0, gt=0, le=1_000_000)
    equity_weight: float = Field(0.5, ge=0, le=1)
    use_llm: bool = True
    make_pdf: bool = True


def _pdf_dir():
    d = aws.RUNTIME_DIR / "briefs"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("")
async def create_brief(body: BriefBody, city_id: str = Depends(require_real)):
    from agent.heat_officer import generate_brief
    if body.ward_id not in set(ward_table(city_id)["ward_id"]):
        raise HTTPException(404, f"Unknown ward '{body.ward_id}'")
    try:
        brief = generate_brief(city_id, body.ward_id, body.budget_lakh, body.equity_weight, body.use_llm)
    except ValueError as e:
        raise HTTPException(400, str(e))

    brief["cached"] = False
    if body.make_pdf:
        try:
            from agent.brief_pdf import build_pdf
            pdf = build_pdf(brief)
            name = f"{city_id}_{body.ward_id}_{uuid.uuid4().hex[:8]}.pdf"
            if aws.DATA_BUCKET:
                key = f"briefs/{name}"
                aws.client("s3").put_object(Bucket=aws.DATA_BUCKET, Key=key, Body=pdf,
                                            ContentType="application/pdf")
                brief["pdf_url"] = aws.presign_get(key)
            else:
                (_pdf_dir() / name).write_bytes(pdf)
                brief["pdf_url"] = f"/api/v1/brief/pdf/{name}"
        except Exception as e:  # a PDF problem must not lose the brief itself
            brief["pdf_error"] = f"{type(e).__name__}: {e}"
    return brief


@router.get("/pdf/{name}")
async def get_pdf(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(400, "bad name")
    f = _pdf_dir() / name
    if not f.exists():
        raise HTTPException(404, "not found")
    return FileResponse(f, media_type="application/pdf")
