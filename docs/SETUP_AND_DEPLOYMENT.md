# HeatRelief: Setup, Deployment and Operations Guide

Everything you need to know and execute to set up, test, deploy, and operate HeatRelief on AWS.

**Status as of October 2026:**
- **Code & Test Suite:** All **151 unit tests** pass cleanly (`pytest tests/`).
- **Smoke Tests:** Local Golden Path end-to-end tests pass **10/10 steps** (`python scripts/smoke_golden_path.py --offline`).
- **Templates:** All three CloudFormation / SAM templates validate cleanly with `cfn-lint` (**0 errors, 0 warnings**):
  - `infra/template.yaml` (Main serverless stack in `us-east-1`)
  - `infra/pipeline-template.yaml` (Cloud data pipeline stack in `us-west-2`)
  - `infra/blog-hosting.yaml` (Interactive Builder Center blog stack)
- **Deployment State:** The repository is fully pre-flight verified and ready for live AWS deployment. Follow the step-by-step instructions below.

---

## 1. What You Need (Prerequisites)

| Tool / Resource | Version / Note |
| --- | --- |
| **AWS Account** | An IAM user or IAM Identity Center role with `AdministratorAccess`. **Do not use the AWS root user**. |
| **AWS CLI v2** | Installed (`aws --version`). Configured for `us-east-1`. |
| **AWS SAM CLI** | Installed (`sam --version`). Used for template validation, image building, and stack deployment. |
| **Docker Engine** | Installed and running (`docker ps`). See critical Docker note below. |
| **Node.js & npm** | Node 20+ (Node 22 recommended) with npm for frontend and interactive blog builds. |
| **Python** | Python 3.11+ virtual environment (`venv/`) with project dependencies installed. |
| **Accessible Email Address** | Receives SNS alerts, CloudWatch operational alarms, budget threshold notices, and subscription confirmations. |

### Critical Environment Notes

1. **Docker Host Resolution (Avoid Podman Socket Collision):**  
   If `/etc/profile.d/podman-docker.sh` is present on your system, it sets `DOCKER_HOST` to a nonexistent Podman socket. Before executing `docker` or `sam build`, ensure your terminal targets the Docker daemon:
   ```bash
   export DOCKER_HOST=unix:///var/run/docker.sock
   docker ps          # Must output container headers without connection errors
   ```
   *(Tip: Add `export DOCKER_HOST=unix:///var/run/docker.sock` to your `~/.bashrc` to make this permanent).*

2. **Network Connection:**  
   Docker image builds and container base layers download several hundred megabytes from Docker Hub and PyPI over IPv4. Use a stable broadband Wi-Fi or wired connection.

---

## 2. Run the Project Locally (No AWS Account Required)

You can develop, test, and preview the full application locally before deploying to AWS.

### 2.1 Starting Local Servers

```bash
cd Urban_Heat_Mitigation_AWS

# Terminal 1: FastAPI Backend API (http://localhost:8000)
venv/bin/uvicorn api.main:app --reload --port 8000

# Terminal 2: Vite React Frontend (http://localhost:5173)
cd frontend
npm install
npm run dev

# Terminal 3 (Optional): Interactive Builder Blog (http://localhost:5174)
cd ../BLOG
npm install
npm run dev
```

### 2.2 Running Tests and Linter Checks

Run the complete test suite and template linters:

```bash
# 1. Run all 151 unit tests (fast, offline, fully mocked)
venv/bin/python -m pytest tests/

# 2. Run end-to-end golden path smoke test
venv/bin/python scripts/smoke_golden_path.py --offline

# 3. Lint all CloudFormation templates
venv/bin/python -m cfnlint infra/template.yaml
venv/bin/python -m cfnlint --regions us-west-2 -t infra/pipeline-template.yaml
venv/bin/python -m cfnlint infra/blog-hosting.yaml
```

### 2.3 Feature Matrix: Local vs Live AWS

