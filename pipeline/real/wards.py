"""
Analysis zones ("wards") for risk aggregation.

Default: 2 km x 2 km blocks (4x4 cells), always available and consistent.
If official ward boundaries exist at data/external/<city>_wards.geojson
(polygons with a `name` property) cells are assigned by centroid instead.
"""

from __future__ import annotations

import numpy as np

from pipeline.config import PROJECT_ROOT
from pipeline.real.gridspec import GridSpec

BLOCK = 4  # cells per zone side


def assign(spec: GridSpec) -> dict:
    idx = np.arange(spec.n_cells)
    row, col = spec.idx_to_rowcol(idx)
    external = PROJECT_ROOT / "data" / "external" / f"{spec.city_id}_wards.geojson"
    if external.exists():
        import geopandas as gpd
        from shapely.geometry import Point
        polys = gpd.read_file(external).to_crs(4326)
        lon, lat = spec.cell_centers_lonlat()
        pts = gpd.GeoDataFrame(geometry=[Point(x, y) for x, y in zip(lon, lat)], crs=4326)
        joined = gpd.sjoin(pts, polys[["name", "geometry"]], how="left", predicate="within")
        joined = joined[~joined.index.duplicated(keep="first")]
        names = joined["name"].fillna("Unassigned").to_numpy()
        ids = np.array([f"W_{n}" for n in names])
        return {"ward_id": ids, "ward_name": names, "kind": "official_boundaries"}
    rb, cb = row // BLOCK, col // BLOCK
    ids = np.array([f"Z{r:02d}{c:02d}" for r, c in zip(rb, cb)])
    names = np.array([f"Zone {r + 1}-{c + 1}" for r, c in zip(rb, cb)])
    return {"ward_id": ids, "ward_name": names, "kind": "2km_analysis_zones"}
