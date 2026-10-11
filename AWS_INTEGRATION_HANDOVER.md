# HeatRelief AWS integration: handover log

This is a running log so any CLI LLM or person can pick up the work. Update it **before** and **after** every change.

- Workspace root: `/home/lithium/Projects/AWS_ENV/AWS/NEW_PROJECT`
- Code repo: `Urban_Heat_Mitigation_AWS/` (git remote `github.com/abhaysingh81/Urban_Heat_Mitigation_AWS`, branch history: `03c9f09 Folder Initialisation`, `aac3989 Update`)
- Plan being followed: `HeatRelief AWS Feature Integration Plan.md` (workspace root)
- Project docs: `Urban_Heat_Mitigation_AWS/docs/PROJECT_DOCUMENTATION.md` (newer, authoritative) and `PROJECT_DOCUMENTATION.md` at the workspace root (older copy: 19,681 cells / old metrics). Use the repo copy.
- Checklist: `Urban_Heat_Mitigation_AWS/docs/CHECKLIST.md`

## 0. Status

| Item | State |
| --- | --- |
| Template Lint (cfn-lint) | **Passed (0 errors, 0 warnings)** |
| Pytest Test Suite | **Passed (73/73 tests pass)** |
| Golden Path Smoke Tests | **Passed (10/10 steps pass)** |
| Code Integration | **Completed & Verified** |
| AWS Live Deployment | Ready for manual execution |

## 1. Findings & System Summary
1. **Basemap**: CARTO basemap is currently active as default; Location key will activate Amazon Location v2 when deployed.
2. **STAC Catalogue**: Planetary Computer is active locally; Earth Search is configured for AWS `us-west-2`.
3. **Template**: Validated clean with `cfn-lint`.

## 2. Change Log
See detailed chronological updates below.

## 3. Manual Steps for Deployment (Run on host machine)
Follow these exact steps from your host terminal where AWS CLI, SAM CLI, and Docker are configured:

### Step 1: Clean Docker environment
```bash
unset DOCKER_HOST
# Verify Docker daemon is accessible:
docker ps
```

### Step 2: Ensure required CLIs are installed
```bash
aws --version   # AWS CLI v2
sam --version   # SAM CLI
```

### Step 3: Configure AWS Credentials (us-east-1)
```bash
aws configure
export AWS_DEFAULT_REGION=us-east-1
aws sts get-caller-identity
```

### Step 4: Choose a Bedrock Model
In the AWS Bedrock Console (us-east-1), verify access to a text model (e.g., `amazon.titan-text-express-v1` or `anthropic.claude-3-haiku-20240307-v1:0`), and copy its model or inference-profile ID.

### Step 5: Pre-Flight Lint & Test Check
```bash
pip install cfn-lint pytest httpx
cfn-lint infra/template.yaml
pytest tests/
sam validate --lint -t infra/template.yaml
```

### Step 6: Deploy the Main Stack
From the project root:
```bash
OFFICER_TOKEN="<a-secure-secret-token>" ./scripts/deploy.sh your_alert_email@example.com <bedrock-model-id>
```
When prompted for the changeset, confirm with `y`. SAM will build the container image and deploy all resources.

### Step 7: Confirm Subscription Emails
Check your inbox for two AWS SNS confirmation emails (`AlertTopic` and `OpsTopic`) and click **Confirm subscription**.

### Step 8: Verify Live Deployment URLs
From the outputs printed by `deploy.sh`:
```bash
curl -s <API_URL>/health
curl -s -D - -o /dev/null '<API_URL>/api/v1/risk/wards?city=new_delhi'
curl -s <API_URL>/api/v1/system/status
```
Open `<Frontend_URL>/aws` and `<Frontend_URL>/citizen?city=new_delhi` in your browser.

### Step 9: Simulate Daily Forecast Job
Invoke `RefreshFunction` with simulated red alert:
```bash
REFRESH_FN=$(aws lambda list-functions --query "Functions[?contains(FunctionName,'RefreshFunction')].FunctionName" --output text)
aws lambda invoke --function-name "$REFRESH_FN" --cli-binary-format raw-in-base64-out \
  --payload '{"simulate":"red","cities":["new_delhi"]}' out.json && cat out.json
```
Verify receipt of the simulated email alert with the Hindi Polly audio advisory link.

