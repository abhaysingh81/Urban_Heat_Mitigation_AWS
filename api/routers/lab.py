"""Scenario Lab and Ward Planner endpoints (real-data cities only)."""

import csv
import io
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api import store
from api.routers.risk import require_real
from models import conditions as cond
from models import planner as planner_mod
from models import scenario_lab, ward_factors
from models.interventions import LIBRARY, library_json

router = APIRouter(prefix="/api/v1", tags=["scenario lab & planner"])


class ConditionsBody(BaseModel):
    mode: Literal["today", "hot_season", "custom"] = "hot_season"
    climate_shift_c: float = Field(0.0, ge=-1, le=4)
    tmax_c: Optional[float] = Field(None, ge=20, le=55)
    humidity_pct: Optional[float] = Field(None, ge=5, le=100)
    power_cut: bool = False
    water_shortage: bool = False

    def to_req(self) -> cond.ConditionsRequest:
        return cond.ConditionsRequest(**self.model_dump())


class ActionBody(BaseModel):
    key: str
    intensity: float = Field(0.0, ge=0, le=1)
    params: dict = Field(default_factory=dict)


class TargetBody(BaseModel):
    mode: Literal["hotspots", "wards", "city"] = "hotspots"
    ward_ids: list[str] = Field(default_factory=list)


class SimulateBody(BaseModel):
    conditions: ConditionsBody = Field(default_factory=ConditionsBody)
    actions: list[ActionBody] = Field(..., min_length=1, max_length=len(LIBRARY))
    target: TargetBody = Field(default_factory=TargetBody)
    survival: float = Field(0.7, gt=0, le=1)
    preset: str = "balanced"


class PlanBody(BaseModel):
    budget_lakh: float = Field(..., gt=0, le=1_000_000, description="Capital budget in INR lakh")
    years: int = Field(3, ge=1, le=10)
    objective: Literal["people", "cooling", "equity", "risk"] = "equity"
    interventions: list[str] = Field(default_factory=lambda: list(LIBRARY))
    unit_caps: dict[str, float] = Field(default_factory=dict)
    params: dict[str, dict] = Field(default_factory=dict)
    access_share: float = Field(0.15, ge=0, le=0.6)
    ward_min_share: float = Field(0.0, ge=0, le=0.2)
    ward_max_share: float = Field(0.25, ge=0.01, le=1)
    type_max_share: float = Field(0.40, ge=0.05, le=1)
    mandatory_wards: list[str] = Field(default_factory=list)
    excluded_wards: list[str] = Field(default_factory=list)
    water_budget_kl_day: Optional[float] = Field(None, ge=0)
    survival: float = Field(0.7, gt=0, le=1)
    preset: str = "balanced"
    conditions: ConditionsBody = Field(default_factory=ConditionsBody)
    compare: bool = False
    save: bool = False

    def to_spec(self, city_id: str) -> planner_mod.PlanSpec:
        d = self.model_dump(exclude={"compare", "save", "conditions"})
        return planner_mod.PlanSpec(city_id=city_id, conditions=self.conditions.to_req(), **d)


@router.get("/lab/interventions")
async def interventions():
    return {"interventions": library_json()}


@router.post("/lab/conditions")
async def conditions(body: ConditionsBody, city_id: str = Depends(require_real)):
    try:
        return cond.resolve(city_id, body.to_req())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/lab/simulate")
async def simulate(body: SimulateBody, city_id: str = Depends(require_real)):
    try:
        return scenario_lab.simulate(city_id, body.conditions.to_req(),
                                     [a.model_dump() for a in body.actions],
                                     body.target.model_dump(), body.survival, body.preset)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/planner/wards")
async def planner_wards(city_id: str = Depends(require_real),
                        preset: str = "balanced", power_cut: bool = False, water_shortage: bool = False,
                        w_hazard: Optional[float] = Query(None, ge=0), w_exposure: Optional[float] = Query(None, ge=0),
                        w_sensitivity: Optional[float] = Query(None, ge=0),
                        w_coping: Optional[float] = Query(None, ge=0)):
    weights = {k: v for k, v in (("hazard", w_hazard), ("exposure", w_exposure),
                                 ("sensitivity", w_sensitivity), ("coping", w_coping)) if v is not None}
    try:
        out = ward_factors.ward_profile(city_id, preset, weights or None, power_cut, water_shortage)
    except ValueError as e:
        raise HTTPException(400, str(e))
    out["presets"] = ward_factors.WEIGHT_PRESETS
    return out


@router.post("/planner/plan")
async def make_plan(body: PlanBody, city_id: str = Depends(require_real)):
    spec = body.to_spec(city_id)
    try:
        result = planner_mod.plan(spec)
        if body.compare:
            result["objective_comparison"] = planner_mod.compare_objectives(spec)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.save:
        doc = store.save_plan(city_id, result)
        result["plan_id"], result["status"] = doc["id"], doc["status"]
    return result


@router.get("/planner/plan/{plan_id}/work-orders.csv")
async def work_orders_csv(plan_id: str):
    doc = store.get_plan(plan_id)
    if not doc or "work_orders" not in doc.get("plan", {}):
        raise HTTPException(404, "plan not found (or saved before work orders existed)")
    buf = io.StringIO()
    cols = ["ward_id", "ward_name", "intervention", "label", "units", "unit", "n_cells", "capex_lakh",
            "opex_lakh_yr", "water_kl_day", "department", "start_quarter", "finish_quarter",
            "risk_before", "risk_after", "kpis"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for wo in doc["plan"]["work_orders"]:
        for ln in wo["lines"]:
            w.writerow({**{k: ln.get(k) for k in cols}, "ward_id": wo["ward_id"], "ward_name": wo["ward_name"],
                        "risk_before": wo["risk_before"], "risk_after": wo["risk_after"],
                        "kpis": "; ".join(ln["kpis"])})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="work_orders_{plan_id}.csv"'})
