"""
Grid data endpoint — serves a city's grid as GeoJSON.
"""

import json
from fastapi import APIRouter, Query, Depends
from typing import Optional

from api.data_source import grid_geojson, read_features, data_kind
from api.deps import get_city_id

router = APIRouter(prefix="/api/v1/grid", tags=["grid"])


@router.get("")
async def get_grid(
    city_id: str = Depends(get_city_id),
    tier: Optional[str] = Query(None, description="Comma-separated tier filter"),
    bbox: Optional[str] = Query(None, description="west,south,east,north"),
):
    """
    Returns a city's full grid as GeoJSON FeatureCollection.
    Optionally filter by tier and/or bounding box.
    """
    geojson = grid_geojson(city_id)
    features = geojson["features"]

    # Filter by tier
    if tier:
        tiers = [t.strip() for t in tier.split(",")]
        features = [f for f in features if f["properties"].get("tier") in tiers]

    # Filter by bbox
    if bbox:
        parts = [float(x) for x in bbox.split(",")]
        if len(parts) == 4:
            west, south, east, north = parts
            filtered = []
            for feat in features:
                coords = feat["geometry"]["coordinates"][0]
                centroid_lon = sum(c[0] for c in coords) / len(coords)
                centroid_lat = sum(c[1] for c in coords) / len(coords)
                if west <= centroid_lon <= east and south <= centroid_lat <= north:
                    filtered.append(feat)
            features = filtered

    return {
        "type": "FeatureCollection",
        "data_kind": data_kind(city_id),
        "features": features,
    }


@router.get("/stats")
async def get_grid_stats(city_id: str = Depends(get_city_id)):
    """Return summary statistics about a city's grid."""
    import pandas as pd

    df = read_features(city_id)
    return {
        "data_kind": data_kind(city_id),
        "total_cells": len(df),
        "lst_mean": round(float(df["lst_mean"].mean()), 2),
        "lst_std": round(float(df["lst_mean"].std()), 2),
        "lst_min": round(float(df["lst_mean"].min()), 2),
        "lst_max": round(float(df["lst_mean"].max()), 2),
        "tier_distribution": df["tier"].value_counts().to_dict(),
    }