| Feature | Local Behavior | Live AWS Behavior |
| --- | --- | --- |
| **Heatmap & Scenarios** | Full raster & GeoJSON rendering with Deck.gl | Full edge caching via CloudFront |
| **Area Names on Hover** | Full OpenStreetMap reverse geocoding cache | Full OpenStreetMap reverse geocoding cache |
| **Citizen View** | Displays cooling spots and Google Maps walking link | Displays cooling spots, route calculation, and AWS map |
| **Ward Brief (AI)** | Deterministic fallback template text | Live Amazon Bedrock Claude/Nova inference |
| **Citizen Alert Signup** | Returns 202 Accepted (in-memory rate limit) | Real SNS / SES confirmation and filtered alerts |
| **Photo Upload** | Mock endpoint (returns 501 / disabled) | Direct S3 presigned upload + Amazon Rekognition |
| **Field Reports (`/reports`)** | Open access, local in-memory store | Role-based Cognito access or officer token, DynamoDB |
| **Street Sensors** | Simulated with `scripts/simulate_sensors.py --local` | Real AWS IoT Core MQTT rules & Kinesis Firehose |
| **System Status (`/aws`)** | Diagnostic panel loads with "local" values | Live AWS metadata (Lambda, DynamoDB, Bedrock, SNS) |

---

## 3. Prepare Your AWS Account (Once)

### 3.1 Configure AWS CLI Credentials

Create an IAM administrator user with access keys, then configure the AWS CLI:

```bash
aws configure
# AWS Access Key ID: <YOUR_KEY_ID>
# AWS Secret Access Key: <YOUR_SECRET_KEY>
# Default region name: us-east-1
# Default output format: json

# Verify identity:
aws sts get-caller-identity
```

### 3.2 Verify Billing & Credits

1. Open **Billing and Cost Management** in the AWS Console.
2. Check **Credits** to confirm active promo credits and eligible services.
3. Check your account payment plan. If using a newly opened account, ensure payment method verification is complete so CloudFront and SES are not restricted.
4. The template provisions a monthly budget (default: $25 USD) configured with `CostTypes: {IncludeCredit: false}` so alert notifications trigger based on gross usage before credits expire.

### 3.3 Enable Amazon Bedrock Foundation Models

1. In the AWS Console, switch to region **us-east-1**.
2. Open **Amazon Bedrock** > **Model access** (or **Model catalog**).
3. Ensure access is active for your chosen text model. Recommended choices:
   - **Amazon Nova Micro / Lite / Pro** (e.g. `amazon.nova-lite-v1:0` or inference profile)
   - **Anthropic Claude 3 Haiku** (`anthropic.claude-3-haiku-20240307-v1:0`)
4. Verify the model via CLI before deploying:
   ```bash
   aws bedrock-runtime converse --region us-east-1 --model-id <YOUR_MODEL_ID> \
     --messages '[{"role":"user","content":[{"text":"Say hello in Hindi"}]}]' \
     --query 'output.message.content[0].text'
   ```
5. *(Optional for Feature F)*: If enabling the Bedrock Knowledge Base, verify access to **Amazon Titan Text Embeddings V2** (`amazon.titan-embed-text-v2:0`).

---

## 4. Deploy the Baseline Stack

The baseline stack deploys:
- **FastAPI Backend:** Containerized Lambda behind an API Gateway HTTP API.
- **Frontend SPA:** S3 static website hosting (or CloudFront CDN when enabled via `ENABLE_CLOUDFRONT=1`).
- **Early Warning Job:** Daily 06:00 IST EventBridge schedule -> Open-Meteo forecast -> ward risk calculation -> Amazon Polly audio bulletin -> SNS alerts.
- **Photo Moderation:** Direct S3 presigned upload -> EventBridge notification -> Lambda photo moderation using **Amazon Rekognition** (auto-approves safe photos, deletes flagged content).
- **Data & Tables:** S3 Data Bucket, DynamoDB tables (`plans`, `reports`, `audit`).
- **Observability:** CloudWatch Dashboard, CloudWatch Alarms, and AWS Budget alerts.

### 4.1 Execute Deployment

Run from the `Urban_Heat_Mitigation_AWS` root:

```bash
cd Urban_Heat_Mitigation_AWS
export DOCKER_HOST=unix:///var/run/docker.sock

OFFICER_TOKEN='<CHOOSE_A_SECURE_TOKEN>' \
  ./scripts/deploy.sh your_alert_email@example.com <YOUR_BEDROCK_MODEL_ID>
```