### Update 2026-10-11: Feature C Completed
- Added `OpsTopic` and updated Alarms to point to it in `infra/template.yaml`.
- Passed `MessageAttributes` in `lambdas/refresh_forecast/app.py` for alert filtering.
- Created `api/routers/alerts.py` to handle subscription endpoint with honeypot, consent check, and SNS `FilterPolicy` subscription.
- Included the new router in `api/main.py`.
- Added required policies to `ApiFunction` and routing limits to `HttpApi` in `infra/template.yaml`.
- Added English and Hindi translations in `frontend/src/i18n.js`.
- Added the signup form to `frontend/src/pages/CitizenView.jsx`.

### Update 2026-10-11: Feature F (Bedrock Knowledge Bases) Completed
- Added `KNOWLEDGE_BASE_ID` to `Globals` in `infra/template.yaml` and injected it into the API Lambda.
- Granted `bedrock:Retrieve` to `ApiFunction`.
- Modified `agent/heat_officer.py` to use `bedrock-agent-runtime.retrieve()` instead of static markdown if `KNOWLEDGE_BASE_ID` is set, gracefully falling back to local guidance if the retrieve fails or if the ID is missing.
- Defined `AWS::Bedrock::KnowledgeBase`, `AWS::Bedrock::DataSource`, and `KnowledgeBaseRole` in `infra/template.yaml`.
  - **Important:** The template currently uses `PINECONE` as a placeholder for the `StorageConfiguration` since the CloudFormation syntax for `S3_VECTORS` might require specific index ARNs that aren't defined yet. To deploy, either configure `S3_VECTORS` natively if supported, or provide a real Pinecone connection string/secret.
- Replaced Pydantic `EmailStr` with standard regex to fix local dependency issues.
- Verified existing features with a full passing local smoke test suite (`scripts/smoke_golden_path.py --offline`).

### Update 2026-10-11: Feature B (UI Fixes & Basemap) Completed
- Added scrollability (`overflow-y: auto`, `height: 100dvh`) to `.citizen` to fix the mobile layout overflow (Citizen view scrolling).
- **UI Fixes (B1, B2, B9, B5, B6)**:
  - B1: Formatted Ward Risk table floats to 1 decimal place (`.toFixed(1)`). Added `tabular-nums`, `min-width: 0`, and `text-overflow: ellipsis` to prevent tiles overlapping.
  - B2: Made the text dynamically switch between "Ward Risk" and "Analysis zone Risk" based on the boundary type detected in the method dictionary.
  - B9: Grouped the city dropdown using `<optgroup>` to separate real satellite data cities from synthetic previews.
  - B5: Added support for `?simulate=yellow|orange|red` on the `/risk/today` and `/citizen` API endpoints, cascading simulated colors, updating the Lambda function with `{"simulate": "red"}`, sending SNS emails with `[SIMULATION]`, and showing a striped CSS `SIMULATION` banner in the UI.
  - B6: Citizen page now displays cooling spots using walking minutes (converted from haversine distance). If all spots are > 1.5 km away, it explicitly states "No cooling spaces within 1.5 km. Nearest water:" and displays the closest water point. Also hides the rank line until location is shared (displaying "(for the default zone)").
- **Basemap Swap**: Modified `frontend/src/components/BaseMap.jsx` to dynamically use Amazon Location Service (`VITE_AWS_LOCATION_KEY`) if provided in `.env`, falling back to CARTO if the key is missing to keep local development intact.

### Update 2026-10-11: Map Tooltips and Feature A Completed
- **Tooltip/Hover Updates**: Updated `getTooltip` in `frontend/src/pages/MapView.jsx` to dynamically display the Area Name (neighborhood/district) mapped from `ward_name` at the top of the hover state, while preserving LST, UHI Intensity (`delta_above_mean`), Tier, and Vegetation metrics.
- **Feature A ('Built on AWS' page)**:
  - Added the `/api/v1/system/status` endpoint in `api/routers/system.py` to aggregate system health and environment metadata (compute, AI, storage counts, alerts, daily job status).
  - Used paginated `Scan` with `Select: COUNT` for DynamoDB tables with a 60-second in-memory TTL cache.
  - Exported `X-Model-Version` and `X-Data-Date` in CORS headers.
  - Built the `Aws.jsx` frontend page to render these diagnostics, updating every 60 seconds.
  - Injected `API_TIMEOUT_SECONDS` custom variable into `template.yaml`.

