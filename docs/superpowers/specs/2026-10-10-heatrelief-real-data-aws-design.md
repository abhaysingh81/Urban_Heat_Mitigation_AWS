# HeatRelief: real-data model + decision system on AWS — design spec

Date: 2026-10-10 · Status: draft for review · Scope: Option A (Delhi + Mumbai, Jaipur, Bengaluru)

## 1. Intent

Turn the current heat dashboard into a heat decision system that runs on AWS and rests on **real satellite data**, for the Environmental Hacks submission (closes Oct 11, hour unpublished).

Success means all of the following:
- The model is trained on real Landsat land surface temperature (LST), not a hand-written formula, and reports honest per-city metrics with uncertainty bands.
- An officer can open Delhi, see ward risk (hazard × exposure × vulnerability), set a budget, get a costed plan, and download a Hindi + English brief.
- A scheduled AWS pipeline refreshes today's risk and sends an alert.
- One `sam deploy` stands up the AWS side, and the AWS console is visible in the demo video.

Stated by the user: pick Option A (Delhi + 3 contrasting cities); use the blueprint's five pillars and Must items.
Assumptions (correct me): ~24 h of build time; one developer; AWS account with Bedrock model access obtainable today; Planetary Computer reachable from the build machine (it timed out earlier in this session, so this is a risk).

## 2. Problems this fixes (found in the repo)

| # | Finding | Evidence |
|---|---|---|
| 1 | Training data is synthetic; target `lst_mean` is a formula of the features | `pipeline/generate_synthetic.py` (`lst_mean = base_temp + 12·impervious − 8·ndvi …`) |
| 2 | Synthetic LST disagrees with real Landsat | `data/processed/*/landsat_validation_meta.json`: Delhi r = −0.47, RMSE 6.43 °C; r ≤ 0.03 in all 7 cities checked |
| 3 | Weather features are per-city constants | `air_temp_max = baseline + 5·urban_intensity + noise` |
| 4 | Real per-cell LST exists but is only used for validation | `landsat_validation.geojson` → `lst_satellite_c` (single scene) |
| 5 | No ward, population, humidity or vulnerability data anywhere | grep over `pipeline/ models/ api/ frontend/src` |
| 6 | No AWS usage; flat files in git | whole repo |

## 3. Scope

**In (Tier 1+2, real data):** `new_delhi` (hero), `mumbai` (hot-humid, coastal), `jaipur` (hot-dry), `bengaluru` (semi-arid, elevated).
**Preview (unchanged):** the other 16 cities keep their existing synthetic features, shown with a visible "synthetic preview" badge, and are excluded from training, risk, optimizer and agent.
**Out:** SageMaker, Cognito, native app, retraining automation, polishing preview cities, Amazon Location Service (straight-line distance used instead), water-link extension.

## 4. Data design

Everything comes from free sources through the Planetary Computer STAC (already used in `pipeline/fetch_real_lst.py`) unless noted. All outputs are aggregated to the existing 500 m fishnet (`data/processed/<city>/grid.geojson`), so grid IDs stay stable.

| Role | Source | Aggregation to cell |
|---|---|---|
| **Target** `lst_c` | Landsat 8/9 C2 L2 `ST_B10`, ≥6 clear scenes (cloud <20 %), Apr–Jun 2024–2026, per-pixel median | zonal mean; also `lst_std`, `n_scenes` |
| NDVI, NDBI, MNDWI | Sentinel-2 L2A median of the same dates | zonal mean/std |
| Land cover | ESA WorldCover 2021 (classes: built-up 50, tree 10, grass/crop/shrub 20/30/40, bare 60, water 80) | class fractions |
| Buildings, roads | OSM via existing `05_extract_osm.py`; building height from OSM `height`/`levels`, imputed by city median where missing | density, mean height, road length |
| Terrain | Copernicus DEM 30 m (`cop-dem-glo-30`) | `elev_mean`, `slope_mean` |
| Weather | Open-Meteo archive API, city centroid, **for each composite scene date**: tmax, mean relative humidity, wind, shortwave radiation; derived heat index and wet-bulb (Stull) | city-level means (constant within a city; helps between-city transfer only, which the model card states) |
| Population | WorldPop India constrained 100 m 2020 | sum per cell → `pop_density` |
| Age mix (stretch) | WorldPop age-sex bands 0–4 and 65+ | `frac_elderly`, `frac_children`; if unavailable, vulnerability falls back to density only and the model card says so |
| Amenities | OSM hospitals, shelters, bus stops, water points, parks | points → cooling-spot table |
| Wards | OSM `admin_level` ward polygons per city; **fallback** 2 km hexagonal "zones" named `Zone-N` if ward polygons are missing or inconsistent | polygon → list of `grid_id` |