#### What `deploy.sh` Does Automatically:
1. Validates prerequisites, builds container images using `sam build`.
2. Provisions the CloudFormation changeset (enter `y` when prompted).
3. Executes a dual-pass deployment: captures the newly minted frontend domain and injects it into API Gateway CORS policies.
4. Syncs local raster grids (`data/processed/`) and ML model artifacts (`models/artifacts/real/`) to the S3 data lake.
5. Builds the production frontend (`npm run build`) and uploads it to the frontend S3 bucket.
6. Invalidates CloudFront edge caches (if enabled) and prints the live URLs:
   - `API: https://<api-id>.execute-api.us-east-1.amazonaws.com`
   - `Frontend: http://<bucket-name>.s3-website-us-east-1.amazonaws.com` (or `https://<dist-id>.cloudfront.net` if CloudFront enabled)

### 4.2 Post-Deployment Verification

1. **Confirm SNS Subscriptions:**  
   Open your email inbox and click **Confirm subscription** on both notification emails:
   - `HeatRelief alerts` (Citizen & forecast notifications)
   - `HeatRelief Ops Alarms` (CloudWatch alarms & operational failures)

2. **Verify API Endpoints:**  
   Replace `<API>` with your deployed API URL:
   ```bash
   curl -s <API>/health
   # Expected: {"status":"ok","timestamp":"...","data_kind":"real"}

   curl -s -D - -o /dev/null '<API>/api/v1/risk/wards?city=new_delhi'
   # Verify response headers contain: X-Model-Version and X-Data-Date

   curl -s <API>/api/v1/system/status
   # Returns diagnostic compute, storage, and alert counters
   ```

3. **Verify Frontend in Browser:**  
   Open `<Frontend>` in your browser:
   - Check the **Heat Map** (`/`) for Delhi, Mumbai, Bengaluru, and Jaipur.
   - Check the **Built on AWS** page (`/aws`) to inspect live service status.
   - Check the **Citizen View** (`/citizen?city=new_delhi`).
   - Check the **Field Reports** dashboard (`/reports`).

4. **Trigger a Simulated Heat Alert:**  
   Verify the daily forecast Lambda without waiting for 06:00 IST:
   ```bash
   REFRESH_FN=$(aws lambda list-functions --region us-east-1 \
     --query "Functions[?contains(FunctionName,'RefreshFunction')].FunctionName" --output text)

   aws lambda invoke --region us-east-1 --function-name "$REFRESH_FN" \
     --cli-binary-format raw-in-base64-out \
     --payload '{"simulate":"red","cities":["new_delhi"]}' out.json && cat out.json
   ```
   *Result:* An alert email marked `[SIMULATION]` is delivered to your inbox containing the forecast summary and a presigned link to the Hindi Polly audio bulletin.

5. **Test Photo Moderation with Amazon Rekognition:**  
   On a mobile phone or browser, navigate to `<Frontend>/citizen?city=new_delhi`:
   - Click "Add an optional photo" and submit a report.
   - The browser automatically scales the image to $\le 1600$ px and strips EXIF/GPS metadata.
   - EventBridge invokes `ModeratePhotoFunction`. Clean images are tagged `moderation=approved` and appear in the community gallery on the citizen page. Inappropriate content is immediately deleted.

---

## 5. Enable Optional Features and Advanced Add-Ons

All optional features are toggled via environment variables. To manage them reliably, maintain a `.env.deploy` file:

```bash
cp scripts/deploy.env.example .env.deploy
# Edit .env.deploy with your desired features, then deploy:
set -a; source .env.deploy; set +a
./scripts/deploy.sh "$ALERT_EMAIL" "$BEDROCK_MODEL_ID"
```

### Complete Feature Switch Reference