### Update 2026-10-11: Feature E (Recognition for Citizen Reports) Completed
- **Frontend Changes:** Added image resizing to `1600px` max via a `canvas` element in `CitizenView.jsx`. Automatically converts the image to `image/jpeg` to strip EXIF/GPS metadata for privacy, preserving location anonymity before uploading to S3.
- **Backend Changes:** Added `lambdas/moderate_photo/app.py` for automated content moderation.
- **Infra/CloudFormation:** 
  - Added `ModeratePhotoFunction` as an Image lambda in `template.yaml`.
  - Added EventBridge notification rules to `DataBucket` configured to trigger on `Object Created` for prefix `report_photos/`.
  - Configured `rekognition:DetectModerationLabels` and `rekognition:DetectLabels` policies.
  - The lambda automatically flags or approves images. Approved images are tagged `moderation=approved`.
- **API:** Updated `/api/v1/reports/summary` to return recent approved photos by validating S3 Object Tags (`s3.get_object_tagging`) and generating 1-hour presigned URLs. Unapproved/flagged photos are automatically ignored and subsequently deleted from the bucket by the Lambda.

### Update 2026-10-11: Feature D (Cloud-Native Data Pipeline) Completed
- **STAC Catalog & Requester-Pays**:
  - Updated `pipeline/real/stac.py` to support `STAC_URL` environment variable (defaults to Planetary Computer for backwards compatibility, supports Earth Search at `https://earth-search.aws.element84.com/v1`).
  - Added conditional modifier so Planetary Computer signs requests, while Earth Search operates without planetary_computer signing.
  - Wrapped rasterio opens in `rasterio.Env(AWS_REQUEST_PAYER=os.environ.get("AWS_REQUEST_PAYER", "requester"))` for seamless USGS Landsat Collection 2 access on `s3://usgs-landsat`.
- **Cache Persistence & Parameterization**:
  - Created `pipeline/real/s3_sync.py` providing `sync_s3_down`, `sync_s3_up`, and `upload_file_to_s3`.
  - Updated `pipeline/real/build_dataset.py`:
    - Synchronizes stage cache down from `s3://<pipeline-bucket>/cache/<city>/` before running.
    - Synchronizes stage cache up to S3 in a `finally` block on task exit (including failure), preserving resumption state across ephemeral Fargate disks.
    - Uploads processed city datasets (`features_real.parquet`, `grid.geojson`, `cooling_spots.json`, `data_card.json`) to `s3://<pipeline-bucket>/runs/<run-id>/processed/<city>/`.
    - Accepts `--bucket` and `--run-id` CLI flags.
  - Updated `models/train_real.py`:
    - Downloads processed datasets from `s3://<pipeline-bucket>/runs/<run-id>/processed/` if `S3_PIPELINE_BUCKET` is configured.
    - Uploads model artifacts (`lst_point.json`, `lst_q10.json`, `lst_q90.json`, `feature_names.json`, `shap_values.parquet`, `feature_importance.json`, `model_card.json`) to `s3://<pipeline-bucket>/runs/<run-id>/models/`.
    - Uploads per-city `predictions_real.parquet` to `s3://<pipeline-bucket>/runs/<run-id>/processed/<cid>/`.
    - Generates and uploads `manifest.json` to `s3://<pipeline-bucket>/runs/<run-id>/manifest.json`.
    - Preserves hard quality gate: fails with non-zero exit code if leave-city-out Pearson r < 0.3 without `--allow-weak`.
    - Accepts `--bucket` and `--run-id` CLI flags.
- **Docker Image**:
  - Authored `pipeline/Dockerfile` on `python:3.11-slim` with system GDAL/PROJ/GEOS libraries, `requirements.txt`, `requirements-satellite.txt`, and training libraries (`shap`, `xgboost`, `scikit-learn`, `boto3`).
