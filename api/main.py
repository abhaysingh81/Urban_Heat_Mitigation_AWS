"""
FastAPI application entrypoint for the Urban Heat MVP.
"""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import pandas as pd

from pipeline.config import data_version, CITIES, DEFAULT_CITY, list_cities, city_features_file, PROCESSED_DIR
from api.deps import get_city_id
from api.routers import grid, hotspots, drivers, scenarios, risk, plans, brief, reports, meta, lab
from api import aws
from api.data_source import read_features, data_kind
import os
from api.schemas import OverviewResponse
import json

app = FastAPI(
    title="Urban Heat MVP API",
    description="API for the Urban Heat Mitigation & Cooling Strategies MVP",
    version="1.0.0",
)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://urban-heat-mitigation-mu.vercel.app",
        "http://localhost:5173",                            # keep this so local dev still works
        *[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Model-Version", "X-Data-Date"],
)

# Compress large responses (city grids are several MB of GeoJSON; Lambda caps responses at 6 MB)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Include routers
app.include_router(grid.router)
app.include_router(hotspots.router)
app.include_router(drivers.router)
app.include_router(scenarios.router)
app.include_router(risk.router)
app.include_router(plans.router)
app.include_router(brief.router)
app.include_router(reports.router)
app.include_router(meta.router)
app.include_router(lab.router)

from api.routers import alerts, sensors, system
app.include_router(alerts.router)
app.include_router(system.router)
app.include_router(sensors.router)


@app.middleware("http")
async def edge_only(request, call_next):
    """With AWS WAF enabled the API is published through CloudFront, which adds a secret header.
    A request without it came straight to API Gateway, around the firewall, and is refused."""
    from api import net
    if net.edge_secret() and not net.came_through_edge(request.headers):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Use the site address for this API."}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def add_version_headers(request, call_next):
    """Every response carries the model version and data date (trust/audit)."""
    response = await call_next(request)
    response.headers["X-Model-Version"] = aws.model_version()
    response.headers["X-Data-Date"] = aws.data_date()
    return response


@app.get("/api/v1/cities", tags=["overview"])
async def get_cities():
    """
    Returns every city available in the demo, for the frontend's city
    picker. Includes the default city id so the frontend knows which
    one to select on first load.
    """
    return {
        "default_city": DEFAULT_CITY,
        "cities": list_cities(),
    }


@app.get("/api/v1/overview", response_model=OverviewResponse, tags=["overview"])
async def get_overview(city_id: str = Depends(get_city_id)):
    """
    Returns high-level KPI metrics for the city overview.
    """
    city = CITIES[city_id]
    df = read_features(city_id)

    hotspot_mask = df["tier"].isin(["critical", "high"])
    hotspot_count = int(hotspot_mask.sum())

    mean_lst = float(df["lst_mean"].mean())

    # Try to load global importance for top driver
    try:
        if data_kind(city_id) == "real":
            from models.explain_real import global_importance
            importance = global_importance()
        else:
            from models.explain import get_global_importance
            importance = get_global_importance()
        top_driver = importance[0]["feature"] if importance else "frac_impervious"
    except Exception:
        top_driver = "frac_impervious"

    best_name, max_cooling = "Tree Cover (+20%)", -4.5  # legacy static values (synthetic previews)
    if data_kind(city_id) == "real":
        from api.routers.scenarios import _real_presets
        from pipeline.config import city_real_features_file
        presets = [p for p in _real_presets(city_id, data_version(city_id))
                   if p["interventions"]]
        if presets:
            best = max(presets, key=lambda p: p["cost_efficiency"])
            best_name = best["name"]
            max_cooling = min(p["mean_cooling_c"] for p in presets)

    return {
        "city": f"{city['name']}, {city['state']}",
        "analysis_period": city["season_label"],
        "grid_cells": len(df),
        "mean_lst_c": round(mean_lst, 2),
        "max_lst_c": round(float(df["lst_max"].max()), 2),
        "min_lst_c": round(float(df["lst_mean"].min()), 2),
        "std_lst_c": round(float(df["lst_mean"].std()), 2),
        "uhi_intensity_c": round(float(df["lst_mean"].max()) - mean_lst, 2),
        "hotspot_area_km2": round(hotspot_count * 0.25, 2),
        "hotspot_count": hotspot_count,
        "top_driver": top_driver,
        "best_intervention": best_name,
        "max_potential_cooling_c": max_cooling,
        "tier_distribution": df["tier"].value_counts().to_dict(),
        "data_kind": data_kind(city_id),
    }


@app.get("/api/v1/validation", tags=["overview"])
async def get_validation(city_id: str = Depends(get_city_id)):
    """
    Returns real-satellite-data validation info for this city, if it
    exists. Most cities use realistic synthetic data and won't have
    this — that's expected, not an error, so we return a flag rather
    than a 404. Generated by running `pipeline/fetch_real_lst.py`,
    which compares this city's synthetic LST against a real Landsat
    Collection 2 Level-2 thermal scene.
    """
    if data_kind(city_id) == "real":
        # The real tier is trained directly on Landsat; no separate synthetic-vs-real check applies.
        return {"available": False, "reason": "model is trained on the real Landsat composite; see /api/v1/model-card"}
    meta_path = PROCESSED_DIR / city_id / "landsat_validation_meta.json"
    if not meta_path.exists():
        return {"available": False}

    meta = json.loads(meta_path.read_text())
    meta["available"] = True
    return meta


@app.get("/health", tags=["system"])
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