| Variable | Feature | AWS Resources Provisioned | Cost Note |
| --- | --- | --- | --- |
| `ENABLE_LOCATION_MAP=1` | **B: Amazon Location Service** | Location API Key, monochrome v2 basemap, pedestrian routing | Free tier / Cents |
| `ENABLE_KNOWLEDGE_BASE=1` | **F: Bedrock Knowledge Base** | Bedrock KB with S3 Vectors, Titan Embeddings V2, RAG data source | Pay-per-query (Cents) |
| `ENABLE_TRANSLATE=1` *(default: 1)* | **H: Amazon Translate** | IAM permission enabling on-the-fly translation for 6 regional Indian languages | Free tier: 2M chars/mo |
| `SES_FROM_EMAIL=<addr>` | **I: Amazon SES HTML Cards** | Verified SES sender identity, contact lists, branded HTML cards with static map | ~$0.10 per 1,000 emails |
| `ENABLE_COGNITO=1` | **K: Cognito Authentication** | User Pool, App Client, `ward_officer` & `city_planner` groups | Free (< 50,000 MAU) |
| `ENABLE_LIVE_UPDATES=1` | **L: Live Officer WebSockets** | API Gateway WebSocket API, connection table, real-time report push | Free tier / Cents |
| `ENABLE_IOT_SENSORS=1` | **G: AWS IoT Core Sensors** | IoT Core MQTT topic rules, sensor DynamoDB table, alert Lambda, Firehose S3 backup | Free tier / Cents |
| `ENABLE_ANALYTICS=1` | **J: Glue & Athena Analytics** | Glue Data Catalog, Athena workgroup (`heatrelief-analytics`), saved queries | Pay-per-query ($5/TB) |
| `ENABLE_WAF=1` | **M: AWS WAF Security** | CloudFront WebACL with rate limits (50 req/5m on abuse routes) | ~$8 USD/month |
| `ENABLE_SECRETS=1` | **Secrets Manager Officer Token** | Automatically rotates/stores plan approval token in AWS Secrets Manager | ~$0.40 USD/month |
| `ENABLE_BATCH_BRIEFS=1` | **Bedrock Batch Inference** | Nightly EventBridge Scheduler job batch-generating briefs for all wards | 50% discount vs on-demand |
| `ENABLE_SYNTHETICS=1` | **CloudWatch Synthetics Canary** | Automated heartbeat canary testing `/health` every 5m with alarm | ~$1.20 USD/month |
| `WHATSAPP_PHONE_NUMBER_ID` | **WhatsApp Heat Alerts** | AWS End User Messaging Social integration with template messaging | Per-message Meta pricing |
| `CONNECT_INSTANCE_ID` | **Amazon Connect Voice Calls** | Automated outbound voice call advisories for non-smartphone citizens | Per-minute Connect pricing |

---

### 5.1 Feature B: Amazon Location Service (`ENABLE_LOCATION_MAP=1`)
- **What it does:** Replaces third-party CARTO tiles with compliant Amazon Location monochrome vector tiles (`political-view=IND`). Adds turn-by-turn walking route calculations from the citizen's location to the nearest cool refuge.
- **Verification:** On the citizen page, clicking "Walking route" renders the exact pedestrian path, distance, and walking minutes.
- **Local Dev:** To use the key locally:
  ```bash
  KEY=$(aws location describe-key --region us-east-1 --key-name heatrelief-map --query Key --output text)
  echo "VITE_AWS_LOCATION_KEY=$KEY" > frontend/.env.local
  echo "VITE_AWS_REGION=us-east-1" >> frontend/.env.local
  ```

### 5.2 Feature F: Bedrock Knowledge Base with S3 Vectors (`ENABLE_KNOWLEDGE_BASE=1`)
- **What it does:** Connects the Heat Officer agent to a vector index on S3 Vectors using `amazon.titan-embed-text-v2:0`.
- **Steps:**
  1. Add authoritative PDF, Markdown, or text documents into `agent/guidance/`.
  2. Document each addition in `agent/guidance/corpus_manifest.csv`.
  3. Deploy with `ENABLE_KNOWLEDGE_BASE=1`. The deploy script uploads files and executes the ingestion sync job.
- **Verification:** Generating a ward brief cites specific retrieved sections (e.g. `[S1] National Heat Action Plan, p. 12`).

### 5.3 Feature I: Amazon SES Branded HTML Alerts (`SES_FROM_EMAIL=alerts@your-domain.org`)
- **What it does:** Replaces plain-text SNS emails with responsive HTML alert cards containing an Amazon Location static snapshot map, heat index breakdown, and one-click unsubscribe links.
- **Setup:**
  1. Deploy with `SES_FROM_EMAIL=your-verified-email@example.com`.
  2. Open your inbox and click the SES email identity verification link.
  3. While in the SES sandbox, verify test recipient addresses:
     ```bash
     aws sesv2 create-email-identity --region us-east-1 --email-identity tester@example.com
     ```
  4. Request production access in the SES Console for general distribution.

