"""
Intervention library for the Scenario Lab and the Ward Planner.

Each intervention is described in physical units an officer can order
(trees, m² of roof, km of road, hectares, sites), with:

  capacity(cell)      how many units fit in one 500 m cell, from land cover
  cooling_range_c     (strong, weak) surface cooling in °C when the cell's
                      capacity is fully used; published-range planning values
  capex / opex        INR per unit (capital) and INR per unit per year (upkeep)
  water_l_day         litres per unit per day (Heat & Water track)
  years_to_full       years until the full effect is reached
  department          who would execute it in a municipal setting

All costs and cooling ranges are planning-grade placeholders, not quotes or
measurements. Effects from several interventions in one cell saturate
(see combine_cooling), so stacking never adds up linearly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

CELL_AREA_M2 = 500.0 * 500.0
CELL_AREA_HA = CELL_AREA_M2 / 10_000
ROOF_SHARE_OF_IMPERVIOUS = 0.40   # share of sealed surface that is roof (no footprints in v1)
ROAD_SHARE_OF_IMPERVIOUS = 0.25   # share of sealed surface that is road
ROAD_WIDTH_M = 8.0
MAX_CELL_COOLING_C = 5.0          # saturation ceiling for combined surface cooling
AIR_PER_SURFACE = {"low": 0.20, "mid": 0.30, "high": 0.45}  # assumed air/surface cooling ratio


def _col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in df:
        return df[name].fillna(default).astype(float)
    return pd.Series(default, index=df.index, dtype=float)


def _roof_m2(df):
    return CELL_AREA_M2 * _col(df, "frac_impervious").clip(0, 1) * ROOF_SHARE_OF_IMPERVIOUS


def _road_km(df):
    return CELL_AREA_M2 * _col(df, "frac_impervious").clip(0, 1) * ROAD_SHARE_OF_IMPERVIOUS / ROAD_WIDTH_M / 1000


def _open_ha(df):
    veg_not_tree = (_col(df, "frac_vegetation") - _col(df, "frac_tree")).clip(0, 1)
    return CELL_AREA_HA * (_col(df, "frac_bare_soil").clip(0, 1) + 0.25 * veg_not_tree)


@dataclass(frozen=True)
class Intervention:
    key: str
    label: str
    label_hi: str
    unit: str
    department: str
    capacity: Callable[[pd.DataFrame], pd.Series]
    ref_units: float                       # units in one cell that give the full cooling range
    cooling_range_c: tuple[float, float]   # (strong, weak) at ref_units, negative = cooler
    capex_inr: float
    opex_inr_yr: float
    water_l_day: float
    years_to_full: int
    uses_survival: bool = False
    access: bool = False                   # access point (people protected) rather than surface cooling
    lead_quarters: int = 1                 # procurement + works lead time
    kpis: tuple[str, ...] = ()
    notes: str = ""
    params: dict = field(default_factory=dict)


LIBRARY: dict[str, Intervention] = {i.key: i for i in [
    Intervention(
        "street_trees", "Street trees", "सड़क किनारे पेड़", "trees", "Horticulture / Forest",
        lambda df: (_road_km(df) * 1000 / 8).round(),          # one tree every 8 m of road edge
        1000,
        (-2.0, -0.5), capex_inr=15_000, opex_inr_yr=1_500, water_l_day=40, years_to_full=8,
        uses_survival=True, lead_quarters=2,
        kpis=("Trees alive after 1 and 3 years", "Canopy cover % (satellite, yearly)"),
        params={"species": ["native_shade", "fast_shade"]}),
    Intervention(
        "pocket_parks", "Pocket parks / urban forest", "छोटे पार्क / शहरी वन", "ha", "Horticulture / DDA",
        _open_ha, 5, (-3.0, -1.0), capex_inr=5_000_000, opex_inr_yr=300_000, water_l_day=20_000,
        years_to_full=6, uses_survival=True, lead_quarters=3,
        kpis=("Hectares handed over", "Daily visitors in summer"),
        notes="Only on bare or open green land; no demolition assumed."),
    Intervention(
        "green_roofs", "Green roofs", "हरी छतें", "m² roof", "Building dept / PWD",
        lambda df: (_roof_m2(df) * 0.30).round(),                # ~30% of roofs structurally suitable
        30000,
        (-1.0, -0.2), capex_inr=3_000, opex_inr_yr=150, water_l_day=3, years_to_full=1,
        lead_quarters=3, kpis=("m² installed", "Roof surface temperature (spot checks)"),
        params={"irrigated": [True, False]}),
    Intervention(
        "cool_roofs", "Cool (reflective) roofs", "ठंडी (परावर्तक) छतें", "m² roof", "Building dept / PWD",
        lambda df: _roof_m2(df).round(),
        60000,
        (-1.5, -0.4), capex_inr=350, opex_inr_yr=30, water_l_day=0, years_to_full=0,
        lead_quarters=1, kpis=("m² coated", "Indoor temperature in sampled homes"),
        params={"albedo": [0.55, 0.85]}),
    Intervention(
        "cool_pavement", "Cool / permeable pavement", "ठंडी सड़कें", "km road", "PWD / Roads",
        lambda df: _road_km(df).round(2),
        4,
        (-1.2, -0.3), capex_inr=6_000_000, opex_inr_yr=200_000, water_l_day=0, years_to_full=1,
        lead_quarters=2, kpis=("km resurfaced", "Road surface temperature (thermal survey)")),
    Intervention(
        "shade_structures", "Shade structures (bus stops, markets)", "छाया संरचनाएँ", "structures",
        "Municipal engineering",
        lambda df: (_col(df, "bus_stop_count") + 6 * _col(df, "frac_impervious")).clip(0, 40).round(),
        30,
        (-0.8, -0.2), capex_inr=400_000, opex_inr_yr=20_000, water_l_day=0, years_to_full=0,
        lead_quarters=1, kpis=("Structures built", "Use at peak hours")),
    Intervention(
        "water_bodies", "Restore ponds / water bodies", "तालाब पुनर्जीवन", "ha", "Water board / Irrigation",
        lambda df: (CELL_AREA_HA * _col(df, "frac_water").clip(0, 1)
                    + 0.5 * (_col(df, "frac_bare_soil") > 0.05)).round(2),
        3,
        (-2.5, -0.5), capex_inr=10_000_000, opex_inr_yr=200_000, water_l_day=30_000, years_to_full=2,
        lead_quarters=3, kpis=("Hectares restored", "Water level in May"),
        notes="Desilting, sewage diversion and restoring existing or degraded water bodies."),
    Intervention(
        "misting_points", "Misting points", "मिस्टिंग पॉइंट", "points", "Municipal engineering",
        lambda df: (2 + 6 * _col(df, "frac_impervious")).round(),
        10,
        (-0.2, -0.05), capex_inr=300_000, opex_inr_yr=60_000, water_l_day=1_500, years_to_full=0,
        lead_quarters=1, kpis=("Points working on alert days",),
        notes="Cools the air locally at markets and stops; small effect on cell surface temperature."),
    Intervention(
        "water_atms", "Drinking-water points (water ATMs)", "पीने के पानी के पॉइंट", "points",
        "Water board", lambda df: pd.Series(2.0, index=df.index),
        1,
        (0.0, 0.0), capex_inr=500_000, opex_inr_yr=120_000, water_l_day=2_000, years_to_full=0,
        access=True, lead_quarters=1, kpis=("Points working on alert days", "Litres dispensed")),
    Intervention(
        "cooling_centres", "Cooling centres", "कूलिंग सेंटर", "centres", "Health / Disaster mgmt",
        lambda df: pd.Series(1.0, index=df.index),
        1,
        (0.0, 0.0), capex_inr=2_500_000, opex_inr_yr=600_000, water_l_day=500, years_to_full=0,
        access=True, lead_quarters=1, kpis=("Centres open on alert days", "Visitors per alert day")),
]}

COOLING_KEYS = [k for k, v in LIBRARY.items() if not v.access]
ACCESS_KEYS = [k for k, v in LIBRARY.items() if v.access]
ACCESS_RADIUS_M = 1000  # an access point serves its own cell and nearby cells within ~1 km


def cooling_for_units(key: str, units, survival: float = 0.7, params: dict | None = None,
                      year: float | None = None):
    """(low, mid, high) surface cooling in °C (negative) from `units` of one intervention
    per cell. Effect is linear in units up to the reference density (ref_units per cell);
    capacity limits how many units fit, it does not change the effect per unit."""
    iv = LIBRARY[key]
    params = params or {}
    units = np.asarray(units, dtype=float)
    share = (units / iv.ref_units).clip(0, 1)
    scale = share * (survival if iv.uses_survival else 1.0)
    strong, weak = iv.cooling_range_c
    if key == "cool_roofs" and "albedo" in params:      # effect grows with albedo above a 0.2 base roof
        scale = scale * np.clip((float(params["albedo"]) - 0.2) / (0.75 - 0.2), 0, 1.3)
    if key == "green_roofs" and params.get("irrigated") is False:
        scale = scale * 0.6
    years = iv.years_to_full
    if key == "street_trees" and params.get("species") == "fast_shade":
        years, strong = 5, strong * 1.1
    if year is not None and years > 0:
        scale = scale * min(1.0, year / years)
    low, high = weak * scale, strong * scale
    return low, (low + high) / 2.0, high


def water_l_day(key: str, units, params: dict | None = None):
    iv = LIBRARY[key]
    params = params or {}
    w = iv.water_l_day
    if key == "green_roofs" and params.get("irrigated") is False:
        w = 0.5
    if key == "street_trees" and params.get("species") == "fast_shade":
        w = w * 1.5
    return np.asarray(units, dtype=float) * w


def combine_cooling(total):
    """Saturating combination: summed independent effects S (negative) become
    -C·(1 − e^(S/C)), so two 3 °C effects give ~3.4 °C, not 6 °C."""
    s = np.asarray(total, dtype=float)
    return -MAX_CELL_COOLING_C * (1 - np.exp(s / MAX_CELL_COOLING_C))


def library_json() -> list[dict]:
    out = []
    for iv in LIBRARY.values():
        out.append({
            "key": iv.key, "label": iv.label, "label_hi": iv.label_hi, "unit": iv.unit,
            "department": iv.department, "cooling_range_c": list(iv.cooling_range_c),
            "capex_inr_per_unit": iv.capex_inr, "opex_inr_per_unit_yr": iv.opex_inr_yr,
            "water_l_per_unit_day": iv.water_l_day, "years_to_full": iv.years_to_full,
            "uses_survival": iv.uses_survival, "access": iv.access, "lead_quarters": iv.lead_quarters,
            "kpis": list(iv.kpis), "notes": iv.notes, "params": iv.params,
        })
    return out
