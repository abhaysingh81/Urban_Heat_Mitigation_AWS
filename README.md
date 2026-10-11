# HeatRelief — from heat map to heat decision

A heat decision system for Indian cities: **where is it dangerous → who is exposed and vulnerable → what to build, for how
much → a written ward brief in Hindi + English → a live alert and a citizen page.** Built for the Environmental Hacks
(Heat & Water track) on AWS.

> **Honesty box.** The real-data tier trains on **real Landsat surface temperature** (not a formula). Accuracy on cities
> the model never saw is reported on the in-app *Model Card* page and in `models/artifacts/real/model_card.json`. Cooling
> results are **estimates from published ranges**, not guarantees. Risk is a **relative ranking**, not a harm prediction.
> The 16 cities outside the real tier are **synthetic previews** and are labelled as such everywhere.

## What existed before vs. what was built for the event

**Existing base (before the event):** a React/Deck.gl heat-map dashboard with SHAP driver analysis and a two-intervention
scenario builder for 20 Indian cities, backed by a *synthetic* data generator and a FastAPI service (Vercel + Render).
Note: this repository's local history was re-initialised on 2026-10-10; the original project history lives in the upstream
repository and should be linked here before submission.

**Built for the event (everything below):**

| Area | What | Where |
|---|---|---|
| Real data | Landsat multi-scene LST composite (target), Sentinel-2 indices, WorldCover, Copernicus DEM, Meta HRSL population, OSM cooling spots, scene-date weather (heat index, wet-bulb), neighbourhood context features, analysis zones — for Delhi, Mumbai, Jaipur, Bengaluru | `pipeline/real/` |
| Model | XGBoost + q10/q90 uncertainty, leave-one-city-out and 5 km spatial-block CV, baselines, quality gate, model card | `models/train_real.py` |
| Risk engine | ward risk = hazard × exposure × vulnerability | `models/risk.py` |
| Optimizer | budget- and equity-aware plan, impact card, timeline, tree survival | `models/optimizer.py` |
| Scenarios | published cooling ranges (low/mid/high), 5 interventions | `models/real_simulate.py`, `pipeline/config.py` |
| Agent | Strands + Bedrock ward brief (EN/HI), numbers verified against tool output, template fallback, PDF | `agent/` |
| Early warning | EventBridge → Lambda → S3 / SNS / Polly | `lambdas/refresh_forecast/` |
| API | risk, plans (DynamoDB lifecycle + audit), brief, reports, model card, citizen | `api/` |
| UI | Ward Risk, Action Plan, Model Card, mobile Citizen view, Hindi/English | `frontend/src/` |
| Infra | one-command SAM deploy (S3, DynamoDB, Lambda container, HTTP API + throttling, EventBridge, SNS, Polly, CloudFront, CloudWatch dashboard + alarms, Budgets) | `infra/`, `scripts/deploy.sh` |
| Tests | optimizer, risk, numbers check, store, API, agent | `tests/`, `scripts/smoke_golden_path.py` |

## Results (from `models/artifacts/real/model_card.json`, real-v1-20261010)

Target: Landsat 8/9 surface-temperature composite, Apr–Jun 2024–26 (≥6 clear scenes per city). Variant shipped: `spatial+weather`.
Scored on a city **the model never saw** (trained on the other three):

| Held-out city | Pearson r | RMSE °C | Bias °C | Baseline r (NDVI+impervious) |
|---|---|---|---|---|
| new_delhi | 0.823 | 2.523 | -1.923 | -0.528 |
| mumbai | 0.821 | 3.944 | 1.253 | -0.696 |
| jaipur | 0.818 | 3.065 | -2.651 | -0.478 |
| bengaluru | 0.775 | 3.915 | 3.651 | -0.557 |

Reading it honestly: the **spatial pattern transfers well** (r = 0.775–0.823) — the old synthetic surface had r = −0.47 against real Delhi LST. The **absolute level does not** transfer cleanly
(city-level offsets, see bias/RMSE), which is why hotspot tiers use the *observed* composite and the model is used for gap-filling and scenario deltas.
The q10–q90 band is conformally widened by 0.17 °C (calibrated block-CV coverage new_delhi 81%, mumbai 78%, jaipur 78%, bengaluru 81%; target 80%).
Trained on 25,588 cells; each city's grid covers its full administrative boundary (OSM), and maps, risk and plans use only cells inside it.

## Architecture

```
Open data (Landsat · Sentinel-2 · WorldCover · DEM · HRSL · OSM · Open-Meteo)
        │  pipeline/real  (cached per city, aggregated to a 500 m grid)
        ▼
 features_real.parquet ──► train_real.py ──► model + model_card.json
        │                                         │
        ▼                                         ▼
 EventBridge (06:00 IST) ─► Lambda: forecast ─► ward risk today ─► S3 ─► SNS alert + Polly (Hindi)
                                  │
 Officer UI ─► API Gateway ─► Lambda (FastAPI): risk · optimizer · brief ─► Bedrock (Strands agent)
 Citizen UI ─►     │                      │                                   │
                   ▼                      ▼                                   ▼
               DynamoDB (plans, audit, reports)                  S3 (PDF briefs, advisories)
```

## Run it locally

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-satellite.txt
pip install fpdf2 uharfbuzz strands-agents mangum boto3 pytest httpx

# 1. build real data (network; ~10–20 min per city, cached under data/raw/real/)
python -m pipeline.real.build_dataset new_delhi mumbai jaipur bengaluru
#    optional heavy extra: HEATRELIEF_OSM_BUILDINGS=1 for OSM building footprints

# 2. train + model card (fails loudly if leave-one-city-out r < 0.3; --allow-weak to override)
python -m models.train_real

# 3. run
uvicorn api.main:app --reload                 # API on :8000
cd frontend && npm install && npm run dev     # UI on :5173

# 4. verify
pytest -q
python scripts/smoke_golden_path.py --offline
```

Bedrock briefs: set `BEDROCK_MODEL_ID` (a model enabled in your account/region), optionally `BEDROCK_GUARDRAIL_ID`.
Without it the deterministic template brief is used (same facts, same number verification).

## Deploy on AWS (one command)

Step-by-step instructions for the account, every optional AWS feature, checks, costs and teardown: [docs/SETUP_AND_DEPLOYMENT.md](docs/SETUP_AND_DEPLOYMENT.md).

```bash
scripts/deploy.sh you@example.com <bedrock-model-id>   # needs AWS creds, Docker, SAM CLI, Node
```

Warm the API before recording the demo (`/health`, then `/api/v1/risk/wards?city=new_delhi`). Keep the stack up until results.
SNS SMS to India needs DLT registration, so alerts go by email.

## Limits (also on the Model Card page)

- Land surface temperature ≠ air temperature ≠ heat stress; humidity is city-level only.
- No age, income or informal-settlement data in v1; vulnerability uses density, green deficit and crowding.
- Zones are 2 km analysis blocks unless official ward polygons are placed in `data/external/<city>_wards.geojson`.
- Cooling ranges and costs are planning-grade placeholders. See `docs/LICENSES.md` for sources and credits.
