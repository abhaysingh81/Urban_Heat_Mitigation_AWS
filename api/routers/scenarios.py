"""
Cooling scenario simulation endpoint.
"""

import json
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Depends

from api.data_source import is_real
from api.schemas import ScenarioRequest, ScenarioResponse, PresetScenario
from pipeline.config import data_version, city_presets_file
from api.deps import get_city_id

router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])

# Presets for real-data cities are computed from the real model/data, never
# read from the (synthetic) presets.json files.
_REAL_PRESETS = [
    ("baseline", "Baseline", "Current conditions — no interventions", {}),
    ("green_boost", "Green Cover Boost", "Aggressive tree planting in all hotspot cells",
     {"tree_cover": 0.7}),
    ("cool_roofs", "Cool Roofs", "Reflective roofs across hotspot cells", {"cool_roofs": 0.8}),
    ("shade_and_pavement", "Shade + Cool Pavement",
     "Shade structures and cool pavements in hotspot cells",
     {"shade_structures": 0.6, "cool_pavement": 0.6}),
    ("combined", "Combined", "Trees, cool roofs and shade together",
     {"tree_cover": 0.5, "cool_roofs": 0.5, "shade_structures": 0.4}),
]


@lru_cache(maxsize=16)
def _real_presets(city_id: str, version: tuple):
    from models.real_simulate import simulate
    out = []
    for sid, name, desc, ints in _REAL_PRESETS:
        s = simulate(city_id, ints)["summary"]
        out.append({
            "scenario_id": sid, "name": name, "description": desc, "interventions": ints,
            "mean_cooling_c": s["mean_cooling_c"], "max_cooling_c": s["max_cooling_c"],
            "hotspots_before": s["hotspots_before"], "hotspots_after": s["hotspots_after"],
            "hotspot_reduction_pct": s["hotspot_reduction_pct"],
            "cost_estimate_m": s["cost_estimate_m"], "cost_efficiency": s["cost_efficiency_c_per_m"],
        })
    return out


@router.post("/simulate", response_model=ScenarioResponse)
async def simulate_scenario(request: ScenarioRequest, city_id: str = Depends(get_city_id),
                            tree_survival: float = 0.7):
    """
    Simulate a custom cooling intervention scenario for one city.
    Real-data cities return estimates with a low/mid/high cooling range.
    """
    try:
        interventions = {i.type: i.intensity for i in request.interventions}
        if is_real(city_id):
            from models.real_simulate import simulate
            return simulate(city_id, interventions, request.target_cells, tree_survival)
        from models.simulate import simulate_scenario as run_simulation
        return run_simulation(city_id=city_id, interventions=interventions,
                              target_cells=request.target_cells)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/presets", response_model=list[PresetScenario])
async def get_presets(city_id: str = Depends(get_city_id)):
    """
    Returns list of pre-computed scenario summaries for one city.
    """
    if is_real(city_id):
        from pipeline.config import city_real_features_file
        return _real_presets(city_id, data_version(city_id))
    presets_file = city_presets_file(city_id)
    if not presets_file.exists():
        return []

    with open(presets_file) as f:
        return json.load(f)