### 5.4 Feature K: Amazon Cognito Role-Based Access (`ENABLE_COGNITO=1`)
- **What it does:** Eliminates the shared static `OFFICER_TOKEN`. Protects administrative actions using Cognito User Pools and JWT verification:
  - `ward_officer`: Can view citizen reports, update status, and log assistance.
  - `city_planner`: Can approve plans, mark interventions implemented, and manage shelters.
- **Creating Staff Users:**
  ```bash
  POOL=$(aws cloudformation describe-stacks --stack-name heatrelief --region us-east-1 \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)

  aws cognito-idp admin-create-user --region us-east-1 --user-pool-id "$POOL" \
    --username officer@example.org \
    --user-attributes Name=email,Value=officer@example.org Name=email_verified,Value=true

  aws cognito-idp admin-add-user-to-group --region us-east-1 --user-pool-id "$POOL" \
    --username officer@example.org --group-name ward_officer
  ```

### 5.5 Feature L: Live Officer WebSockets (`ENABLE_LIVE_UPDATES=1`)
- **What it does:** Establishes an API Gateway WebSocket connection on `<Frontend>/reports`. Whenever a citizen submits a report or refuge capacity changes, updates push immediately to officer dashboards without page polling.

### 5.6 Feature G: AWS IoT Core Street Sensors (`ENABLE_IOT_SENSORS=1`)
- **What it does:** Ingests live microclimate telemetry from street poles via MQTT topic `heatrelief/sensors/<city>/<sensor_id>`.
- **Testing without hardware:**
  ```bash
  venv/bin/python scripts/simulate_sensors.py --city new_delhi
  venv/bin/python scripts/simulate_sensors.py --city new_delhi --hot  # Triggers ops notification
  curl -s '<API>/api/v1/sensors?city=new_delhi'
  ```
- Sensors appear dynamically as live status dots on the heat map.

### 5.7 Feature J: Amazon Athena & QuickSight Analytics (`ENABLE_ANALYTICS=1`)
- **What it does:** Sets up Glue Data Catalog tables (`grid_features`, `risk_daily`, `sensor_history`) and workgroup `heatrelief-analytics`.
- **Running a test query:**
  ```bash
  QID=$(aws athena start-query-execution --region us-east-1 --work-group heatrelief-analytics \
    --query-execution-context Database=heatrelief_analytics \
    --query-string "SELECT city, count(*) AS cells, round(avg(lst_c),1) AS mean_lst FROM grid_features GROUP BY city" \
    --query QueryExecutionId --output text)
  sleep 4
  aws athena get-query-results --region us-east-1 --query-execution-id "$QID" --output table
  ```
- **QuickSight Setup:** In AWS QuickSight > Manage Permissions, enable Athena and the HeatRelief data S3 bucket, then create dashboards on `grid_features`.

### 5.8 Feature M: AWS WAF Security (`ENABLE_WAF=1`)
- **What it does:** Protects the platform with AWS WAF attached to CloudFront. Routes all API traffic through CloudFront edge caches and rate-limits signup/upload endpoints to 50 requests per 5 minutes per IP.
- **Note:** When WAF is enabled, direct calls to API Gateway return `403 Forbidden`. All client requests must target the `<Frontend>/api/v1/...` URL.

### 5.9 Feature: Secrets Manager Token (`ENABLE_SECRETS=1`)
- **What it does:** Automatically generates a cryptographically secure 32-character officer secret and stores it in AWS Secrets Manager under `heatrelief/officer-token`.
- **Retrieving the Token:**
  ```bash
  aws secretsmanager get-secret-value --region us-east-1 --secret-id heatrelief/officer-token \
    --query SecretString --output text
  ```

### 5.10 Feature: Bedrock Batch Inference (`ENABLE_BATCH_BRIEFS=1`)
- **What it does:** Executes a nightly batch inference job (`agent/batch_briefs.py`) at 00:30 IST across all 418 wards. Pre-generates English and Hindi briefs into S3 cache at 50% lower cost, ensuring instant sub-second page loads for ward planners.

