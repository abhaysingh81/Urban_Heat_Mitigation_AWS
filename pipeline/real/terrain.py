"""Copernicus DEM 30 m -> elevation and slope per cell."""

from __future__ import annotations

import numpy as np
from rasterio.enums import Resampling

from pipeline.real.gridspec import GridSpec
from pipeline.real.stac import open_catalog, read_to_grid, search

FACTOR = 10  # 50 m


def build(spec: GridSpec) -> dict:
    catalog = open_catalog()
    items = search(catalog, collections=["cop-dem-glo-30"], bbox=list(spec.bbox_wgs84()))
    if not items:
        raise RuntimeError(f"No DEM tiles for {spec.city_id}")
    dem = np.full(spec.fine_shape(FACTOR), np.nan, dtype=np.float32)
    for item in items:
        tile = read_to_grid(item.assets["data"].href, spec, FACTOR,
                            Resampling.bilinear, nodata_in=None, overview=None)
        fill = np.isnan(dem) & ~np.isnan(tile)
        dem[fill] = tile[fill]

    px = spec.fine_pixel_size(FACTOR)
    gy, gx = np.gradient(np.nan_to_num(dem, nan=np.nanmean(dem)), px)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    slope[np.isnan(dem)] = np.nan
    return {"arrays": {
        "elev_mean": spec.block_reduce(dem, FACTOR, "mean"),
        "slope_mean": spec.block_reduce(slope, FACTOR, "mean"),
    }}
