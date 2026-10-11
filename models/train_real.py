"""
Train the real-data LST model (HeatRelief tier).

    python -m models.train_real
    python -m models.train_real --allow-weak   # ship even if the quality gate fails

Target: multi-scene Landsat LST composite (lst_c). Estimators: XGBoost point
model + q10/q90 quantile models. Evaluation (written to model_card.json):
  * leave-one-city-out (can the model score a city it has never seen?)
  * spatial block CV, 5 km blocks (adjacent cells are strongly correlated)
  * baselines: global mean, linear on NDVI + impervious fraction
Two feature sets are compared (with / without city-level weather); the one
with the lower leave-city-out RMSE is shipped, and both are reported.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import GroupKFold

from pipeline.config import (
    PROCESSED_DIR, REAL_CITIES, REAL_MODEL_DIR, city_data_card_file, city_processed_dir,
    city_real_features_file,
)
from pipeline.real.s3_sync import sync_s3_down, sync_s3_up, upload_file_to_s3

TARGET = "lst_c"
BLOCK_CELLS = 10  # 5 km at 500 m cells
MIN_LOCO_R = 0.3  # quality gate: Pearson r on every held-out city

SPATIAL_FEATURES = [
    "frac_impervious", "frac_tree", "frac_vegetation", "frac_bare_soil", "frac_water",
    "ndvi_mean", "ndvi_std", "ndbi_mean", "mndwi_mean",
    "building_density", "building_height_mean", "elev_mean", "slope_mean",
    "pop_density", "green_deficit", "veg_imperv_ratio",
    "ndvi_mean_ctx3", "ndvi_mean_ctx7", "frac_impervious_ctx3", "frac_impervious_ctx7",
    "building_density_ctx3", "building_density_ctx7", "pop_density_ctx3", "pop_density_ctx7",
]
WEATHER_FEATURES = ["air_temp_max", "humidity_mean", "wind_speed_mean",
                    "solar_radiation", "heat_index_c", "wet_bulb_c"]

PARAMS = dict(n_estimators=400, max_depth=5, learning_rate=0.05, subsample=0.8,
              colsample_bytree=0.8, min_child_weight=5, reg_lambda=5.0,
              tree_method="hist", n_jobs=4, random_state=42)


# ── data ─────────────────────────────────────────────────────
def load_data() -> pd.DataFrame:
    frames = []
    for cid in REAL_CITIES:
        f = city_real_features_file(cid)
        if not f.exists():
            print(f"  [skip] {cid}: no features_real.parquet (run pipeline.real.build_dataset)")
            continue
        d = pd.read_parquet(f)
        d["city_id"] = cid
        frames.append(d)
    if not frames:
        raise SystemExit("No real-data feature files found. Run "
                         "`python -m pipeline.real.build_dataset` first.")
    df = pd.concat(frames, ignore_index=True)
    df["block"] = df["city_id"] + "_" + (df["row"] // BLOCK_CELLS).astype(str) \
        + "_" + (df["col"] // BLOCK_CELLS).astype(str)
    return df


def usable(df: pd.DataFrame, cols: list[str]) -> list[str]:
    """Keep features that exist and carry information (not all-NaN / constant)."""
    keep = []
    for c in cols:
        if c in df.columns and df[c].notna().mean() > 0.5 and df[c].nunique() > 1:
            keep.append(c)
    return keep


# ── metrics ──────────────────────────────────────────────────
def metrics(y, p) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    ok = ~(np.isnan(y) | np.isnan(p))
    y, p = y[ok], p[ok]
    if len(y) < 3 or np.std(p) < 1e-9:
        return {"n": int(len(y)), "r2": None, "rmse": None, "mae": None, "pearson_r": None, "bias": None}
    ss_res, ss_tot = np.sum((y - p) ** 2), np.sum((y - y.mean()) ** 2)
    return {"n": int(len(y)), "r2": round(float(1 - ss_res / ss_tot), 3),
            "rmse": round(float(np.sqrt(np.mean((y - p) ** 2))), 3),
            "mae": round(float(np.mean(np.abs(y - p))), 3),
            "pearson_r": round(float(np.corrcoef(y, p)[0, 1]), 3),
            # mean(pred - observed): a city-level offset shows up here, separate from pattern skill (r)
            "bias": round(float(np.mean(p - y)), 3)}


def per_city(df, y, p) -> dict:
    out = {}
    for cid in df["city_id"].unique():
        m = (df["city_id"] == cid).to_numpy()
        out[cid] = metrics(y[m], p[m])
    return out


def mean_rmse(pc: dict) -> float:
    v = [m["rmse"] for m in pc.values() if m["rmse"] is not None]
    return float(np.mean(v)) if v else float("inf")


# ── models ───────────────────────────────────────────────────
def fit_point(X, y):
    return xgb.XGBRegressor(**PARAMS).fit(X, y)


def fit_quantile(X, y, alpha):
    return xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=alpha,
                            **PARAMS).fit(X, y)


def loco(df, feats):
    """Leave-one-city-out predictions + baselines."""
    X, y = df[feats], df[TARGET].to_numpy()
    pred = np.full(len(df), np.nan)
    base_mean = np.full(len(df), np.nan)
    base_lin = np.full(len(df), np.nan)
    lin_feats = [f for f in ("ndvi_mean", "frac_impervious") if f in feats]
    cities = df["city_id"].unique()
    if len(cities) < 2:
        return pred, base_mean, base_lin
    for cid in cities:
        te = (df["city_id"] == cid).to_numpy()
        tr = ~te
        pred[te] = fit_point(X[tr], y[tr]).predict(X[te])
        base_mean[te] = y[tr].mean()
        if lin_feats:
            Xl = df[lin_feats].fillna(df[lin_feats].median())
            base_lin[te] = LinearRegression().fit(Xl[tr], y[tr]).predict(Xl[te])
    return pred, base_mean, base_lin


def block_cv(df, feats, n_splits=5):
    X, y = df[feats], df[TARGET].to_numpy()
    pred = np.full(len(df), np.nan)
    q10 = np.full(len(df), np.nan)
    q90 = np.full(len(df), np.nan)
    gkf = GroupKFold(n_splits=min(n_splits, df["block"].nunique()))
    for tr, te in gkf.split(X, y, groups=df["block"]):
        pred[te] = fit_point(X.iloc[tr], y[tr]).predict(X.iloc[te])
        q10[te] = fit_quantile(X.iloc[tr], y[tr], 0.1).predict(X.iloc[te])
        q90[te] = fit_quantile(X.iloc[tr], y[tr], 0.9).predict(X.iloc[te])
    return pred, q10, q90


def run(allow_weak: bool = False, bucket: str | None = None, run_id: str | None = None):
    bucket = bucket or os.environ.get("S3_PIPELINE_BUCKET")
    run_id = run_id or os.environ.get("RUN_ID", datetime.now(timezone.utc).strftime("real-v1-%Y%m%d"))

    if bucket:
        print(f"  [s3] syncing processed city features from s3://{bucket}/runs/{run_id}/processed/ -> {PROCESSED_DIR}")
        # strict: never train silently on whatever data happens to be baked into the image
        if not sync_s3_down(bucket, f"runs/{run_id}/processed", PROCESSED_DIR, strict=True):
            raise SystemExit(f"No processed datasets found under s3://{bucket}/runs/{run_id}/processed/")

    print("Loading real-data features…")
    df = load_data()
    df = df[df[TARGET].notna()].reset_index(drop=True)
    print(f"  {len(df)} cells with a real LST target across {df['city_id'].nunique()} cities")

    spatial = usable(df, SPATIAL_FEATURES)
    weather = usable(df, WEATHER_FEATURES)
    variants = {"spatial": spatial, "spatial+weather": spatial + weather}

    report, best_name, best_pc = {}, None, None
    for name, feats in variants.items():
        if name == "spatial+weather" and not weather:
            continue
        print(f"\n[{name}] {len(feats)} features")
        lp, bm, bl = loco(df, feats)
        y = df[TARGET].to_numpy()
        pc = per_city(df, y, lp)
        report[name] = {"features": feats, "leave_one_city_out": pc,
                        "baseline_global_mean": per_city(df, y, bm),
                        "baseline_linear_ndvi_impervious": per_city(df, y, bl)}
        for cid, m in pc.items():
            print(f"    LOCO {cid:10s} r={m['pearson_r']}  rmse={m['rmse']}  r2={m['r2']}")
        if best_pc is None or mean_rmse(pc) < mean_rmse(best_pc):
            best_name, best_pc = name, pc

    feats = variants[best_name]
    print(f"\nShipping variant: {best_name}")
    bp, q10, q90 = block_cv(df, feats)
    y = df[TARGET].to_numpy()
    block = per_city(df, y, bp)
    cover = {cid: round(float(np.mean(
        (y[m] >= q10[m]) & (y[m] <= q90[m]))), 3)
        for cid in df["city_id"].unique()
        for m in [(df["city_id"] == cid).to_numpy()]}
    for cid, m in block.items():
        print(f"    block-CV {cid:10s} r={m['pearson_r']}  rmse={m['rmse']}  "
              f"q10-q90 coverage={cover[cid]}")

    # Conformalised quantile regression: widen the band by the 80th percentile of how far
    # held-out cells fall outside it, so the reported band reaches its nominal coverage.
    score = np.maximum(q10 - y, y - q90)
    qhat = float(max(np.nanquantile(score, 0.8), 0.0))
    cover_cal = {cid: round(float(np.mean(
        (y[m] >= q10[m] - qhat) & (y[m] <= q90[m] + qhat))), 3)
        for cid in df["city_id"].unique()
        for m in [(df["city_id"] == cid).to_numpy()]}
    print(f"    band widened by {qhat:.2f} °C -> calibrated coverage {cover_cal}")

    # gate on leave-city-out correlation (only meaningful with ≥2 cities)
    weak = [c for c, m in best_pc.items()
            if m["pearson_r"] is None or m["pearson_r"] < MIN_LOCO_R]
    gate_ok = not weak and df["city_id"].nunique() >= 2

    # final models on all data
    print("\nFitting final models…")
    X = df[feats]
    point, mq10, mq90 = fit_point(X, y), fit_quantile(X, y, 0.1), fit_quantile(X, y, 0.9)

    REAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    point.save_model(str(REAL_MODEL_DIR / "lst_point.json"))
    mq10.save_model(str(REAL_MODEL_DIR / "lst_q10.json"))
    mq90.save_model(str(REAL_MODEL_DIR / "lst_q90.json"))
    (REAL_MODEL_DIR / "feature_names.json").write_text(json.dumps(feats))

    # SHAP (model explanation, NOT causal effect)
    top = []
    try:
        import shap
        sample = X.sample(min(5000, len(X)), random_state=0)
        sv = shap.TreeExplainer(point).shap_values(sample)
        imp = np.abs(sv).mean(axis=0)
        top = sorted(({"feature": f, "mean_abs_shap": round(float(v), 4)}
                      for f, v in zip(feats, imp)), key=lambda d: -d["mean_abs_shap"])
        pd.DataFrame(sv, columns=feats).assign(
            base_value=float(np.ravel(shap.TreeExplainer(point).expected_value)[0]),
            grid_id=df.loc[sample.index, "grid_id"].values,
            city_id=df.loc[sample.index, "city_id"].values,
        ).to_parquet(REAL_MODEL_DIR / "shap_values.parquet", index=False)
        (REAL_MODEL_DIR / "feature_importance.json").write_text(json.dumps(top, indent=2))
    except Exception as e:
        print(f"  [warn] SHAP skipped: {e}")

    # per-city predictions for the API (final model; in-sample, labelled as such)
    for cid in df["city_id"].unique():
        full = pd.read_parquet(city_real_features_file(cid))
        Xf = full.reindex(columns=feats)
        pd.DataFrame({
            "grid_id": full["grid_id"],
            "lst_pred": point.predict(Xf), "lst_q10": mq10.predict(Xf) - qhat,
            "lst_q90": mq90.predict(Xf) + qhat,
        }).round(2).to_parquet(city_processed_dir(cid) / "predictions_real.parquet", index=False)

    card = {
        "model_version": run_id,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "target": "Landsat 8/9 C2 L2 ST_B10 median composite (°C), Apr–Jun 2024–2026",
        "cities": sorted(df["city_id"].unique().tolist()),
        "n_cells": int(len(df)),
        "shipped_variant": best_name,
        "features": feats,
        "evaluation": report,
        "block_cv_5km": {"per_city": block, "q10_q90_coverage": cover,
                         "calibrated_coverage": cover_cal, "band_widen_c": round(qhat, 2),
                         "nominal_coverage": 0.8},
        "top_drivers_shap": top[:10],
        "quality_gate": {"min_pearson_r_leave_city_out": MIN_LOCO_R,
                         "passed": gate_ok, "failing_cities": weak},
        "limitations": [
            "Land surface temperature is not air temperature or heat stress.",
            "Model learns correlations across cells; SHAP explains the model, not causal effects.",
            "Weather features are city-level (constant within a city) and help between-city transfer only.",
            "Cells outside the best Landsat tile footprint have no target and are excluded from training.",
            "Spatial pattern transfers across cities far better than absolute level: a city-level offset (see bias and R²) remains for cities the model has not seen.",
            "With four training cities the model cannot learn a reliable weather-to-level relationship; weather features are included only if they lower leave-city-out RMSE.",
            "The q10–q90 band is conformally widened; calibrated coverage is measured on the same block-CV folds used to widen it, so it is optimistic.",
            "Cooling-scenario results are estimates clamped to published ranges, not guarantees.",
        ],
        "data_cards": {c: json.loads(city_data_card_file(c).read_text())
                       for c in df["city_id"].unique() if city_data_card_file(c).exists()},
    }
    (REAL_MODEL_DIR / "model_card.json").write_text(json.dumps(card, indent=2, default=str))
    print(f"\nWrote artifacts to {REAL_MODEL_DIR}")

    # Upload models, predictions, and manifest to S3 if pipeline bucket is configured
    if bucket:
        print(f"  [s3] uploading model artifacts to s3://{bucket}/runs/{run_id}/models/")
        sync_s3_up(REAL_MODEL_DIR, bucket, f"runs/{run_id}/models", strict=True)
        for cid in df["city_id"].unique():
            pred_file = city_processed_dir(cid) / "predictions_real.parquet"
            if pred_file.exists():
                upload_file_to_s3(pred_file, bucket, f"runs/{run_id}/processed/{cid}/predictions_real.parquet", strict=True)

        manifest = {
            "run_id": run_id,
            "model_version": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cities": sorted(df["city_id"].unique().tolist()),
            "quality_gate_passed": gate_ok,
            "failing_cities": weak,
            "shipped_variant": best_name,
            "models_s3_path": f"s3://{bucket}/runs/{run_id}/models/",
            "processed_s3_path": f"s3://{bucket}/runs/{run_id}/processed/",
        }
        manifest_file = REAL_MODEL_DIR / "manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2))
        upload_file_to_s3(manifest_file, bucket, f"runs/{run_id}/manifest.json", strict=True)
        print(f"  [s3] wrote manifest to s3://{bucket}/runs/{run_id}/manifest.json")

    if not gate_ok and not allow_weak:
        raise SystemExit(
            f"QUALITY GATE FAILED: leave-city-out Pearson r < {MIN_LOCO_R} for {weak or 'n/a (need ≥2 cities)'}. "
            "Artifacts were written and flagged passed=false; rerun with --allow-weak to accept.")
    return card


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-weak", action="store_true")
    ap.add_argument("--bucket", default="", help="S3 pipeline bucket name (or S3_PIPELINE_BUCKET env)")
    ap.add_argument("--run-id", default="", help="Pipeline run identifier (or RUN_ID env)")
    args = ap.parse_args()
    run(allow_weak=args.allow_weak, bucket=args.bucket or None, run_id=args.run_id or None)
