"""Sentinel-2 L2A median composite -> NDVI / NDBI / MNDWI per cell."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
from rasterio.enums import Resampling

from pipeline.config import REAL_MONTHS, REAL_YEARS
from pipeline.real.gridspec import GridSpec
from pipeline.real.stac import asset_href, open_catalog, read_to_grid, search, sentinel2_boa_offset

FACTOR = 10  # 50 m
MAX_SCENES = 8
# SCL classes to drop: no-data, saturated, cloud shadow, cloud med/high, cirrus
_SCL_BAD = (0, 1, 3, 8, 9, 10)


def _reflectance(dn: np.ndarray, offset: float) -> np.ndarray:
    return np.clip((dn - offset) / 10000.0, 0, 1.5)


def _norm_diff(a, b):
    with np.errstate(all="ignore"):
        return (a - b) / (a + b)


def build(spec: GridSpec) -> dict:
    catalog = open_catalog()
    bbox = list(spec.bbox_wgs84())
    items = []
    for year in REAL_YEARS:
        items += search(
            catalog, collections=["sentinel-2-l2a"], bbox=bbox,
            datetime=f"{year}-{REAL_MONTHS[0]:02d}-01/{year}-{REAL_MONTHS[-1]:02d}-30",
            query={"eo:cloud_cover": {"lt": 15}},
        )
    items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
    print(f"  Sentinel-2: {len(items)} candidates, using up to {MAX_SCENES}")

    ndvi_l, ndbi_l, mndwi_l = [], [], []
    used = 0
    for item in items:
        if used >= MAX_SCENES:
            break
        try:
            # 10 m bands: overview 1 (~40 m); 20 m bands: overview 0 (~40 m)
            jobs = {
                "red": ("B04", 1, Resampling.average, 0), "nir": ("B08", 1, Resampling.average, 0),
                "green": ("B03", 1, Resampling.average, 0), "swir": ("B11", 0, Resampling.average, 0),
                "scl": ("SCL", 0, Resampling.nearest, None),
            }
            with ThreadPoolExecutor(max_workers=5) as pool:
                futs = {k: pool.submit(read_to_grid, asset_href(item, a), spec, FACTOR, rs,
                                       nodata_in=nd, overview=ov)
                        for k, (a, ov, rs, nd) in jobs.items()}
                red, nir, green, swir, scl = (futs[k].result() for k in
                                              ("red", "nir", "green", "swir", "scl"))
        except Exception as e:
            print(f"    [skip] {item.id}: {e}")
            continue
        offset = sentinel2_boa_offset(item)
        r, n, g, s = (_reflectance(x, offset) for x in (red, nir, green, swir))
        bad = np.isin(np.nan_to_num(scl, nan=0).astype(int), _SCL_BAD)
        ndvi, ndbi, mndwi = _norm_diff(n, r), _norm_diff(s, n), _norm_diff(g, s)
        for arr in (ndvi, ndbi, mndwi):
            arr[bad] = np.nan
        if np.mean(~np.isnan(ndvi)) < 0.2:
            continue
        ndvi_l.append(ndvi); ndbi_l.append(ndbi); mndwi_l.append(mndwi)
        used += 1
        print(f"    + {item.id}")

    if used < 2:
        raise RuntimeError(f"Sentinel-2: only {used} usable scenes for {spec.city_id}")

    def comp(layers):
        with np.errstate(all="ignore"):
            return np.nanmedian(np.stack(layers), axis=0)

    ndvi, ndbi, mndwi = comp(ndvi_l), comp(ndbi_l), comp(mndwi_l)
    return {
        "arrays": {
            "ndvi_mean": spec.block_reduce(ndvi, FACTOR, "mean"),
            "ndvi_std": spec.block_reduce(ndvi, FACTOR, "std"),
            "ndbi_mean": spec.block_reduce(ndbi, FACTOR, "mean"),
            "mndwi_mean": spec.block_reduce(mndwi, FACTOR, "mean"),
        },
        "n_scenes": used,
    }
