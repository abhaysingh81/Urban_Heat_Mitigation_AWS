# HeatRelief: Comprehensive AWS Feature Integration Plan & Architecture Roadmap

**Platform:** HeatRelief (Urban Heat Mitigation & Climate Resilience Platform)  
**Target Deployment:** AWS Cloud (Serverless & Cloud-Native)  
**Target Geographies:** New Delhi, Mumbai, Bengaluru, Jaipur (Scalable Nationally)  
**Document Status:** Comprehensive Blueprint (Initial Core Addons + Advanced Extensions)

---

## 1. Executive Summary & Architecture Vision

HeatRelief addresses urban heat island (UHI) effects and lethal heatwave conditions across dense Indian metropolitan centers. The platform connects municipal officers, disaster management authorities, and vulnerable citizens with hyper-local heat forecasts, AI-driven intervention planning, and real-time cooling infrastructure.

This document unifies:
1. **The Core Serverless Baseline:** The foundational compute, storage, and caching layer.
2. **Phase 1 Priority Add-ons (Features A–F):** High-impact enhancements integrating Amazon Location Service, SNS topic splitting, AWS Batch, Rekognition, and Bedrock Knowledge Bases with S3 Vectors.
3. **Phase 2 Advanced Add-ons (Features G–M):** Scalable enterprise extensions including IoT ground sensing, regional language translation, SES notifications, Athena/QuickSight analytics, Cognito authentication, live WebSockets, and AWS WAF security.

```
                              +-------------------------------------------------------+
                              |                    Amazon CloudFront                  |
                              |              (Edge Caching & SSL Termination)         |
                              +---------------------------+---------------------------+
                                                          |
                                      +-------------------+-------------------+
                                      |                                       |
                                      v                                       v
                             [Static Web Assets]                     [API Gateway HTTP API]
                             Amazon S3 (Frontend)                    (Throttling, Routing)
                                                                              |
                                                          +-------------------+-------------------+
                                                          |                                       |
                                                          v                                       v
                                                  AWS Lambda (FastAPI)                 AWS Lambda (Moderation)
                                                 (Core Business Logic)                 (S3 EventBridge Trigger)
                                                          |                                       |
                   +------------------+-------------------+-------------------+                   v
                   |                  |                   |                   |          Amazon Rekognition
                   v                  v                   v                   v         (Photo Content Filter)
             Amazon DynamoDB      Amazon S3         Amazon Bedrock       Amazon SNS
            (Plans, Reports)  (Data & Vectors)   (AI Heat Officer RAG) (Filtered Alerts)
```

---

## 2. Baseline Serverless Foundation

| Service | Architectural Role | Cost Model |
| :--- | :--- | :--- |
| **AWS Lambda** | Runs FastAPI application code and daily scheduled forecast refreshes via container images. | Pay-per-invocation & duration (Free tier: 1M requests/mo). |
| **Amazon API Gateway** | Managed HTTP API providing routing, CORS handling, and per-route throttling. | $1.00 per million requests. |
| **Amazon DynamoDB** | On-demand NoSQL database storing intervention plans, citizen field reports, and rate-limit counters. | Pay-per-request (Free tier: 25 GB storage). |
| **Amazon S3** | Object storage hosting frontend builds, pre-computed raster grids, GeoJSON boundaries, and citizen photos. | Standard storage tier (~$0.023/GB/mo). |
| **Amazon CloudFront** | CDN providing edge distribution, caching, and HTTPS termination for sub-second latency. | Generous free tier (1 TB transfer out/mo). |
| **Amazon Polly** | Synthesizes daily morning heat advisories into Hindi and English audio bulletins for accessibility. | Pay-per-character (Free tier: 5M chars/mo for 12 mos). |
| **AWS Budgets & CloudWatch** | Real-time monitoring, structured logging, and budget alarms with credit tracking. | Budgets free (first 2); CloudWatch standard logs. |

---

## 3. Phase 1 Priority Add-Ons (Core Roadmap)

### Feature A: 'Built on AWS' Transparency & Health Page (`/aws`)
* **Objective:** Provide a public, live transparency dashboard showcasing serverless runtime health, data provenance, and cloud resource counters without exposing sensitive credentials.
* **Services Involved:** AWS Lambda (runtime environment variables), Amazon DynamoDB, Amazon SNS, Amazon CloudWatch.
* **Key Components:**
  * **Compute Status:** Inspects `AWS_LAMBDA_FUNCTION_NAME`, memory size, region, and cold start detection flag.
  * **Model Provenance:** Reads `X-Model-Version` and `X-Data-Date` directly from `model_card.json`.
  * **Resource Counts:** Lightweight, cached (60s) DynamoDB paginated item count on plans and reports tables.
  * **Security Rule:** Explicitly strips Account IDs, ARNs, and private bucket names from responses.

