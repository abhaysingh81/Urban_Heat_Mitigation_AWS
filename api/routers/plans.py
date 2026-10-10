"""Budget + equity optimizer and saved-plan lifecycle."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api import store
from api.routers.risk import require_real
from models.optimizer import COOLING_TYPES, PlanRequest, compare_equity, optimize

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])


class OptimizeBody(BaseModel):
    budget_lakh: float = Field(..., gt=0, le=1_000_000, description="Budget in INR lakh (100 lakh = 1 crore)")
    interventions: list[str] = Field(default_factory=lambda: list(COOLING_TYPES))
    equity_weight: float = Field(0.0, ge=0, le=1)
    tree_survival: float = Field(0.7, gt=0, le=1)
    include_centres: bool = True
    compare: bool = False
    save: bool = False


class StatusBody(BaseModel):
    status: str
    actor: str = "officer"
    note: str = ""


@router.post("/optimize")
async def optimize_plan(body: OptimizeBody, city_id: str = Depends(require_real)):
    bad = [i for i in body.interventions if i not in COOLING_TYPES]
    if bad:
        raise HTTPException(400, f"Unknown interventions {bad}. Valid: {COOLING_TYPES}")
    req = PlanRequest(city_id=city_id, budget_lakh=body.budget_lakh, interventions=body.interventions,
                      equity_weight=body.equity_weight, tree_survival=body.tree_survival,
                      include_centres=body.include_centres)
    try:
        plan = optimize(req)
        if body.compare:
            plan["equity_comparison"] = compare_equity(req)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.save:
        doc = store.save_plan(city_id, plan)
        plan["plan_id"], plan["status"] = doc["id"], doc["status"]
    return plan


@router.get("/{plan_id}")
async def get_plan(plan_id: str):
    doc = store.get_plan(plan_id)
    if not doc:
        raise HTTPException(404, "plan not found")
    return doc


@router.get("/{plan_id}/export")
async def export_plan(plan_id: str, format: str = "csv"):
    """Saved plan as CSV or GeoJSON (points) for sharing and GIS."""
    import csv, io, json
    from fastapi.responses import Response
    doc = store.get_plan(plan_id)
    if not doc:
        raise HTTPException(404, "plan not found")
    items = doc["plan"]["items"]
    if format == "geojson":
        gj = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [i["lon"], i["lat"]]},
             "properties": {k: v for k, v in i.items() if k not in ("lat", "lon", "cooling_c")}
                           | {"cooling_low_c": i["cooling_c"]["low"], "cooling_mid_c": i["cooling_c"]["mid"],
                              "cooling_high_c": i["cooling_c"]["high"], "plan_status": doc["status"]}}
            for i in items]}
        return Response(json.dumps(gj), media_type="application/geo+json",
                        headers={"Content-Disposition": f'attachment; filename="plan_{plan_id}.geojson"'})
    if format != "csv":
        raise HTTPException(400, "format must be csv or geojson")
    buf = io.StringIO()
    cols = ["grid_id", "ward_id", "ward_name", "lat", "lon", "intervention", "label", "cost_lakh", "people",
            "cooling_low_c", "cooling_mid_c", "cooling_high_c", "vulnerability"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for i in items:
        w.writerow({**{k: i[k] for k in cols if k in i},
                    "cooling_low_c": i["cooling_c"]["low"], "cooling_mid_c": i["cooling_c"]["mid"],
                    "cooling_high_c": i["cooling_c"]["high"]})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="plan_{plan_id}.csv"'})


@router.put("/{plan_id}/status")
async def set_status(plan_id: str, body: StatusBody):
    try:
        return store.set_plan_status(plan_id, body.status, body.actor, body.note)
    except KeyError:
        raise HTTPException(404, "plan not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
