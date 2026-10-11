#!/usr/bin/env bash
# One-command deploy of the whole HeatRelief stack.
#   scripts/deploy.sh <alert-email> [bedrock-model-id]
#   OFFICER_TOKEN=<secret> scripts/deploy.sh ...        # require a token to approve plans
#   ENABLE_LOCATION_MAP=1 scripts/deploy.sh ...         # Amazon Location basemap + walking routes (else CARTO)
#   ENABLE_KNOWLEDGE_BASE=1 scripts/deploy.sh ...       # Bedrock Knowledge Base for guidance (else local file)
#   KB_MIN_SCORE=0.5 ...                                # knowledge-base relevance floor (default 0.4)
#   ENABLE_TRANSLATE=0 ...                              # switch Amazon Translate off (it is on by default)
#   SES_FROM_EMAIL=alerts@example.org ...               # Amazon SES HTML alert cards (else SNS plain text)
#   ENABLE_COGNITO=1 ...                                # Cognito sign-in for officers and planners
#   ENABLE_LIVE_UPDATES=1 ...                           # WebSocket API: live reports on the officer page
#   ENABLE_IOT_SENSORS=1 ...                            # AWS IoT Core rules and tables for street sensors
#   ENABLE_ANALYTICS=1 ...                              # Glue tables + Athena workgroup (for QuickSight)
#   ENABLE_WAF=1 ...                                    # AWS WAF, with the API served through CloudFront
#   ENABLE_SECRETS=1 ...                                # officer token generated in AWS Secrets Manager
#   ENABLE_BATCH_BRIEFS=1 ...                           # nightly ward briefs with Bedrock batch inference
#   ENABLE_SYNTHETICS=1 ...                             # CloudWatch Synthetics uptime canary + alarm
#   WHATSAPP_PHONE_NUMBER_ID=phone-number-id-... ...    # WhatsApp heat alerts (End User Messaging Social)
#   CONNECT_INSTANCE_ID=... CONNECT_CONTACT_FLOW_ID=... # heat-alert phone calls (Amazon Connect)
# Use the same switches on every run: a switch left out removes that feature's resources.
# Requires: AWS credentials, Docker, SAM CLI, Node 20+.
set -euo pipefail
cd "$(dirname "$0")/.."
EMAIL="${1:-}"; MODEL="${2:-}"; TOKEN="${OFFICER_TOKEN:-}"
STACK="heatrelief"; REGION="us-east-1"   # must match infra/samconfig.toml
# every aws/sam call below targets the stack's region, whatever the CLI profile defaults to
export AWS_DEFAULT_REGION="${REGION}" AWS_REGION="${REGION}"

# SAM ignores 'Key=' with an empty value, so only pass parameters that are set
PARAMS=()
[ -n "${EMAIL}" ] && PARAMS+=("AlertEmail=${EMAIL}")
[ -n "${MODEL}" ] && PARAMS+=("BedrockModelId=${MODEL}")
if [ "${ENABLE_SECRETS:-0}" = "1" ]; then
  PARAMS+=('OfficerToken=""')     # the token lives in Secrets Manager; an env value would override it
  [ -n "${TOKEN}" ] && echo "Note: OFFICER_TOKEN is ignored with ENABLE_SECRETS=1 (a token is generated in Secrets Manager)."
else
  [ -n "${TOKEN}" ] && PARAMS+=("OfficerToken=${TOKEN}")
