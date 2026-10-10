# HeatRelief — project checklist

Last updated: 2026-10-10 (after real-data retrain, smoke 10/10 ×4 cities, 53 tests passing).
Legend: `[x]` done and verified · `[~]` done but only partly verified or partial · `[ ]` not done · **BLOCKER** = can sink the submission.
Update this file whenever something changes state; keep the "Verified how" notes honest.

## A. Submission blockers (do first)

- [ ] **BLOCKER — Deploy on AWS** (`scripts/deploy.sh <email> <bedrock-model-id>`). Needs AWS credentials, Docker, SAM CLI. Nothing has been deployed; template only passes `cfn-lint`.
- [ ] **BLOCKER — Enable a Bedrock model** in the target region and test Hindi output quality; set `BedrockModelId`. The live Strands/Bedrock path has never been called (mock-tested only).
- [ ] **BLOCKER — Demo video < 3 min**, public/unlisted on YouTube, checked signed-out, **AWS console visible** (Lambda, EventBridge, DynamoDB, SNS, CloudWatch dashboard).
- [ ] **BLOCKER — Old-project rule.** README must state existing vs built-in-event work; local git history has only two Oct 10 commits (re-init). Restore/link the original history; confirm commits match event dates (event start Oct 8).
- [ ] **BLOCKER — Confirm deadline hour** (Oct 11, hour unpublished) on the schedule page.
- [ ] Every teammate registered and student-verified; one submission form per team; check Amazon fast-track batch eligibility (2027/2028 only).
- [~] Writeup: problem, build, where AWS fits, AI coding tools used. Technical + AWS reference written: `docs/PROJECT_DOCUMENTATION.md` (no "AI coding tools used" section yet).
- [ ] AWS Builder Center blog (separate prize).
- [ ] Commit the work (nothing is committed; ~69 changed/new files) — review `git diff` first.

## B. Real-data pipeline (`pipeline/real/`)

- [x] Grid spec identical to existing fishnet (verified: 0 m centroid error, 4 cities)
- [x] Landsat multi-scene composite (≥6 scenes, QA-masked) — Delhi 14 scenes, all cells covered
- [x] Sentinel-2 indices, ESA WorldCover fractions, Copernicus DEM (nodata fill bug fixed)
- [x] Population from Meta HRSL (WorldPop unusable: no range requests)
- [x] Scene-date weather + heat index + wet-bulb; neighbourhood context features
- [x] Per-stage caching, data cards with licences, `--refresh/--skip` flags
- [~] OSM cooling spots — partial (Overpass throttling): Delhi 5,399 · Mumbai 2,351 · Jaipur 895 · Bengaluru 998. Re-run online to fill missing tiles (`python -m pipeline.real.build_dataset <city> --refresh osm`).
- [ ] OSM building footprints (opt-in `HEATRELIEF_OSM_BUILDINGS=1`; slow) — features currently NaN, unused by model
- [ ] Age structure (0–4, 65+) for vulnerability — not in v1
- [ ] Official ward polygons (`data/external/<city>_wards.geojson`) — zones are 2 km blocks
- [ ] Day vs night population switch
- [ ] Sentinel-2 / Landsat via AWS Open Data Registry (currently Planetary Computer; fine, but AWS-native would strengthen the story)

## C. Model (`models/train_real.py`)

- [x] XGBoost point + q10/q90, leave-one-city-out + 5 km block CV, baselines, quality gate (passed, r 0.72–0.89)
- [x] Conformal band calibration (coverage 73–82% vs 80% target; optimistic, same folds)
- [x] Model card JSON served by API and page
- [~] **Absolute level does not transfer** (bias −3.2…+3.7 °C, R² negative for some cities). Mitigated by using observed LST for tiers. Possible fix: per-city offset calibration or anomaly target.
- [ ] Weather features are city constants (4 values) — consider dropping variant or adding more cities
- [ ] Validate top-risk zones against a published heat action plan (cheap outside check)
- [ ] Retrain after OSM/building/age data are added

## D. Decision layer