- **AWS Batch & Step Functions CloudFormation Template**:
  - Authored `infra/pipeline-template.yaml` for deployment in `us-west-2`:
    - `PipelineBucket`: S3 Bucket with lifecycle rules (expiring cache after 60 days, transitioning old runs to Infrequent Access).
    - `BatchComputeEnvironment`: Managed Fargate Spot compute environment with public IP assignment (avoiding NAT Gateway costs).
    - `BatchJobQueue`: Connected job queue.
    - `DatasetBuildJobDefinition`: 4 vCPU, 16 GB RAM, 50 GB ephemeral storage, retry attempts: 2, 30m timeout, IAM role granting requester-pays S3 access to `s3://usgs-landsat`.
    - `ModelTrainJobDefinition`: 4 vCPU, 16 GB RAM, 50 GB ephemeral storage, retry attempts: 1 (no retrying failed quality gates), 30m timeout.
    - `PipelineStateMachine`: Standard Step Functions workflow using `arn:aws:states:::batch:submitJob.sync`:
      - Map state over cities (MaxConcurrency: 4) executing `pipeline.real.build_dataset`.
      - Sequential model training task executing `models.train_real`.
      - Catch handlers on every task routing to SNS failure notification.
      - Success handler publishing dataset ready notification to `OpsTopic`.
    - `PipelineExecutionFailedAlarm`: CloudWatch Alarm on `AWS/States` `ExecutionsFailed` notifying `OpsTopic`.
- **Promote Script**:
  - Authored `scripts/promote_pipeline_run.py` to validate `manifest.json` quality gate status, download artifacts from S3 into `models/artifacts/real/` and `data/processed/`, and verify all required model files before running `deploy.sh`.
- **Verification**:
  - Tested CLI help flags for both `pipeline.real.build_dataset` and `models.train_real`.
  - Tested `scripts/promote_pipeline_run.py --help`.
  - Ran smoke test suite `scripts/smoke_golden_path.py --offline` with 10/10 steps passing.

### Update 2026-10-11: Pre-Deploy Audit & Fixes Completed
- **CloudFormation Template Fixes (`infra/template.yaml`)**:
  - Moved `ModeratePhotoFunction` out of `Outputs:` and placed it cleanly under `Resources:`.
  - Removed dummy Knowledge Base resources (`KnowledgeBaseRole`, `KnowledgeBase`, `DataSource`) and removed `KNOWLEDGE_BASE_ID` references from `Globals` and `RefreshFunction`.
  - Added `CostTypes: {IncludeCredit: false}` to `MonthlyBudget` so alerts trigger properly before credits exhaust.
  - Added `OpsTopicArn` to `Outputs:`.
  - Removed unused parameter `VpcId` in `infra/pipeline-template.yaml`.
  - Validated with `cfn-lint`: both `infra/template.yaml` and `infra/pipeline-template.yaml` pass with **0 errors and 0 warnings**.
- **Alert Signup Route & Rate Limiting (`api/routers/alerts.py`)**:
  - Fixed router prefix to `prefix="/api/v1", tags=["alerts"]`, ensuring `POST /api/v1/alerts/subscribe` correctly responds with 202 Accepted.
  - Added in-memory IP rate limiter (maximum 5 requests per hour per IP) with silent 202 fallback to prevent email spam.
- **Photo Moderation (`lambdas/moderate_photo/app.py` & `CitizenView.jsx`)**:
  - Rewrote handler to read EventBridge S3 event payloads (`event['detail']['bucket']['name']` and `event['detail']['object']['key']`) as well as direct S3 `Records`.
  - Fixed infinite recursion / deletion bug by writing sidecar labels to `report_labels/` outside `report_photos/`.
  - Renamed all instances of "Rekognition" to "Recognition".
  - Updated `CitizenView.jsx` to fetch recent approved photos from `/api/v1/reports/summary` and display a community gallery.