**Context features** (largest expected gain on real LST): for NDVI, impervious fraction, building density and `pop_density`, add focal means over 3×3 (1.5 km) and 7×7 (3.5 km) cells computed on the grid's 2-D layout (needs `row`, `col` in the grid, added by the grid step).

**Output per city:** `data/processed/<city>/features_real.parquet` (one row per cell: `grid_id, row, col, lon, lat, lst_c, lst_std, n_scenes, <features>, ward_id`), plus `wards.geojson`, `cooling_spots.json`, `data_card.json` (source, date range, scene IDs, licence). Large rasters are cached under `data/raw/` (git-ignored); processed parquet is uploaded to S3.

## 5. Model design

- **Module:** `models/train_real.py` (new). The old `models/train_hotspot.py` stays for preview cities.
- **Target:** `lst_c` (Landsat composite, °C). **Features:** the table above, with raw coordinates excluded (existing rule) and weather features included.
- **Estimators:** XGBoost point model (`reg:squarederror`) plus two quantile models (`reg:quantileerror`, α = 0.1 and 0.9) for an uncertainty band. Stays under the existing `xgboost<3.0` pin; quantile objective is available in 2.x.
- **Baselines (required for the model card):** per-city mean; linear regression on NDVI + impervious fraction.
- **Evaluation:** (a) leave-one-city-out over the 4 cities; (b) within-city spatial block CV with 5 km blocks, because adjacent cells are strongly autocorrelated. Report R², RMSE, MAE, Pearson r per city and per scheme, plus quantile-band coverage.
- **Expectation:** leave-city-out R² around 0.4–0.65. The old 0.7–0.91 was circular. Positive correlation with real LST is the claim.
- **Artifacts:** `models/artifacts/real/{lst_point.json, lst_q10.json, lst_q90.json, feature_names.json, model_card.json, shap_values.parquet}`; `model_card.json` carries version, data date, metrics and limitations and is served by the API.
- **Hotspot tiers** for real cities use **observed** Landsat `lst_c` relative to the city distribution (existing `HOTSPOT_TIERS` logic); the model prediction drives scenarios only.
- **Honesty rules:** every scenario output is a range labelled "estimate"; SHAP is described as explaining the model, not the world.

## 6. Decision-layer design

### 6.1 Risk engine (`models/risk.py`, new)
Per ward: hazard H = rank-normalised blend of mean observed LST and heat index; exposure E = rank-normalised population (day/night switch is an input that reweights the exposure term; v1 uses a single population layer and the switch is shown only if data allows); vulnerability V = rank-normalised combination of density, elderly+child fraction (if available), and green deficit. `risk = H·E·V`, rescaled 0–100, with the three components returned so the UI can explain a ranking.

### 6.2 Scenario engine changes (`models/simulate.py`, `pipeline/config.py`)
- Add intervention types: `shade_structures`, `cool_pavement` (feature-perturbation like the existing ones) and `cooling_centre` (no LST effect, adds protected people within 500 m walking).
- Each intervention gains `cooling_range_c` (low, high) from published studies, `survival_rate` (trees only, user-adjustable), `years_to_full_effect`, and `cost_inr_per_unit`. Model-predicted delta is clamped into the published range, and output is `{low, mid, high}`.
- Costs move from `cost_per_km2_million` to INR per cell.

### 6.3 Optimizer (`models/optimizer.py`, new)
Input: city, budget (₹), allowed interventions, equity weight λ ∈ [0, 1], tree survival. Algorithm: build candidate (cell, intervention) options; score = `Δ°C_mid × people_in_cell × (1 + λ·V) / cost`; greedy fill until the budget is exhausted (never exceeded); return the plan, per-ward totals, and an **impact card** (people protected, ₹ per person, °C reduction as low/mid/high, assumptions) and a **timeline** by year. Cooling-centre placement picks cells maximising vulnerable people within 500 m. Deterministic; unit-tested.