fi
# explicit true/false, so turning a feature off on a later run really removes it
PARAMS+=("EnableLocationMap=$([ "${ENABLE_LOCATION_MAP:-0}" = "1" ] && echo true || echo false)")
PARAMS+=("EnableKnowledgeBase=$([ "${ENABLE_KNOWLEDGE_BASE:-0}" = "1" ] && echo true || echo false)")
PARAMS+=("AlertMinLevel=${ALERT_MIN_LEVEL:-orange}")   # always set, so the list is never empty
flag() { [ "${1}" = "1" ] && echo true || echo false; }
PARAMS+=("KbMinScore=${KB_MIN_SCORE:-0.4}")
PARAMS+=("EnableTranslate=$(flag "${ENABLE_TRANSLATE:-1}")")
PARAMS+=("EnableCognito=$(flag "${ENABLE_COGNITO:-0}")")
PARAMS+=("EnableLiveUpdates=$(flag "${ENABLE_LIVE_UPDATES:-0}")")
PARAMS+=("EnableIotSensors=$(flag "${ENABLE_IOT_SENSORS:-0}")")
PARAMS+=("EnableAnalytics=$(flag "${ENABLE_ANALYTICS:-0}")")
PARAMS+=("EnableWaf=$(flag "${ENABLE_WAF:-0}")")
# an empty value is dropped by SAM, which would keep an old sender; '""' clears it explicitly
PARAMS+=("SesFromEmail=${SES_FROM_EMAIL:-\"\"}")
PARAMS+=("EnableSecrets=$(flag "${ENABLE_SECRETS:-0}")")
PARAMS+=("EnableBatchBriefs=$(flag "${ENABLE_BATCH_BRIEFS:-0}")")
PARAMS+=("WhatsAppPhoneNumberId=${WHATSAPP_PHONE_NUMBER_ID:-\"\"}")
[ -n "${WHATSAPP_OPTIN_TEMPLATE:-}" ] && PARAMS+=("WhatsAppOptinTemplate=${WHATSAPP_OPTIN_TEMPLATE}")
[ -n "${WHATSAPP_ALERT_TEMPLATE:-}" ] && PARAMS+=("WhatsAppAlertTemplate=${WHATSAPP_ALERT_TEMPLATE}")
[ -n "${WHATSAPP_LANGUAGE:-}" ] && PARAMS+=("WhatsAppLanguage=${WHATSAPP_LANGUAGE}")
PARAMS+=("ConnectInstanceId=${CONNECT_INSTANCE_ID:-\"\"}")
PARAMS+=("ConnectContactFlowId=${CONNECT_CONTACT_FLOW_ID:-\"\"}")
PARAMS+=("ConnectSourcePhoneNumber=${CONNECT_SOURCE_PHONE_NUMBER:-\"\"}")
PARAMS+=("VoiceMinLevel=${VOICE_MIN_LEVEL:-red}")

out() { aws cloudformation describe-stacks --stack-name "${STACK}" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text 2>/dev/null || true; }

# uptime canary (CloudWatch Synthetics): its code zip must already be in the data bucket when the
# canary is created. On a stack that exists, upload first; on the very first deploy the bucket is
# created by pass 1 and the canary is added in pass 2 below.
CANARY_KEY='""'; CANARY_ZIP=""
if [ "${ENABLE_SYNTHETICS:-0}" = "1" ]; then
  mkdir -p .aws-sam/canary; CANARY_ZIP=".aws-sam/canary/heartbeat.zip"
  python3 - "${CANARY_ZIP}" <<'PY'
import sys, zipfile
info = zipfile.ZipInfo("python/heartbeat.py", date_time=(2026, 1, 1, 0, 0, 0))   # fixed time: same code, same zip
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr(info, open("infra/canary/python/heartbeat.py", "rb").read())
PY
  CANARY_S3_KEY="synthetics/heartbeat-$(shasum -a 256 "${CANARY_ZIP}" | cut -c1-12).zip"
  EXISTING_DATA_BUCKET="$(out DataBucketName)"
  if [ -n "${EXISTING_DATA_BUCKET}" ] && [ "${EXISTING_DATA_BUCKET}" != "None" ]; then
    aws s3 cp "${CANARY_ZIP}" "s3://${EXISTING_DATA_BUCKET}/${CANARY_S3_KEY}" --only-show-errors
    CANARY_KEY="${CANARY_S3_KEY}"
  fi
fi

sam build -t infra/template.yaml
sam deploy -t infra/template.yaml --config-file infra/samconfig.toml --no-fail-on-empty-changeset \
  --parameter-overrides "${PARAMS[*]} CanaryCodeKey=${CANARY_KEY}"
API_URL="$(out ApiUrl)"; BUCKET="$(out FrontendBucketName)"; DIST="$(out FrontendDistributionId)"
DATA_BUCKET="$(out DataBucketName)"
FRONTEND_URL="$(out FrontendUrl)"

# first deploy with the canary on: the bucket exists now, so upload the code and add the canary
if [ -n "${CANARY_ZIP}" ] && [ "${CANARY_KEY}" = '""' ]; then
  aws s3 cp "${CANARY_ZIP}" "s3://${DATA_BUCKET}/${CANARY_S3_KEY}" --only-show-errors
  CANARY_KEY="${CANARY_S3_KEY}"
fi

# the CloudFront URL only exists after the first deploy: allow it in the API's CORS list
sam deploy -t infra/template.yaml --config-file infra/samconfig.toml --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides "${PARAMS[*]} CanaryCodeKey=${CANARY_KEY} ExtraCorsOrigin=${FRONTEND_URL}"

# With WAF the browser talks to the API through CloudFront (same address as the site), so the
# firewall sees every request; the API then refuses calls made straight to API Gateway.
SITE_API="${API_URL}"
[ "${ENABLE_WAF:-0}" = "1" ] && SITE_API="${FRONTEND_URL}"

