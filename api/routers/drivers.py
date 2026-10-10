"""
Heat driver analysis endpoint — SHAP-based explainability.
"""

import json
from fastapi import APIRouter, Query, Depends
from typing import Optional

from pipeline.config import MODEL_DIR
from api.data_source import is_real
from api.deps import get_city_id

router = APIRouter(prefix="/api/v1/drivers", tags=["drivers"])


@router.get("")
async def get_drivers(
    city_id: str = Depends(get_city_id),
    grid_id: Optional[str] = Query(None, description="Grid cell ID for per-cell explanation"),
):
    """
    Returns global feature importance (shared across all cities) and an
    optional per-cell SHAP explanation for one cell in this city.
    """
    # Global importance
    importance_file = MODEL_DIR / "feature_importance.json"
    if is_real(city_id):
        from models.explain_real import global_importance as real_importance
        global_importance = real_importance()
    elif importance_file.exists():
        with open(importance_file) as f:
            global_importance = json.load(f)
    else:
        global_importance = []

    result = {"global_importance": global_importance}

    # Per-cell explanation
    if grid_id:
        try:
            if is_real(city_id):
                from models.explain_real import cell_explanation as get_cell_explanation
            else:
                from models.explain import get_cell_explanation
            explanation = get_cell_explanation(city_id, grid_id)
            if explanation:
                result["cell_explanation"] = explanation
        except Exception as e:
            result["cell_explanation_error"] = str(e)

    return result


@router.get("/hotspot-drivers")
async def get_hotspot_drivers(city_id: str = Depends(get_city_id)):
    """
    Returns the top heat drivers specifically for this city's hotspot cells.
    """
    try:
        if is_real(city_id):
            from models.explain_real import top_drivers_for_hotspots as get_top_drivers_for_hotspots
        else:
            from models.explain import get_top_drivers_for_hotspots
        return {"hotspot_drivers": get_top_drivers_for_hotspots(city_id)}
    except Exception as e:
        return {"error": str(e), "hotspot_drivers": []}