- [x] Risk engine (hazard × exposure × vulnerability) + tests
- [x] Optimizer: budget cap, equity λ now changes the plan, tree survival, timeline, impact card + tests
- [x] Scenario simulator with low/mid/high published ranges; real presets computed, not read from synthetic files
- [x] Alert levels on separate dry-bulb / heat-index scales (heat index gated at Tmax ≥ 35 °C)
- [~] Cooling ranges and ₹ costs are **placeholders** — cite real studies / local quotes (`pipeline/config.py: REAL_INTERVENTIONS`)
- [ ] Extra scenarios from the blueprint: power-cut heatwave, +1.5/+2 °C climate shift, heat + water shortage, school hours, wind corridors
- [ ] Water link (water points, tanker routes) — Heat & Water track

## E. Agent

- [x] Strands agent with 5 registered tools; numbers check; one retry; template fallback; PDF (EN+HI, shaping verified visually)
- [x] Guardrail resource in template (topic + content filters)
- [ ] **Live Bedrock call tested** (see A)
- [ ] Hindi quality review by a native speaker (template + UI strings)
- [ ] Retrieval over real NDMA / city heat-action-plan documents (currently a short paraphrased guidance file)

## F. AWS / infra (`infra/`, `lambdas/`)

- [x] SAM template: S3, DynamoDB ×2, Lambda container API, HTTP API + throttling, EventBridge (06:00 IST), SNS, Polly, CloudFront+OAC, CloudWatch dashboard + alarms, Budgets, Guardrail — `cfn-lint` clean
- [ ] `sam build` / `sam deploy` actually run; stack outputs recorded
- [ ] SNS email subscription confirmed; test alert received
- [ ] Polly Hindi voice (`Kajal`, neural) available in chosen region — verify
- [ ] Narrow Bedrock IAM from `Resource: '*'` once the model is chosen
- [ ] Container image size / cold start measured; warm before demo
- [ ] Upload processed data + model to S3 (`deploy.sh` does it; not exercised)
- [ ] Rotate/confirm no secrets in repo (none used so far)

## G. API (`api/`)

- [x] Risk, plans (+audit, status machine), brief+PDF, reports (privacy-rounded), citizen, model card, exports (CSV/GeoJSON)
- [x] `X-Model-Version` / `X-Data-Date` headers; preview cities get clear 404 on real-only routes
- [x] Graceful degradation: forecast → cached → climatology (flagged stale)
- [ ] Authentication on plan status changes (any caller can approve) — acceptable for demo; note in writeup
- [ ] Report spam protection beyond API Gateway throttling

## H. Frontend (`frontend/`)

- [x] Ward Risk, Action Plan, Model Card, mobile Citizen view, EN/HI switch, onboarding, preview/real badges, exports, PWA files; builds clean; routes serve 200
- [ ] **Visual QA in a browser** (layouts, mobile width, dark/light, Hindi text overflow) — not done, no browser tool was available
- [ ] Accessibility pass (contrast, focus order, screen-reader labels, colour-only signals on risk chart)
- [ ] Ward map (currently a scatter plot of zone centres, not a polygon map)
- [ ] Old pages (Heat Map, Drivers, Scenarios) not translated to Hindi
- [ ] Two lint errors that pre-date this work (`App.jsx` effect, `ThemeContext.jsx` export)
- [ ] Service worker tested on a real deployment (HTTPS) and offline

## I. Tests & verification

- [x] 53 backend tests (optimizer, risk, numbers check, store, agent, API, exports)
- [x] Golden-path smoke (`scripts/smoke_golden_path.py`) 10/10 on all four cities against the live local API
- [ ] Run the smoke script against the **deployed** API (`--base <ApiUrl>`) and use it as demo rehearsal
- [ ] Frontend tests (none)
- [ ] CI run on GitHub (workflow written, never executed)

## J. Docs

- [x] README (existing vs built, results table, run + deploy, limits), `docs/LICENSES.md`, design spec
- [ ] Architecture diagram + screenshots in README (needs UI QA first)
- [ ] Update `docs/architecture.svg` (still shows the old Vercel/Render design)
- [ ] Remove or replace stale legacy docs/UI text that still describes synthetic data as the main product

## Running locally right now

- API: `http://localhost:8000` (docs at `/docs`) · UI: `http://localhost:5173` · all four real cities served; 16 others are labelled synthetic previews.
- Rebuild data: `python -m pipeline.real.build_dataset <city>` · retrain: `python -m models.train_real` · verify: `pytest -q` and `python scripts/smoke_golden_path.py --base http://localhost:8000`
