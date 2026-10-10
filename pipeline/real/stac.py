"""Planetary Computer STAC helpers + warping onto a city's fine grid."""

from __future__ import annotations

import time

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

from pipeline.real.gridspec import GridSpec

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
_OUTSIDE = -9999.0  # fill value for pixels outside a source raster


def open_catalog():
    import planetary_computer
    import pystac_client
    return pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)


def search(catalog, retries: int = 3, **kwargs) -> list:
    last = None
    for i in range(retries):
        try:
            return list(catalog.search(**kwargs).items())
        except Exception as e:  # network blips are common on public STAC
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"STAC search failed after {retries} tries: {last}")


def read_to_grid(href: str, spec: GridSpec, factor: int,
                 resampling: Resampling = Resampling.average,
                 nodata_in: float | None = 0, dtype=np.float32,
                 retries: int = 3, overview: int | None = None) -> np.ndarray:
    """Read one raster band onto the city's fine grid (north-up, NaN where
    the source has no data). Only the needed window is fetched (COG).
    `overview` reads a COG overview level (0 = 2x coarser, 1 = 4x …), which
    cuts transfer ~4^(n+1)x when the target grid is much coarser than the
    source pixels."""
    last = None
    for i in range(retries):
        try:
            open_kw = {"OVERVIEW_LEVEL": overview} if overview is not None else {}
            with rasterio.open(href, **open_kw) as src:
                src_nodata = src.nodata if src.nodata is not None else nodata_in
                # Always give the warp an explicit fill value so areas outside the
                # source footprint become NaN instead of a real-looking 0.
                fill = src_nodata if src_nodata is not None else _OUTSIDE
                with WarpedVRT(src, crs=spec.crs, transform=spec.fine_transform(factor),
                               width=spec.fine_shape(factor)[1],
                               height=spec.fine_shape(factor)[0],
                               resampling=resampling, src_nodata=src_nodata,
                               nodata=fill) as vrt:
                    arr = vrt.read(1).astype(dtype)
            arr[arr == fill] = np.nan
            return arr
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"read failed for {href[:80]}…: {last}")