### 6.4 Heat Officer agent (`agent/heat_officer.py`, new)
Strands Agents SDK on Bedrock. Tools: `get_ward_risk`, `run_optimizer`, `get_forecast`, `get_cooling_spots`, `search_guidance` (keyword search over a small local set of NDMA/Delhi heat-action-plan excerpts, no vector store, so no standing cost). Output: ward brief in Hindi and English. A **numbers check** rejects any number in the output that does not appear in tool results (regenerate once, then fall back to a deterministic template brief). Bedrock Guardrails ID from env. PDF via `reportlab` with Noto Sans Devanagari, stored in S3, returned as a presigned URL. `BEDROCK_MODEL_ID` is an env var; the model must be enabled in the account's region first.

### 6.5 Early-warning pipeline (`lambdas/`, `infra/`)
EventBridge Scheduler (daily) → Lambda `refresh_forecast` (Open-Meteo forecast for each Tier 1+2 city; scales ward hazard by forecast tmax/heat-index anomaly against composite-date conditions; writes `risk_today.json` to S3) → if any ward exceeds the alert threshold, publish to SNS (email) and call Polly (Hindi voice) for an advisory MP3 in S3 → CloudWatch metrics (alerts fired, run duration, failures). If the forecast call fails, keep the last good `risk_today.json` and flag `stale: true`.

### 6.6 API (`api/`)
New routers (all take `?city=` like existing ones; real-data routes return 404 with a clear message for preview cities):
- `GET /api/v1/risk/wards`, `GET /api/v1/risk/today`
- `POST /api/v1/plans/optimize`, `GET/PUT /api/v1/plans/{id}` (DynamoDB; PUT sets `approved`/`implemented` with an audit entry)
- `POST /api/v1/brief` → agent brief + PDF URL; `GET /api/v1/model-card`
- `GET /api/v1/cooling-spots`, `POST /api/v1/reports` (anonymous, location rounded to cell; photo via presigned S3 upload)
Every response carries `model_version` and `data_date`. API Gateway throttling on all routes.

