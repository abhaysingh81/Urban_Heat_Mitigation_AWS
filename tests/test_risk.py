import numpy as np
import pandas as pd
import pytest

from models.risk import alert_level, cell_components, nearest_cooling_spots, risk_today, ward_table
from pipeline.config import city_real_features_file


def test_every_cell_belongs_to_exactly_one_ward(fake_city):
    cells = cell_components(fake_city)
    assert cells["ward_id"].notna().all()
    assert cells["grid_id"].is_unique


def test_ward_ids_match_cell_table(fake_city):
    w = ward_table(fake_city)
    cells = pd.read_parquet(city_real_features_file(fake_city))
    assert set(w["ward_id"]) <= set(cells["ward_id"])


def test_scores_in_range_and_ranked(fake_city):
    w = ward_table(fake_city)
    assert w["risk_score"].between(0, 100).all()
    assert w["risk_score"].max() == 100.0
    assert list(w["rank"]) == sorted(w["rank"])
    for c in ("hazard", "exposure", "vulnerability"):
        assert w[c].between(0, 1).all()


def test_score_is_product_of_components(fake_city):
    w = ward_table(fake_city)
    raw = w["hazard"] * w["exposure"] * w["vulnerability"]  # components are rounded for output
    assert np.corrcoef(raw, w["risk_score"])[0, 1] > 0.999
    assert w["risk_score"].iloc[0] == 100.0


@pytest.mark.parametrize("t,expected", [(30, "green"), (40, "yellow"), (43, "orange"), (46, "red")])
def test_alert_levels_dry_bulb(t, expected):
    assert alert_level(t) == expected


def test_alert_uses_separate_scales_for_heat_index():
    assert alert_level(36, 33) == "yellow"      # hot and humid but not dangerous
    assert alert_level(36, 43) == "orange"      # NWS 'danger' heat index
    assert alert_level(36, 55) == "red"
    assert alert_level(33, 43) == "green"       # humid but mild day: no alarm
    assert alert_level(44, 30) == "orange"      # dry heat still counts
    assert alert_level(30, None) == "green"


def test_risk_today_scales_with_alert(fake_city):
    hot = risk_today(fake_city, 46.0)
    mild = risk_today(fake_city, 30.0, 30.0)
    assert hot["alert_level"] == "red" and mild["alert_level"] == "green"
    assert hot["top_wards"][0]["risk_today"] > mild["top_wards"][0]["risk_today"]


def test_nearest_cooling_spot_sorted(fake_city):
    s = nearest_cooling_spots(fake_city, 28.55, 77.06, 2)
    assert s[0]["name"] == "Test Clinic" and s[0]["distance_m"] <= s[1]["distance_m"]


def test_preview_city_refused():
    with pytest.raises(ValueError):
        cell_components("kochi")
