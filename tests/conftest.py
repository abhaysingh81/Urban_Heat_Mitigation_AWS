"""Shared fixture: a small synthetic 'real-data' city written to a temp dir, so
tests never need the network or the multi-GB real build."""

import json

import numpy as np
import pandas as pd
import pytest

import pipeline.config as cfg


def make_features(rows=24, cols=24, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = np.arange(rows * cols)
    row, col = idx % rows, idx // rows
    d = np.hypot(row - rows / 2, col - cols / 2) / rows  # 0 centre -> ~0.7 edge
    urban = np.clip(1 - d * 1.6, 0, 1)
    df = pd.DataFrame({
        "grid_id": [f"cell_{i:04d}" for i in idx], "row": row, "col": col,
        "centroid_lon": 77.0 + col * 0.005, "centroid_lat": 28.5 + row * 0.0045,
        "lst_c": 40 + 8 * urban + rng.normal(0, 0.7, len(idx)),
        "lst_std": 0.8, "n_scenes": 10.0,
        "frac_impervious": np.clip(0.2 + 0.7 * urban + rng.normal(0, .05, len(idx)), 0, 1),
        "frac_vegetation": np.clip(0.5 - 0.4 * urban + rng.normal(0, .05, len(idx)), 0, 1),
        "frac_tree": np.clip(0.2 - 0.15 * urban, 0, 1), "frac_bare_soil": 0.05, "frac_water": 0.01,
        "ndvi_mean": 0.5 - 0.3 * urban, "ndvi_std": 0.05, "ndbi_mean": -0.1 + 0.4 * urban,
        "mndwi_mean": -0.3, "building_density": 4000 * urban + 100, "building_height_mean": 3 + 12 * urban,
        "elev_mean": 220.0, "slope_mean": 1.0,
        "pop_total": 50 + 4000 * urban, "pop_density": (50 + 4000 * urban) / 0.25,
        "green_deficit": np.clip(0.5 + 0.4 * urban, 0, 1),
        "air_temp_max": 41.0, "humidity_mean": 30.0, "wind_speed_mean": 3.0,
        "solar_radiation": 25.0, "heat_index_c": 40.0, "wet_bulb_c": 22.0,
    })
    df["veg_imperv_ratio"] = df["frac_vegetation"] / (df["frac_impervious"] + 0.01)
    df["ward_id"] = [f"Z{r // 4:02d}{c // 4:02d}" for r, c in zip(row, col)]
    df["ward_name"] = [f"Zone {r // 4 + 1}-{c // 4 + 1}" for r, c in zip(row, col)]
    z = (df["lst_c"] - df["lst_c"].mean()) / df["lst_c"].std()
    df["tier"] = np.select([z > 2, z > 1, z > 0, z > -1], ["critical", "high", "moderate", "normal"], "cool")
    df["lst_mean"] = df["lst_c"]
    df["lst_max"] = df["lst_c"] + 0.8
    df["delta_above_mean"] = df["lst_mean"] - df["lst_mean"].mean()
    df["priority_score"] = 5.0
    return df


@pytest.fixture()
def fake_city(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(cfg, "SCENARIOS_DIR", tmp_path / "scenarios")
    monkeypatch.setattr(cfg, "REAL_MODEL_DIR", tmp_path / "model")
    import api.aws as aws
    monkeypatch.setattr(aws, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(aws, "REAL_MODEL_DIR", tmp_path / "model")
    for var in ("PLANS_TABLE", "REPORTS_TABLE", "DATA_BUCKET", "BEDROCK_MODEL_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(aws, "PLANS_TABLE", None)
    monkeypatch.setattr(aws, "REPORTS_TABLE", None)
    monkeypatch.setattr(aws, "DATA_BUCKET", None)

    city = "new_delhi"
    df = make_features()
    cfg.city_processed_dir(city)
    df.to_parquet(cfg.city_real_features_file(city), index=False)
    spots = [{"name": "Test Clinic", "type": "clinic", "lat": 28.55, "lon": 77.06},
             {"name": "Test Park", "type": "park", "lat": 28.52, "lon": 77.02}]
    cfg.city_cooling_spots_file(city).write_text(json.dumps(spots))
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "model_card.json").write_text(json.dumps(
        {"model_version": "test-v0", "trained_at": "2026-10-10T00:00:00+00:00"}))

    from models import risk
    risk._load.cache_clear()
    from api import data_source
    data_source._real_grid.cache_clear()
    yield city
    risk._load.cache_clear()
    data_source._real_grid.cache_clear()
