"""Neighbourhood context: NaN-aware focal means over 3x3 and 7x7 cells."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter

CONTEXT_SOURCES = ["ndvi_mean", "frac_impervious", "building_density", "pop_density"]
WINDOWS = {"ctx3": 3, "ctx7": 7}


def focal_mean(arr: np.ndarray, size: int) -> np.ndarray:
    valid = ~np.isnan(arr)
    num = uniform_filter(np.where(valid, arr, 0.0), size=size, mode="nearest")
    den = uniform_filter(valid.astype(float), size=size, mode="nearest")
    with np.errstate(all="ignore"):
        out = num / den
    out[den < 1e-6] = np.nan
    return out


def build(arrays: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    out = {}
    for name in CONTEXT_SOURCES:
        if name in arrays and not np.all(np.isnan(arrays[name])):
            for suffix, size in WINDOWS.items():
                out[f"{name}_{suffix}"] = focal_mean(arrays[name], size)
    return out