### 5.11 Feature: CloudWatch Synthetics Canary (`ENABLE_SYNTHETICS=1`)
- **What it does:** Packages and deploys a Python Selenium canary (`infra/canary/python/heartbeat.py`) that monitors `<API>/health` every 5 minutes. Publishes an immediate CloudWatch Alarm to `OpsTopic` if availability drops.

---

## 6. Feature D: Cloud Data Pipeline Stack (AWS Batch in `us-west-2`)

The data pipeline stack runs in **`us-west-2`** directly adjacent to the USGS Landsat and Sentinel-2 AWS Open Data archives. It operates independently of the main API stack and rebuilds datasets using AWS Batch on Fargate Spot.

### 6.1 Deploy Pipeline Infrastructure

```bash
cd Urban_Heat_Mitigation_AWS
export DOCKER_HOST=unix:///var/run/docker.sock

./scripts/deploy_pipeline.sh your_ops_email@example.com
```

This deploys `infra/pipeline-template.yaml`, provisions an ECR repository, builds the GDAL/Rasterio pipeline container (`pipeline/Dockerfile`), pushes the image, and sets up the Step Functions state machine.

### 6.2 Trigger a Pipeline Execution

```bash
MACHINE=$(aws cloudformation describe-stacks --region us-west-2 --stack-name heatrelief-pipeline \
  --query "Stacks[0].Outputs[?OutputKey=='PipelineStateMachineArn'].OutputValue" --output text)
BUCKET=$(aws cloudformation describe-stacks --region us-west-2 --stack-name heatrelief-pipeline \
  --query "Stacks[0].Outputs[?OutputKey=='PipelineBucketName'].OutputValue" --output text)

RUN_ID="real-v1-$(date -u +%Y%m%d)"

aws stepfunctions start-execution --region us-west-2 --state-machine-arn "$MACHINE" \
  --name "$RUN_ID-run" \
  --input "{\"cities\":[\"new_delhi\",\"mumbai\",\"jaipur\",\"bengaluru\"],\"run_id\":\"$RUN_ID\"}"
```

### 6.3 Promote Pipeline Artifacts to Main Application

Once the Step Functions execution completes successfully and passes the quality gate ($r \ge 0.3$ on held-out cities):

```bash
# 1. Download and promote verified models & datasets from S3
AWS_DEFAULT_REGION=us-west-2 venv/bin/python scripts/promote_pipeline_run.py \
  --bucket "$BUCKET" --run-id "$RUN_ID"

# 2. Run verification suite
venv/bin/python -m pytest tests/

# 3. Redeploy main application with updated models
./scripts/deploy.sh your_alert_email@example.com <YOUR_BEDROCK_MODEL_ID>
```

---

## 7. Interactive Builder Center Blog Deployment

A dedicated interactive storytelling application (`BLOG/`) is included to publish findings, architectural diagrams, and interactive heat maps:

```bash
# Deploy blog stack to CloudFront + S3:
./scripts/deploy_blog.sh heatrelief-blog us-east-1
```

- Builds the Vite React / TypeScript blog in `BLOG/dist`.
- Deploys `infra/blog-hosting.yaml`.
- Syncs compiled assets to S3 and invalidates CloudFront.
- Outputs the live public blog URL.

---

## 8. Day-to-Day Operations & Maintenance

| Operational Task | Command / Action |
| --- | --- |
| **Deploy Code or Model Updates** | Run `./scripts/deploy.sh "$ALERT_EMAIL" "$BEDROCK_MODEL_ID"` using your `.env.deploy` switches. |
| **View Stack Outputs** | `aws cloudformation describe-stacks --stack-name heatrelief --region us-east-1 --query 'Stacks[0].Outputs' --output table` |
| **Inspect Application Logs** | CloudWatch Logs > Log groups: `/aws/lambda/heatrelief-ApiFunction-...` and `/aws/lambda/heatrelief-RefreshFunction-...` |
| **Monitor Live Metrics** | CloudWatch > Dashboards > `heatrelief-heatrelief` |
| **Trigger Immediate Forecast Run** | Invoke `RefreshFunction` via AWS CLI without the `"simulate"` payload flag. |
| **Update Knowledge Base Corpus** | Add documents to `agent/guidance/`, update `corpus_manifest.csv`, and run deploy with `ENABLE_KNOWLEDGE_BASE=1`. |

---

## 9. Cost Guardrails & Idle Spending