### Feature B: Amazon Location Service (Basemap & Pedestrian Routes)
* **Objective:** Replace third-party mapping dependencies (CARTO/Google Maps) with AWS-native vector tiles, ensure Indian geopolitical compliance, and calculate real walking routes to cooling spots.
* **Services Involved:** Amazon Location Service (`geo-maps:*`, `geo-routes:CalculateRoutes`).
* **Key Components:**
  * **Monochrome Basemap:** Clean map style supporting light and dark themes optimized for high-contrast heat overlays.
  * **Geopolitical View:** Implements `political-view=IND` parameter for compliant administrative boundaries.
  * **Walking Directions:** Calls `CalculateRoutes` (`TravelMode: Pedestrian`) to provide walking time and turn-by-turn paths from the user's location to the nearest verified water point or shaded shelter.

### Feature C: Citizen Heat Alert Engine & Split SNS Topics
* **Objective:** Protect citizens through automated, targeted heat warnings while isolating operational developer alarms.
* **Services Involved:** Amazon Simple Notification Service (SNS).
* **Key Components:**
  * **Topic Separation:** Isolates internal alarms (`OpsTopic`) from public citizen alerts (`AlertTopic`).
  * **Subscription Filter Policies:** Attributes (`city: [city]`, `level_num: [>= threshold]`) ensure a Delhi resident never receives Jaipur alerts or low-priority alerts.
  * **Abuse & Privacy Protection:** Public subscription endpoint uses honeypots, tight route throttling (1 req/sec), IP rate limits in DynamoDB, and 48-hour confirmation tokens.

### Feature D: Cloud-Native Geospatial Data Pipeline
* **Objective:** Transition satellite data processing (Landsat Collection 2 & Sentinel-2) and ML model retraining from local laptops to an automated, reproducible cloud workflow.
* **Services Involved:** AWS Batch on AWS Fargate, AWS Step Functions, Amazon ECR, Amazon S3.
* **Key Components:**
  * **Workflow Orchestration:** Standard Step Functions state machine mapping parallel city ingestion runs.
  * **Serverless Container Execution:** AWS Batch running GDAL, Rasterio, and LightGBM in Fargate Spot containers.
  * **Data Locality:** Runs in `us-west-2` adjacent to USGS Landsat requester-pays storage, syncing intermediate caches to S3.
  * **Automated Quality Gates:** Strict validation criteria (Pearson correlation $r \ge 0.3$) stopping failing runs before promotion.

### Feature E: Amazon Rekognition for Community Photo Moderation
* **Objective:** Protect public crowdsourced heat reporting (e.g., dry water coolers, unshaded bus stops) from inappropriate or offensive image uploads.
* **Services Involved:** Amazon Rekognition, Amazon S3, Amazon EventBridge, AWS Lambda.
* **Key Components:**
  * **Direct S3 Upload:** Client-side resizing and JPEG re-encoding (stripping EXIF/GPS data) uploaded via presigned PUT.
  * **Asynchronous Moderation:** S3 ObjectCreated triggers Lambda via EventBridge to call `DetectModerationLabels`.
  * **Auto-Triage:** Approved images receive an S3 object tag (`moderation=approved`); flagged uploads are permanently deleted within seconds.

### Feature F: Amazon Bedrock Knowledge Bases & S3 Vectors
* **Objective:** Power the AI "Heat Officer" conversational assistant with real Retrieval-Augmented Generation (RAG) backed by official municipal and national heat action guidelines.
* **Services Involved:** Amazon Bedrock (Knowledge Bases, Titan Text Embeddings V2, Foundation Models), Amazon S3 Vectors.
* **Key Components:**
  * **Corpus Ingestion:** Ingests National Disaster Management Authority (NDMA) guidelines and city-specific Heat Action Plans (HAPs).
  * **Low-Cost Vector Store:** Uses Amazon S3 Vectors instead of expensive OpenSearch clusters, keeping idle infrastructure costs at $0.
  * **Grounded Citations:** The model generates briefs with explicit citation brackets (`[S1] Delhi HAP, Page 12`), strictly enforcing numerical verification.

---

## 4. Phase 2 Advanced Extensions & Upgrades

```
                                  ADVANCED EXTENSIONS (PHASE 2)
                                  
   +---------------------+   +---------------------+   +---------------------+
   |    AWS IoT Core     |   |  Amazon Translate   |   |     Amazon SES      |
   | (Street Temp Nodes) |   | (8+ Regional Langs) |   | (HTML Alerts / Push)|
   +----------+----------+   +----------+----------+   +----------+----------+
              |                         |                         |
              +-------------------+     |     +-------------------+
                                  |     |     |
                                  v     v     v
                             +---------------------+
                             |   HeatRelief Core   |
                             +----------+----------+
                                  ^     ^     ^
              +-------------------+     |     +-------------------+
              |                         |                         |
   +----------+----------+   +----------+----------+   +----------+----------+
   |   Amazon Athena &   |   |   Amazon Cognito    |   |   AWS AppSync /     |
   |  Amazon QuickSight  |   |  (RBAC Auth Portal) |   |  API Gateway WSS    |
   | (Executive BI Dash) |   +---------------------+   | (Live Officer Sync) |
   +---------------------+                             +---------------------+
```

