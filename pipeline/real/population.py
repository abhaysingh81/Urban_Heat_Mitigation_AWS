"""
Population per cell from Meta's High Resolution Population Density Maps
(HRSL, 30 m, AWS Open Data Registry, CC BY 4.0) — cloud-optimised GeoTIFFs read
with HTTP range requests, so only the city window is fetched.

If HRSL cannot be read we fall back to a clearly flagged building-count proxy
so the pipeline still completes; the data card records which source was used.
"""

from __future__ import annotations

import numpy as np
from rasterio.enums import Resampling

from pipeline.real.gridspec import GridSpec
from pipeline.real.stac import read_to_grid

HRSL_VRT = "/vsicurl/https://dataforgood-fb-data.s3.amazonaws.com/hrsl-cogs/hrsl_general/hrsl_general-latest.vrt"
FACTOR = 10  # 50 m fine grid
PERSONS_PER_BUILDING = 5.0  # crude fallback only


def build(spec: GridSpec, building_density: np.ndarray | None) -> dict:
    try:
        # Resampling.sum keeps head-counts conserved when 30 m pixels are merged to 50 m.
        fine = read_to_grid(HRSL_VRT, spec, FACTOR, Resampling.sum, nodata_in=None, retries=3)
        pop = spec.block_reduce(np.nan_to_num(fine, nan=0.0), FACTOR, "sum")
        if float(np.nansum(pop)) <= 0:
            raise RuntimeError("HRSL window is empty")
        source = "meta_hrsl_30m"
    except Exception as e:
        print(f"    [pop] HRSL failed ({e}); using building-count proxy")
        if building_density is None or np.all(np.isnan(building_density)):
            raise RuntimeError("No population source available for "
                               f"{spec.city_id}: HRSL failed and OSM buildings missing")
        per_cell = building_density * (spec.cell ** 2 / 1e6)
        pop = np.nan_to_num(per_cell) * PERSONS_PER_BUILDING
        source = "building_count_proxy"
    return {"arrays": {"pop_total": pop,
                       "pop_density": pop / (spec.cell ** 2 / 1e6)},  # per km²
            "source": source}