HeatRelief is engineered for maximum credit efficiency and near-zero idle cost:

- **Pay-Per-Use (Zero Cost when Idle):** Lambda, API Gateway, DynamoDB On-Demand, S3 storage, Amazon Rekognition, Amazon Polly, Bedrock inference.
- **Fixed / Hourly Services while Enabled:**
  - **AWS WAF (`ENABLE_WAF=1`):** ~$8.00 USD/month.
  - **CloudWatch Synthetics Canary (`ENABLE_SYNTHETICS=1`):** ~$1.20 USD/month.
  - **QuickSight:** Billed per author ($18–$24/month); cancel trial before expiration.
- **Architectural Cost Guardrails:**
  - No expensive NAT Gateways (tasks assign public IPs in public subnets).
  - No OpenSearch Serverless (Bedrock uses lightweight S3 Vectors).
  - No idle SageMaker endpoints (Lambda container inference with XGBoost).

---

## 10. Complete Teardown (Clean Resource Removal)

To completely remove all provisioned infrastructure and prevent ongoing charges:

```bash
# 1. Teardown Main Application Stack (us-east-1)
DATA_BUCKET=$(aws cloudformation describe-stacks --stack-name heatrelief --region us-east-1 \
  --query "Stacks[0].Outputs[?OutputKey=='DataBucketName'].OutputValue" --output text)
FRONT_BUCKET=$(aws cloudformation describe-stacks --stack-name heatrelief --region us-east-1 \
  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" --output text)

aws s3 rm "s3://$DATA_BUCKET" --recursive
aws s3 rm "s3://$FRONT_BUCKET" --recursive
sam delete --stack-name heatrelief --region us-east-1

# 2. Teardown Pipeline Stack (us-west-2, if deployed)
PIPE_BUCKET=$(aws cloudformation describe-stacks --stack-name heatrelief-pipeline --region us-west-2 \
  --query "Stacks[0].Outputs[?OutputKey=='PipelineBucketName'].OutputValue" --output text)

aws s3 rm "s3://$PIPE_BUCKET" --recursive --region us-west-2
aws cloudformation delete-stack --stack-name heatrelief-pipeline --region us-west-2

# 3. Teardown Blog Stack (if deployed)
BLOG_BUCKET=$(aws cloudformation describe-stacks --stack-name heatrelief-blog --region us-east-1 \
  --query "Stacks[0].Outputs[?OutputKey=='BlogBucketName'].OutputValue" --output text)

aws s3 rm "s3://$BLOG_BUCKET" --recursive
aws cloudformation delete-stack --stack-name heatrelief-blog --region us-east-1
```

---

## 11. Troubleshooting Guide

| Symptom | Cause | Solution |
| --- | --- | --- |
| `docker` cannot connect or `sam build` fails immediately | `DOCKER_HOST` environment variable points to a missing Podman socket | Run `export DOCKER_HOST=unix:///var/run/docker.sock` and verify with `docker ps`. |
| Container build hangs on PyPI downloads | Slow network tether or IPv4 DNS routing issue | Connect to broadband Wi-Fi before running `sam build`. |
| `sam deploy` reports `ROLLBACK_COMPLETE` | Previous initial deployment failed, locking the stack | Run `sam delete --stack-name heatrelief --region us-east-1`, fix the issue, and redeploy. |
| Ward brief displays `source: template` | Bedrock model access not granted, invalid model ID, or timeout | Verify model ID in `us-east-1` with `aws bedrock-runtime converse`. Ensure the model supports Converse tool use. |
| Heat alert email is not received | SNS subscription unconfirmed or forecast level < threshold | Click confirmation link in the SNS email; verify via simulation (`"simulate":"red"`). |
| All API endpoints return `403 Forbidden` | `ENABLE_WAF=1` is active and requests are calling API Gateway directly | Target the CloudFront frontend address (`<Frontend>/api/v1/...`) instead of the raw execute-api endpoint. |
| Map tiles fail to render on a custom domain | Location API Key referer restriction does not include the domain | Add your custom domain to `AllowReferers` under `LocationApiKey` in `infra/template.yaml`. |
| CloudFront distribution fails creation on new account | Brand-new AWS accounts require identity verification for CDN edge | Submit a quick verification support ticket in the AWS Console. |