### Feature G: Hyper-Local Ground Sensor Grid (AWS IoT Core)
* **What it does:** Ingests real-time telemetry from street-level IoT temperature and humidity sensors installed on municipal infrastructure (light poles, transit hubs).
* **Work in HeatRelief:**
  * Receives MQTT payloads every 60 seconds with ambient temperature, humidity, and calculated Heat Index.
  * Ingests data through IoT Core Rules Engine directly into DynamoDB and triggers AWS Lambda if temperatures breach safety thresholds.
* **Impact:** Eliminates reliance on satellite revisit delays, offering real-time situational awareness during extreme heat waves.

### Feature H: Multi-Lingual Regional Accessibility (Amazon Translate)
* **What it does:** Automated neural translation across Indian scheduled languages.
* **Work in HeatRelief:**
  * Translates daily forecast bulletins and AI recommendations into Marathi, Bengali, Tamil, Telugu, Gujarati, and Kannada.
  * Feeds translated scripts into Amazon Polly to synthesize native audio broadcasts.
* **Impact:** Protects vulnerable migrant labor populations and informal outdoor workers who do not read Hindi or English.

### Feature I: Production-Grade Branded Civic Alerts (Amazon SES)
* **What it does:** Reliable, high-volume transactional email service with custom domain identity.
* **Work in HeatRelief:**
  * Replaces plain-text SNS notifications with responsive, accessible HTML daily heat cards.
  * Embeds warning badges, hydration recommendations, dynamic cooling center maps, and direct emergency helpline contacts.
* **Impact:** Increases citizen trust, prevents messages from landing in spam folders, and improves engagement.

### Feature J: Municipal Decision Intelligence (Amazon Athena + Amazon QuickSight)
* **What it does:** Serverless SQL query engine (Athena) paired with visual Business Intelligence dashboards (QuickSight).
* **Work in HeatRelief:**
  * Athena executes ad-hoc SQL queries against raw and processed Parquet datasets stored in S3 without managing database servers.
  * QuickSight provides municipal commissioners with longitudinal heat trend analysis, canopy loss tracking, and cooling spot coverage gaps across wards.
* **Impact:** Enables data-backed municipal budget justification for urban forestry and cool-roof subsidies.

### Feature K: Role-Based Access Control & Field Verification (Amazon Cognito)
* **What it does:** Managed user identity pools and authentication directories.
* **Work in HeatRelief:**
  * **Citizen Tier:** Anonymous, zero-friction access to public maps and emergency tools.
  * **Ward Officer Tier:** Authenticated portal for municipal field teams to inspect reported broken fountains and dispatch water tankers.
  * **City Planner Tier:** Administrative authorization to approve intervention plans and simulate scenario models.
* **Impact:** Guarantees data integrity and prevents unauthorized modification of official city mitigation plans.

### Feature L: Live Operations Center (AWS AppSync / WebSocket API)
* **What it does:** Managed GraphQL and WebSocket communication for live, bi-directional event streaming.
* **Work in HeatRelief:**
  * Pushes live updates to the Ward Officer map when a citizen submits an emergency heat report or when a cooling shelter reaches capacity.
* **Impact:** Eliminates manual screen refreshes, creating an active, operational command room experience during heat crises.

### Feature M: Perimeter Defense & Anti-Abuse (AWS WAF)
* **What it does:** Cloud-native Web Application Firewall attached to CloudFront and API Gateway.
* **Work in HeatRelief:**
  * Enforces rate-based rules (e.g., maximum 50 requests per 5 minutes per IP).
  * Blocks bot spam on public alert subscription endpoints and image upload routes.
* **Impact:** Protects cloud infrastructure credits from malicious scraping and denial-of-wallet attacks.

---

## 5. Comprehensive AWS Architecture Matrix