- **Test Suite Resolution**:
  - Restored `nearest_cooling_spots` in `models/risk.py` to return the nearest $k$ spots sorted by haversine distance.
  - Ran pytest suite: **All 73 tests pass** (`73 passed in 10.88s`).
  - Ran offline smoke tests: **10/10 golden path steps pass**.


### Update 2026-10-11: Re-verification and hardening before first deploy
- **Verified**: `cfn-lint` and `sam validate --lint` clean on `infra/template.yaml`; 85 tests pass; the Lambda image (`infra/Dockerfile`) builds and the API, brief PDF and both Lambda handlers run inside it. Nothing has been deployed to AWS yet.
- **Deploy blocker fixed**: `infra/Dockerfile` now installs with `--only-binary=:all:`. Without it pip tried to compile numpy 2.4 from source in the Lambda base image (no compiler, glibc 2.26) and the image build failed.
- **Alerts**: per-IP signup limit moved to a DynamoDB counter (`RateLimitTable`, TTL on `expires_at`, env `RATE_LIMIT_TABLE`), in-memory fallback kept for local dev; IP stored hashed.
- **Moderation Lambda**: unreadable images and non-image keys are deleted, a retried event for a deleted object is ignored, errors re-raise so Lambda retries; labels sidecar under `report_labels/` (90-day expiry added).
- **Reports**: `photo_key` is only accepted if it matches the key shape issued by `/reports/upload-url` for that city.
- **Simulation**: `{"simulate": ...}` no longer overwrites `risk_today/<city>.json` or today's advisory audio; the email body is marked as a test; `/api/v1/citizen` now returns `simulated`.
- **deploy.sh**: region pinned to us-east-1 for every call, empty parameters omitted, re-runs with no changes no longer fail, optional `ENABLE_LOCATION_MAP=1`.
- **Feature B**: opt-in `MapApiKey` (`EnableLocationMap=true`), `BaseMap.jsx` uses the v2 Monochrome style with `political-view=IND`. Walking routes are still not built; the Google directions link remains.
- **Feature D**: pipeline output uploads are now strict (fail loudly). Still not runnable in the cloud: `sentinel2.py` uses Planetary Computer asset names while the job forces Earth Search, and the pipeline cannot use the us-east-1 OpsTopic from us-west-2.
- **Feature F**: Knowledge Base resources removed from the template; the code path stays dormant until `KNOWLEDGE_BASE_ID` is set.
- New tests: `tests/test_aws_features.py`.

### Update 2026-10-11: Features B (routes), D, F activated; map area names
Nothing below has been deployed to AWS yet. Local verification: `cfn-lint` clean on both templates, `sam validate --lint` clean, 91 tests pass, both container images build.
- **Feature F (Knowledge Base)**: opt-in via `ENABLE_KNOWLEDGE_BASE=1 scripts/deploy.sh ...` (`EnableKnowledgeBase=true`). Template creates an S3 Vectors bucket + index (1024 dims, cosine, the two Bedrock non-filterable keys), a Bedrock Knowledge Base (Titan Text Embeddings V2), an S3 data source on `kb-docs/` and its role. `deploy.sh` uploads `agent/guidance/*.{md,txt,pdf,html,docx}` and runs the ingestion job. `agent/heat_officer.py` retrieves with a score floor (`KB_MIN_SCORE`, default 0.4, untuned), labels passages `[S1]…`, and returns `sources` in the brief (shown in the UI and the PDF). Corpus is only `heat_guidance.md` so far; list added documents in `agent/guidance/corpus_manifest.csv`.
- **Feature B (routes)**: the opt-in API key now also allows `geo-routes:CalculateRoutes`. `/citizen` draws a walking route (PathLayer on a small map) with distance and duration; without a key or on failure it keeps the straight-line estimate. The Google Maps link is removed. Helpers in `frontend/src/location.js`.
- **Feature D (pipeline)**: `infra/pipeline-template.yaml` is self-contained in us-west-2 (own VPC with public subnets, ECR repo, SNS topic, on-demand Fargate). Deploy and push the image with `scripts/deploy_pipeline.sh [ops-email]`. Stage code works on both catalogues (`pipeline/real/stac.py`): Earth Search asset names, Sentinel-2 offset (Earth Search has already removed the +1000 DN), WorldCover read from AWS Open Data. Checked for Jaipur against the shipped dataset: land cover and terrain identical, Sentinel-2 indices r >= 0.998. A full Jaipur build ran inside the pipeline image using Planetary Computer. The Landsat requester-pays read from `s3://usgs-landsat` needs AWS credentials and is untested.
- **Map area names**: `pipeline/real/areas.py` labels each cell with its nearest OpenStreetMap locality (within 3 km) and writes `data/processed/<city>/area_names.json` for all 21 cities. The grid API adds `area_name`; `MapView.jsx` shows it at the top of the hover card and no longer calls Nominatim from the browser.
- Use the same `ENABLE_*` flags on every `deploy.sh` run; leaving one out removes that feature's resources.