### 6.7 Frontend (`frontend/src/`)
- New pages: `RiskView` (ward map, component breakdown, day/night toggle if available), `PlanView` (budget slider, equity toggle, plan table, impact card, timeline, "Generate brief"), `ModelCardView`, `CitizenView` (mobile, today's risk in plain words, nearest cooling spot by straight-line distance, audio advisory, report button).
- `i18n.js` with Hindi/English strings; language switch in the header.
- `MapView`/`ScenarioView`: show "observed" vs "synthetic preview" badge; show scenario ranges; drop unexplained jargon (SHAP/LST get plain-word labels, existing explainer modal kept).
- Nav and routes updated in `App.jsx`.

### 6.8 AWS deployment (`infra/template.yaml`, SAM)
S3 (data/artifacts/PDFs/reports), DynamoDB (`plans`, `reports`), Lambda container image for the FastAPI app via Mangum (xgboost + pandas exceed the zip limit; warm before demo), refresh and brief Lambdas, EventBridge schedule, SNS topic, CloudFront + S3 for the frontend, API Gateway with throttling, CloudWatch dashboard and alarms, AWS Budgets alarm, least-privilege IAM per function, secrets in SSM Parameter Store. One command: `sam build && sam deploy --guided`. Render and Vercel are replaced for the submission build; CORS origins become env-configured.

## 7. Phases and time budget (one developer, ≈24 h)

| Phase | Work | Est. | Cut if late |
|---|---|---|---|
| P0 | README "existing vs built in event", licence/credit audit file, secrets and `.gitignore` check | 1 h | no |
| P1 | Real-data pipeline for 4 cities (Landsat composite, S2, WorldCover, OSM, DEM, weather, WorldPop, wards, context features) | 6 h | drop age mix, then Bengaluru |
| P2 | `train_real.py`, baselines, CV, quantiles, model card | 2 h | no |
| P3 | `risk.py`, `optimizer.py`, scenario changes, new API routers, tests | 4 h | day/night switch |
| P4 | Strands agent, numbers check, PDF, guardrails, fallback brief | 3 h | PDF → plain text |
| P5 | SAM template, DynamoDB, S3 upload of data, forecast Lambda, SNS, Polly, CloudWatch | 4 h | Polly |
| P6 | Frontend Risk/Plan/ModelCard pages, i18n, badges | 3 h | ModelCard → static markdown |
| P7 | CitizenView + reports | 2 h | **first to cut** |
| P8 | Golden-path smoke script, warm-up, demo video, writeup, blog | 3 h | no |

This is tight; P7 and the stretch items are the pressure valves.

## 8. Testing

- `tests/test_optimizer.py`: total cost ≤ budget; λ=1 allocates at least as much to high-V wards as λ=0; deterministic.
- `tests/test_risk.py`: monotonic in each component; ward IDs map to existing `grid_id`s; every cell belongs to exactly one ward.
- `tests/test_agent_numbers.py`: numbers check rejects an injected invented number.
- `tests/test_api.py`: FastAPI TestClient smoke for every new route, preview-city 404, response carries `model_version`.
- `scripts/smoke_golden_path.py`: refresh → risk → optimize → brief → alert → citizen payload → report round-trip; doubles as demo rehearsal.
- Model gate: `train_real.py` fails loudly if Pearson r on any held-out city is below 0.3, instead of silently shipping.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Planetary Computer slow or unreachable | cache rasters under `data/raw/`; run P1 first; start with Delhi |
| Real-LST model scores lower than synthetic | expected; report honestly, show baselines |
| Bedrock Hindi quality or model access delay | enable model access now; template-brief fallback |
| Lambda container cold start | warm before recording; keep API handlers light |
| Ward polygons poor in OSM | hex-zone fallback, labelled |
| Time | cut order in §7 |
| Repo history looks re-initialised (2 commits, both Oct 10) | keep older history if the GitHub repo has it; README states what existed |

## 10. Change list

### New files
- `pipeline/real/__init__.py`, `stac.py`, `landsat_composite.py`, `sentinel2_features.py`, `landcover.py`, `osm_features.py`, `terrain.py`, `weather.py`, `population.py`, `wards.py`, `context_features.py`, `build_dataset.py`
- `models/train_real.py`, `models/risk.py`, `models/optimizer.py`
- `agent/__init__.py`, `agent/heat_officer.py`, `agent/numbers_check.py`, `agent/brief_pdf.py`, `agent/guidance/*.md`
- `lambdas/refresh_forecast/app.py`, `lambdas/brief/app.py`
- `api/routers/risk.py`, `plans.py`, `brief.py`, `reports.py`, `meta.py`; `api/aws.py` (boto3 clients, env config); `api/lambda_handler.py` (Mangum)
- `infra/template.yaml`, `infra/Dockerfile`, `samconfig.toml`
- `frontend/src/pages/RiskView.jsx`, `PlanView.jsx`, `ModelCardView.jsx`, `CitizenView.jsx` (+ `.css`), `frontend/src/i18n.js`
- `tests/` (files in §8), `scripts/smoke_golden_path.py`
- `docs/DATA_CARD.md`, `docs/LICENSES.md`, `docs/superpowers/specs/…` (this file)

### Modified files
- `pipeline/config.py`: `TIERS` (real vs preview cities), new interventions and cost/range fields, real-data paths
- `pipeline/fetch_real_lst.py`: reuse STAC helper; multi-scene composite replaces single scene
- `pipeline/06_build_grid.py` / grid generation: add `row`, `col`
- `models/simulate.py`: ranges, survival, time-to-impact, new interventions; real-model loading by city tier
- `models/explain.py`: load per-model SHAP for the real model
- `api/main.py`: new routers, env-driven CORS, version/data-date middleware; `/overview` uses observed LST for real cities
- `api/schemas.py`: new request/response models, `{low, mid, high}` ranges
- `api/routers/scenarios.py`, `hotspots.py`, `grid.py`, `drivers.py`: tier-aware data source
- `frontend/src/App.jsx` (routes, nav, language switch), `api.js`, `MapView.jsx`, `ScenarioView.jsx`, `DriversView.jsx`
- `requirements.txt` (+ `scipy`, `boto3`, `mangum`, `reportlab`, `strands-agents`, `requests`), `requirements-satellite.txt` (+ `osmnx`, `stackstac` or `rioxarray`, `odc-stac` as needed)
- `README.md` (existing vs built, architecture, honest metrics), `.gitignore` (`data/raw/`, `.aws-sam/`, `.env*`)

### Unchanged
- `pipeline/generate_synthetic.py`, `models/train_hotspot.py`, and the 16 preview cities' data: kept as the labelled offline fallback.

### Removed / retired for the submission
- Render/Vercel deployment config (`nixpacks.toml` stays but is unused); hardcoded CORS origins in `api/main.py`.

## 11. Open points for the spec reviewer

1. Is OSM ward polygon quality acceptable for Delhi, or should hex zones be the default from the start?
2. Which Bedrock model and region is enabled in your AWS account?
3. Confirm Mumbai, Jaipur and Bengaluru are the right three contrast cities.
