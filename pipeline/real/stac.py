"""STAC helpers (Planetary Computer or Earth Search on AWS) + warping onto a city's fine grid.

The two catalogues serve the same products with different asset names, hrefs and,
for Sentinel-2, different pixel offsets. Everything catalogue-specific lives here so
the stage modules stay identical for both.
"""

from __future__ import annotations

import os
import time

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

from pipeline.real.gridspec import GridSpec

# Default to Microsoft Planetary Computer; override with Earth Search on AWS (e.g. https://earth-search.aws.element84.com/v1)
DEFAULT_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1"
STAC_URL = os.environ.get("STAC_URL", DEFAULT_STAC_URL)
_OUTSIDE = -9999.0  # fill value for pixels outside a source raster

# Planetary Computer asset name -> Earth Search asset name (Landsat and DEM names are the same)
_EARTH_SEARCH_ASSETS = {"B03": "green", "B04": "red", "B08": "nir", "B11": "swir16", "SCL": "scl"}
# Public (not requester-pays) AWS Open Data buckets and their regions: read over plain HTTPS,
# so no credentials or bucket permissions are needed. usgs-landsat stays s3:// (requester pays).
_PUBLIC_BUCKETS = {"copernicus-dem-30m": "eu-central-1", "sentinel-cogs": "us-west-2",
                   "esa-worldcover": "eu-central-1"}


def stac_url() -> str:
    return os.environ.get("STAC_URL") or DEFAULT_STAC_URL


def is_planetary(url: str | None = None) -> bool:
    return "planetarycomputer" in (url or stac_url())


def open_catalog(url: str | None = None):
    import pystac_client
    target_url = url or stac_url()
    if is_planetary(target_url):
        import planetary_computer
        return pystac_client.Client.open(target_url, modifier=planetary_computer.sign_inplace)
    return pystac_client.Client.open(target_url)


def public_href(href: str) -> str:
    """s3://<public open-data bucket>/key -> https URL; anything else unchanged."""
    if href.startswith("s3://"):
        bucket, _, key = href[5:].partition("/")
        if bucket in _PUBLIC_BUCKETS:
            return f"https://{bucket}.s3.{_PUBLIC_BUCKETS[bucket]}.amazonaws.com/{key}"
    return href


def asset_href(item, name: str) -> str:
    """Href of an asset given its Planetary Computer name, on either catalogue."""
    assets = item.assets
    key = name if name in assets else _EARTH_SEARCH_ASSETS.get(name, name)
    if key not in assets:
        raise KeyError(f"asset '{name}' not in item {item.id} (has: {sorted(assets)[:12]}…)")
    return public_href(assets[key].href)


def sentinel2_boa_offset(item) -> float:
    """DN offset to subtract before scaling Sentinel-2 L2A to reflectance.

    Processing baseline >= 04.00 (Jan 2022+) adds +1000 DN. Planetary Computer serves
    those values as-is; Earth Search has already subtracted the offset from the pixels
    when `earthsearch:boa_offset_applied` is true (checked on the same scene from both:
    Planetary Computer minus Earth Search = 1000 DN), so subtracting again would be wrong.
    """
    props = item.properties
    if props.get("earthsearch:boa_offset_applied") is True:
        return 0.0
    try:
        return 1000.0 if float(props.get("s2:processing_baseline", "05.00")) >= 4.0 else 0.0
    except (TypeError, ValueError):
        return 1000.0


def worldcover_tile_urls(bbox: tuple) -> list[str]:
    """ESA WorldCover 2021 v200 tiles (3 x 3 degrees, named by their south-west corner) from
    the AWS Open Data bucket. Same files Planetary Computer lists; used when the catalogue
    has no esa-worldcover collection (Earth Search)."""
    west, south, east, north = bbox
    urls = []
    eps = 1e-9  # a bbox edge exactly on a tile boundary must not pull in the next tile
    for lat in range(int(np.floor(south / 3) * 3), int(np.floor((north - eps) / 3) * 3) + 1, 3):
        for lon in range(int(np.floor(west / 3) * 3), int(np.floor((east - eps) / 3) * 3) + 1, 3):
            tile = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
            urls.append("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                        f"ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")
    return urls


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
            payer = os.environ.get("AWS_REQUEST_PAYER", "requester")
            with rasterio.Env(AWS_REQUEST_PAYER=payer):
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
