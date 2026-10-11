"""
Target layer: multi-scene Landsat 8/9 Collection 2 Level-2 surface
temperature composite, aggregated to the 500 m grid.

Replaces the single-scene fetch in pipeline/fetch_real_lst.py. For every
hot-season window in REAL_YEARS we take the clearest scenes, mask
cloud/shadow with QA_PIXEL, calibrate ST_B10 to °C with the official USGS
scale/offset, and take the per-pixel median across scenes.
"""

from __future__ import annotations

import numpy as np
from rasterio.enums import Resampling

from pipeline.config import (
    LANDSAT_OFFSET, LANDSAT_SCALE_FACTOR, REAL_CLOUD_MAX, REAL_MAX_SCENES,
    REAL_MIN_SCENES, REAL_MONTHS, REAL_YEARS,
)
from pipeline.real.gridspec import GridSpec
from pipeline.real.stac import asset_href, open_catalog, read_to_grid, search

FACTOR = 10  # 50 m fine grid (Landsat is 30 m)
# QA_PIXEL bits: 1 dilated cloud, 2 cirrus, 3 cloud, 4 cloud shadow
_QA_BAD_MASK = (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)


def find_scenes(spec: GridSpec, catalog=None) -> list:
    catalog = catalog or open_catalog()
    bbox = list(spec.bbox_wgs84())
    items = []
    for year in REAL_YEARS:
        start, end = f"{year}-{REAL_MONTHS[0]:02d}-01", f"{year}-{REAL_MONTHS[-1]:02d}-30"
        found = search(
            catalog, collections=["landsat-c2-l2"], bbox=bbox,
            datetime=f"{start}/{end}",
            query={"eo:cloud_cover": {"lt": REAL_CLOUD_MAX},
                   "platform": {"in": ["landsat-8", "landsat-9"]}},
        )
        items.extend(found)
    # one best scene per acquisition date/footprint-set, clearest first
    items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
    return items[: REAL_MAX_SCENES * 2]  # extra headroom for failed reads


def _scene_lst_c(item, spec: GridSpec) -> np.ndarray | None:
    try:
        st = read_to_grid(asset_href(item, "lwir11"), spec, FACTOR,
                          Resampling.bilinear, nodata_in=0)
        qa = read_to_grid(asset_href(item, "qa_pixel"), spec, FACTOR,
                          Resampling.nearest, nodata_in=None, dtype=np.float32)
    except Exception as e:
        print(f"    [skip] {item.id}: {e}")
        return None
    lst = st * LANDSAT_SCALE_FACTOR + LANDSAT_OFFSET - 273.15
    bad = (np.nan_to_num(qa, nan=1).astype(np.uint16) & _QA_BAD_MASK) != 0
    lst[bad] = np.nan
    lst[(lst < 5) | (lst > 80)] = np.nan  # physically implausible → fill/edge
    return lst


def build(spec: GridSpec) -> dict:
    """Return per-cell target arrays + scene metadata."""
    catalog = open_catalog()
    items = find_scenes(spec, catalog)
    print(f"  Landsat: {len(items)} candidate scenes")

    cell_means, used = [], []
    for item in items:
        if len(used) >= REAL_MAX_SCENES:
            break
        lst = _scene_lst_c(item, spec)
        if lst is None:
            continue
        valid_frac = float(np.mean(~np.isnan(lst)))
        if valid_frac < 0.25:  # scene barely touches the city or is cloudy
            print(f"    [skip] {item.id}: only {valid_frac:.0%} valid")
            continue
        cell_means.append(spec.block_reduce(lst, FACTOR, "mean"))
        used.append({
            "id": item.id, "date": item.datetime.date().isoformat(),
            "platform": item.properties.get("platform"),
            "cloud_cover": item.properties.get("eo:cloud_cover"),
            "valid_frac": round(valid_frac, 3),
        })
        print(f"    + {item.id} ({used[-1]['date']}, valid {valid_frac:.0%})")

    if len(used) < REAL_MIN_SCENES:
        raise RuntimeError(
            f"Only {len(used)} usable Landsat scenes for {spec.city_id} "
            f"(need ≥{REAL_MIN_SCENES}).")

    stack = np.stack(cell_means)  # (scenes, rows, cols), per-cell means
    with np.errstate(all="ignore"):
        lst_c = np.nanmedian(stack, axis=0)
        lst_std = np.nanstd(stack, axis=0)
    n_valid = np.sum(~np.isnan(stack), axis=0)
    lst_c[n_valid < 3] = np.nan  # too few observations to trust

    return {
        "arrays": {"lst_c": lst_c, "lst_std": lst_std, "n_scenes": n_valid.astype(float)},
        "scenes": used,
    }