| Service | Category | Work in HeatRelief | Estimated Demo Cost |
| :--- | :--- | :--- | :--- |
| **AWS Lambda** | Compute | Serverless API handlers & cron forecasts | Free Tier ($0.00) |
| **Amazon API Gateway** | Networking | API routing, CORS & route throttling | < $0.05 |
| **Amazon DynamoDB** | Database | Stores plans, citizen reports & rate limits | Free Tier ($0.00) |
| **Amazon S3** | Storage | Web hosting, Parquet data, photos & vector docs | < $0.20 |
| **Amazon CloudFront** | Edge CDN | Global HTTPS delivery & caching | Free Tier ($0.00) |
| **Amazon Polly** | Voice AI | Audio heat bulletins (Hindi/English) | Free Tier ($0.00) |
| **Amazon SNS** | Messaging | Filtered email/SMS alert dispatch | Free Tier ($0.00) |
| **Amazon Location** | Geospatial | Vector basemaps & pedestrian route navigation | $0.05 – $0.20 |
| **AWS Batch + Fargate** | Batch Compute | Geospatial raster ETL & model training | $0.50 – $2.00 / run |
| **AWS Step Functions** | Orchestration | City pipeline workflow execution | Free Tier ($0.00) |
| **Amazon Rekognition** | Computer Vision | Inappropriate photo content moderation | ~$0.002 / report |
| **Amazon Bedrock + S3 Vectors** | Generative AI | Knowledge Base RAG for municipal heat officer | ~$0.10 – $1.00 (Titan) |
| **AWS IoT Core** | IoT / Edge | Real-time street temperature sensor streams | Free Tier ($0.00) |
| **Amazon Translate** | NLP | Multi-lingual translation (8+ Indian languages) | Free Tier ($0.00) |
| **Amazon SES** | Email | Branded HTML civic heat bulletins | Free Tier / cents |
| **Amazon Athena** | Analytics | Serverless SQL queries on S3 Parquet files | ~$0.005 / query |
| **Amazon QuickSight** | BI Dashboards | Municipal executive heat risk reports | Free trial / Tiered |
| **Amazon Cognito** | Security / Auth | Role-based authentication (Officer/Planner) | Free Tier (50k MAU) |
| **AWS AppSync / WebSocket** | Real-time | Live incident streaming & shelter status | Free Tier ($0.00) |
| **AWS WAF** | Security | Rate limiting & bot protection at edge | ~$5.00 / mo |

---

## 6. Phased Implementation Roadmap

```
+-----------------------------------------------------------------------------------+
| PHASE 1: HACKATHON & MVP BASELINE (Core Stability & High Visual Impact)           |
+-----------------------------------------------------------------------------------+
  1. Split SNS Topics (Ops vs Citizen Alerts) & Deploy Baseline Stack
  2. Implement Feature A ('Built on AWS' public transparency page at /aws)
  3. Integrate Feature B (Amazon Location monochrome basemap + walking routes)
  4. Launch Feature C (Citizen alert signup UI with filter policies)
  5. Configure Feature F (Bedrock Knowledge Base + S3 Vectors RAG)
  6. Add Feature E (Rekognition moderation for crowdsourced photos)
  7. Deploy Feature D (AWS Batch container pipeline in us-west-2)

+-----------------------------------------------------------------------------------+
| PHASE 2: REGIONAL SCALE & CIVIC ACCESSIBILITY                                     |
+-----------------------------------------------------------------------------------+
  1. Add Amazon Translate for regional languages (Marathi, Bengali, Tamil, etc.)
  2. Upgrade alert delivery to Amazon SES for rich HTML heat cards
  3. Deploy Amazon Cognito for Ward Officer login & report verification
  4. Attach AWS WAF to CloudFront for anti-bot rate limiting

+-----------------------------------------------------------------------------------+
| PHASE 3: MUNICIPAL ENTERPRISE & REAL-TIME SENSING                                 |
+-----------------------------------------------------------------------------------+
  1. Ingest physical street sensor telemetry with AWS IoT Core
  2. Connect Amazon Athena & Amazon QuickSight for municipal executive dashboards
  3. Enable AWS AppSync / WebSockets for live command-center map updates
```

---

## 7. Budget, Privacy & Compliance Guidelines

1. **Strict Credit & Budget Protection:**
   * Configure `AWS Budgets` with `IncludeCredit: false` to monitor gross spend accurately.
   * Avoid always-on cluster resources (e.g., OpenSearch Serverless, NAT Gateways, idle SageMaker endpoints).
   * Restrict Amazon Location API keys to the CloudFront distribution domain and specific allowed referrers.
2. **Citizen Privacy & DPDP Act (India, 2023) Alignment:**
   * Never store raw GPS coordinates for citizen reports; store only anonymized $250\text{m} \times 250\text{m}$ grid cell identifiers.
   * Strip EXIF/geotag metadata from uploaded images client-side before sending to S3.
   * Hash email addresses in application logs and store them only within managed SNS/SES subscription tables.
3. **Graceful Offline & Fallback Modes:**
   * Every AWS feature must degrade gracefully (e.g., if Bedrock is unreachable, fall back to rule-based templates; if Amazon Location keys are absent, fall back to local canvas grids).
   * All automated checks must be clearly labeled as automated on the user interface.
