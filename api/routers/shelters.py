"""Cool refuges with live status (Feature L). Reading is public; changing a status needs an officer."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import auth, live, shelters, store
from api.routers.risk import require_real

router = APIRouter(prefix="/api/v1/shelters", tags=["cool refuges"])


class ShelterStatusBody(BaseModel):
    status: Literal["open", "busy", "full", "closed"]
    note: str = Field("", max_length=200)


def _public(s: dict) -> dict:
    keep = ("id", "name", "type", "lat", "lon", "status", "updated_at", "stale", "last_status", "distance_m")
    return {k: s[k] for k in keep if k in s}


@router.get("")
async def list_refuges(city_id: str = Depends(require_real),
                       q: Optional[str] = Query(None, max_length=60, description="name contains"),
                       lat: Optional[float] = Query(None, ge=-90, le=90),
                       lon: Optional[float] = Query(None, ge=-180, le=180),
                       status: Optional[str] = Query(None, pattern="^(open|busy|full|closed|unknown)$"),
                       limit: int = Query(50, ge=1, le=500)):
    """Cool refuges with their live status: nearest first when lat/lon are given, otherwise the
    most recently updated first."""
    items = shelters.annotate(city_id, shelters.refuges(city_id))
    counts = {s: sum(1 for i in items if i["status"] == s) for s in (*store.SHELTER_STATUSES, "unknown")}
    if q:
        items = [i for i in items if q.lower() in i["name"].lower()]
    if status:
        items = [i for i in items if i["status"] == status]
    if lat is not None and lon is not None:
        for i, d in zip(items, shelters.distances_m(lat, lon, items)):
            i["distance_m"] = int(d)
        items.sort(key=lambda i: i["distance_m"])
    else:
        items.sort(key=lambda i: i["name"])
        items.sort(key=lambda i: i["updated_at"] or "", reverse=True)  # stable: updated first, then by name
    return {"city_id": city_id, "counts": counts, "stale_after_hours": shelters.STALE_HOURS,
            "refuges": [_public(i) for i in items[:limit]]}


@router.put("/{spot_id}/status")
async def set_refuge_status(body: ShelterStatusBody, spot_id: str, city_id: str = Depends(require_real),
                            user: dict = Depends(auth.require_role(auth.WARD_OFFICER, auth.CITY_PLANNER))):
    refuge = next((r for r in shelters.refuges(city_id) if r["id"] == spot_id), None)
    if refuge is None:
        raise HTTPException(404, "cool refuge not found in this city")
    doc = store.save_shelter_status(city_id, spot_id, body.status, actor=user["name"], note=body.note)
    out = _public({**refuge, **shelters.live_status(doc)})
    live.broadcast({"type": "shelter.updated", "city_id": city_id, "shelter": out})
    return out
