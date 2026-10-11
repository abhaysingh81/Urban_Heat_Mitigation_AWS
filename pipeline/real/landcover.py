"""ESA WorldCover 2021 (10 m) -> class fractions per cell."""

from __future__ import annotations

import numpy as np
from rasterio.enums import Resampling

from pipeline.real.gridspec import GridSpec
from pipeline.real.stac import (
    asset_href, is_planetary, open_catalog, read_to_grid, search, worldcover_tile_urls,
)

FACTOR = 20  # 25 m fine grid -> 400 samples per 500 m cell
# WorldCover classes
TREE, SHRUB, GRASS, CROP, BUILT, BARE, WATER, WETLAND, MANGROVE = 10, 20, 30, 40, 50, 60, 80, 90, 95


def build(spec: GridSpec) -> dict:
    bbox = spec.bbox_wgs84()
    if is_planetary():
        items = search(open_catalog(), collections=["esa-worldcover"],
                       bbox=list(bbox), datetime="2021-01-01/2021-12-31")
        hrefs = [asset_href(item, "map") for item in items]
    else:  # Earth Search has no WorldCover collection: read the same tiles from AWS Open Data
        hrefs = worldcover_tile_urls(bbox)
    if not hrefs:
        raise RuntimeError(f"No WorldCover tiles for {spec.city_id}")

    fine = np.full(spec.fine_shape(FACTOR), np.nan, dtype=np.float32)
    for href in hrefs:  # tiles are disjoint -> first valid wins
        try:
            tile = read_to_grid(href, spec, FACTOR,
                                Resampling.nearest, nodata_in=0, overview=0)  # ~20 m
        except RuntimeError as e:
            if len(hrefs) == 1:
                raise
            print(f"    [skip] WorldCover tile: {e}")  # e.g. an all-ocean tile that does not exist
            continue
        fill = np.isnan(fine) & ~np.isnan(tile)
        fine[fill] = tile[fill]
    if np.isnan(fine).all():
        raise RuntimeError(f"No readable WorldCover tiles for {spec.city_id}")

    def frac(*classes):
        m = np.where(np.isnan(fine), np.nan, np.isin(fine, classes).astype(np.float32))
        return spec.block_reduce(m, FACTOR, "mean")

    return {"arrays": {
        "frac_impervious": frac(BUILT),
        "frac_tree": frac(TREE, MANGROVE),
        "frac_vegetation": frac(TREE, SHRUB, GRASS, CROP, MANGROVE, WETLAND),
        "frac_bare_soil": frac(BARE),
        "frac_water": frac(WATER),
    }}