# data lake: processed features, model artifacts, model card
aws s3 sync data/processed "s3://${DATA_BUCKET}/processed" --exclude "*" --include "*/features_real.parquet" \
  --include "*/wards.geojson" --include "*/cooling_spots.json" --include "*/data_card.json"
aws s3 sync models/artifacts/real "s3://${DATA_BUCKET}/model"

# knowledge base: upload the guidance documents, then index them (re-run whenever documents change)
if [ "${ENABLE_KNOWLEDGE_BASE:-0}" = "1" ]; then
  KB_ID="$(out KnowledgeBaseId)"; DS_ID="$(out KbDataSourceId)"
  aws s3 sync agent/guidance "s3://${DATA_BUCKET}/kb-docs" --delete --exclude "*" \
    --include "*.md" --include "*.txt" --include "*.pdf" --include "*.html" --include "*.docx"
  JOB="$(aws bedrock-agent start-ingestion-job --knowledge-base-id "${KB_ID}" --data-source-id "${DS_ID}" \
    --query ingestionJob.ingestionJobId --output text)"
  KB_STATUS="STARTING"
  for _ in $(seq 1 60); do
    KB_STATUS="$(aws bedrock-agent get-ingestion-job --knowledge-base-id "${KB_ID}" --data-source-id "${DS_ID}" \
      --ingestion-job-id "${JOB}" --query ingestionJob.status --output text)"
    case "${KB_STATUS}" in COMPLETE|FAILED|STOPPED) break ;; esac
    sleep 5
  done
  echo "Knowledge base ingestion: ${KB_STATUS}"
  aws bedrock-agent get-ingestion-job --knowledge-base-id "${KB_ID}" --data-source-id "${DS_ID}" \
    --ingestion-job-id "${JOB}" --query '{statistics: ingestionJob.statistics, failureReasons: ingestionJob.failureReasons}'
  [ "${KB_STATUS}" = "COMPLETE" ] || echo "WARNING: guidance documents were not indexed; briefs use the local guidance file until this succeeds."
fi

# analytics: one clean, partitioned copy of the grid features for Athena / QuickSight
if [ "${ENABLE_ANALYTICS:-0}" = "1" ]; then
  for CITY in new_delhi mumbai jaipur bengaluru; do
    aws s3 cp "data/processed/${CITY}/features_real.parquet" \
      "s3://${DATA_BUCKET}/analytics/features/city=${CITY}/features_real.parquet" --only-show-errors
  done
fi

# basemap key: its value is not a CloudFormation attribute, so read it from Amazon Location
MAP_KEY=""
if [ "${ENABLE_LOCATION_MAP:-0}" = "1" ]; then
  MAP_KEY="$(aws location describe-key --key-name "$(out MapApiKeyName)" --query Key --output text)"
fi

# frontend
( cd frontend && npm ci --no-audit --no-fund && VITE_API_BASE_URL="${SITE_API}" \
    VITE_AWS_LOCATION_KEY="${MAP_KEY}" VITE_AWS_REGION="${REGION}" npm run build )
aws s3 sync frontend/dist "s3://${BUCKET}" --delete --exclude "alert-maps/*"   # keep the daily alert maps
aws cloudfront create-invalidation --distribution-id "${DIST}" --paths "/*" >/dev/null

echo "API:      ${SITE_API}"
echo "Frontend: ${FRONTEND_URL}"
[ "${ENABLE_COGNITO:-0}" = "1" ] && echo "Cognito user pool: $(out UserPoolId)   (create staff users: see docs/SETUP_AND_DEPLOYMENT.md)"
[ "${ENABLE_LIVE_UPDATES:-0}" = "1" ] && echo "Live updates:      $(out LiveUpdatesUrl)"
[ "${ENABLE_ANALYTICS:-0}" = "1" ] && echo "Athena:            workgroup $(out AthenaWorkGroup), database $(out AthenaDatabase)"
[ -n "${SES_FROM_EMAIL:-}" ] && echo "SES:               open the verification email sent to ${SES_FROM_EMAIL} and click the link"
[ "${ENABLE_SECRETS:-0}" = "1" ] && echo "Officer token:     aws secretsmanager get-secret-value --secret-id $(out OfficerTokenSecretArn) --query SecretString --output text"
[ "${ENABLE_SYNTHETICS:-0}" = "1" ] && echo "Uptime canary:     heatrelief-uptime (CloudWatch > Synthetics), alarm to the ops topic"
[ "${ENABLE_BATCH_BRIEFS:-0}" = "1" ] && [ -z "${MODEL}" ] && echo "WARNING: ENABLE_BATCH_BRIEFS needs a Bedrock model id (second argument); no batch job was created."
echo "Warm the API before recording:  curl -s ${SITE_API}/health && curl -s '${SITE_API}/api/v1/risk/wards?city=new_delhi' >/dev/null"
