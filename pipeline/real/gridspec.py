"""
Grid geometry shared by every real-data stage.

Reproduces the fishnet from pipeline/generate_synthetic.generate_grid
exactly (UTM, GRID_CELL_SIZE_M cells, x outer loop / y inner loop), so
`grid_id` values from the real pipeline line up with the existing
grid.geojson files. Each source raster is warped onto a "fine grid" that
is an integer subdivision of that fishnet, then block-averaged to cells.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pyproj import Transformer
from affine import Affine

from pipeline.config import CITIES, CRS_WGS84, GRID_CELL_SIZE_M, utm_epsg_for


@dataclass(frozen=True)
class GridSpec:
    city_id: str
    crs: str
    west: float   # UTM x of the grid's west edge
    south: float  # UTM y of the grid's south edge
    rows: int
    cols: int
    cell: float = float(GRID_CELL_SIZE_M)

    # ── construction ──────────────────────────────────────────
    @classmethod
    def for_city(cls, city_id: str) -> "GridSpec":
        city = CITIES[city_id]
        bbox = city["bbox"]
        crs = utm_epsg_for(*city["center"])
        to_utm = Transformer.from_crs(CRS_WGS84, crs, always_xy=True)
        west, south = to_utm.transform(bbox["west"], bbox["south"])
        east, north = to_utm.transform(bbox["east"], bbox["north"])
        cell = float(GRID_CELL_SIZE_M)
        # generate_grid loops `while x < east` / `while y < north`
        cols = int(math.ceil((east - west) / cell))
        rows = int(math.ceil((north - south) / cell))
        return cls(city_id, crs, west, south, rows, cols)

    # ── cell indexing (matches generate_grid ordering) ────────
    @property
    def n_cells(self) -> int:
        return self.rows * self.cols

    def grid_ids(self) -> list[str]:
        return [f"cell_{i:04d}" for i in range(self.n_cells)]

    def idx_to_rowcol(self, idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        idx = np.asarray(idx)
        return idx % self.rows, idx // self.rows  # row (south→north), col

    def cell_centers_utm(self) -> tuple[np.ndarray, np.ndarray]:
        idx = np.arange(self.n_cells)
        row, col = self.idx_to_rowcol(idx)
        return (self.west + (col + 0.5) * self.cell,
                self.south + (row + 0.5) * self.cell)

    def cell_centers_lonlat(self) -> tuple[np.ndarray, np.ndarray]:
        x, y = self.cell_centers_utm()
        to_wgs = Transformer.from_crs(self.crs, CRS_WGS84, always_xy=True)
        lon, lat = to_wgs.transform(x, y)
        return np.asarray(lon), np.asarray(lat)

    def bbox_wgs84(self) -> tuple[float, float, float, float]:
        b = CITIES[self.city_id]["bbox"]
        return (b["west"], b["south"], b["east"], b["north"])

    # ── fine grid (north-up raster aligned to the fishnet) ────
    def fine_shape(self, factor: int) -> tuple[int, int]:
        return self.rows * factor, self.cols * factor

    def fine_transform(self, factor: int) -> Affine:
        px = self.cell / factor
        north = self.south + self.rows * self.cell
        return Affine(px, 0, self.west, 0, -px, north)

    def fine_pixel_size(self, factor: int) -> float:
        return self.cell / factor

    # ── block reduction & array <-> per-cell vector ───────────
    def block_reduce(self, fine: np.ndarray, factor: int, how: str = "mean") -> np.ndarray:
        """Reduce a north-up fine raster to a north-up (rows, cols) array."""
        h, w = fine.shape
        assert h == self.rows * factor and w == self.cols * factor, (fine.shape, factor)
        blocks = fine.reshape(self.rows, factor, self.cols, factor)
        with np.errstate(all="ignore"):
            if how == "mean":
                return np.nanmean(blocks, axis=(1, 3))
            if how == "std":
                return np.nanstd(blocks, axis=(1, 3))
            if how == "count":
                return np.sum(~np.isnan(blocks), axis=(1, 3)).astype(float)
            if how == "sum":
                return np.nansum(blocks, axis=(1, 3))
        raise ValueError(how)

    def array_to_cells(self, arr: np.ndarray) -> np.ndarray:
        """North-up (rows, cols) array -> per-cell vector in grid_id order."""
        idx = np.arange(self.n_cells)
        row, col = self.idx_to_rowcol(idx)
        return arr[self.rows - 1 - row, col]

    def cells_to_array(self, vec: np.ndarray) -> np.ndarray:
        """Per-cell vector in grid_id order -> north-up (rows, cols) array."""
        idx = np.arange(self.n_cells)
        row, col = self.idx_to_rowcol(idx)
        out = np.full((self.rows, self.cols), np.nan)
        out[self.rows - 1 - row, col] = vec
        return out

    def lonlat_to_fine_rc(self, lon, lat, factor: int):
        to_utm = Transformer.from_crs(CRS_WGS84, self.crs, always_xy=True)
        x, y = to_utm.transform(np.asarray(lon), np.asarray(lat))
        px = self.cell / factor
        north = self.south + self.rows * self.cell
        c = np.floor((x - self.west) / px).astype(int)
        r = np.floor((north - y) / px).astype(int)
        return r, c

    def lonlat_to_cell_rc(self, lon, lat):
        """-> (north-up row, col, inside_mask) in the cell array."""
        r, c = self.lonlat_to_fine_rc(lon, lat, 1)
        ok = (r >= 0) & (r < self.rows) & (c >= 0) & (c < self.cols)
        return r, c, ok