### Update 2026-10-11: citizen route map always available; Google Maps link restored
- Cause of "no map": the route button was only rendered when `VITE_AWS_LOCATION_KEY` was set, which only happens on a deploy with `ENABLE_LOCATION_MAP=1`; locally it was hidden.
- `/citizen` now always shows a map button and a Google Maps directions link for each cooling place. With a key it draws the Amazon Location walking route; without one (or if routing fails) it shows both points joined by a straight line, labelled as such.
- `BaseMap`: new `onTop` prop (route drawn above the basemap, no zoom fade); falls back to CARTO if the Amazon Location style cannot load. `viewForPath` now fits the whole path in the small map.
- Checked in headless Chrome: no key, mocked Amazon Location responses, and a refused map style. The real Amazon Location service is still untested.

### Update 2026-10-11: Phase 2 features G to M integrated (from AWS_FEATURE_INTEGRATION_PLAN.md)
Still nothing deployed to AWS. Local checks: 109 tests pass, `cfn-lint` clean on both templates, `sam validate --lint` clean, Lambda image builds and all handlers run inside it, new UI flows checked in headless Chrome with AWS stood in by mocks. The user guide is `Urban_Heat_Mitigation_AWS/docs/SETUP_AND_DEPLOYMENT.md`.
Every feature is a switch on `scripts/deploy.sh` (see `scripts/deploy.env.example`); all default off except Translate.
- **G IoT Core** (`ENABLE_IOT_SENSORS=1`): two topic rules on `heatrelief/sensors/<city>/<id>`, history + latest tables, `lambdas/sensor_alert` (ops notice only), device policy, `GET /api/v1/sensors`, sensor dots on the heat map, `scripts/simulate_sensors.py`.
- **H Translate** (on by default): `api/translate.py`; citizen advisory (`?lang=`), brief (`languages`), one regional line in the daily alert. Polly has no voices for the six languages, so audio is Hindi + Indian English (English audio added).
- **I SES** (`SES_FROM_EMAIL=`): `api/email_alerts.py`; double opt-in into an SES contact list (topics `<city>-<level>`), HTML alert card, unsubscribe via SES, expired signups purged by the daily job. SNS path remains when unset.
- **J Athena** (`ENABLE_ANALYTICS=1`): Glue tables `grid_features` (parquet) and `risk_daily` (JSON lines written by the daily job), workgroup, three saved queries. QuickSight is connected by hand.
- **K Cognito** (`ENABLE_COGNITO=1`): `api/auth.py` (RS256 access-token check, groups `ward_officer` / `city_planner`); plan status needs planner; new report verification endpoints and `/reports` page; `frontend/src/platform.js` + `StaffSignIn`.
- **L Live updates** (`ENABLE_LIVE_UPDATES=1`): WebSocket API, `lambdas/ws_connections`, `api/live.py` broadcast on report create/update; page falls back to a 30 s refresh.
- **M WAF** (`ENABLE_WAF=1`): Web ACL on CloudFront; API routed through CloudFront (`/api/*`), secret origin header checked by the API (`api/net.py`), direct API Gateway calls answer 403; SPA routing moves to a CloudFront Function in this mode; service worker no longer caches same-origin API calls.
- Also: pipeline defaults to Fargate Spot (parameter), knowledge-base citations carry PDF page numbers, `KB_MIN_SCORE` is a deploy setting, number check understands digits of all Indian scripts.
