#!/usr/bin/env bash
# One-command deploy of the whole HeatRelief stack.
#   scripts/deploy.sh <alert-email> [bedrock-model-id]
# Requires: AWS credentials, Docker, SAM CLI, Node 20+.
set -euo pipefail
cd "$(dirname "$0")/.."
EMAIL="${1:-}"; MODEL="${2:-}"

sam build -t infra/template.yaml
sam deploy -t infra/template.yaml --config-file infra/samconfig.toml \
  --parameter-overrides "AlertEmail=${EMAIL} BedrockModelId=${MODEL}"

out() { aws cloudformation describe-stacks --stack-name heatrelief \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
API_URL="$(out ApiUrl)"; BUCKET="$(out FrontendBucketName)"; DIST="$(out FrontendDistributionId)"
DATA_BUCKET="$(out DataBucketName)"

# data lake: processed features, model artifacts, model card
aws s3 sync data/processed "s3://${DATA_BUCKET}/processed" --exclude "*" --include "*/features_real.parquet" \
  --include "*/wards.geojson" --include "*/cooling_spots.json" --include "*/data_card.json"
aws s3 sync models/artifacts/real "s3://${DATA_BUCKET}/model"

# frontend
( cd frontend && npm ci --no-audit --no-fund && VITE_API_BASE_URL="${API_URL}" npm run build )
aws s3 sync frontend/dist "s3://${BUCKET}" --delete
aws cloudfront create-invalidation --distribution-id "${DIST}" --paths "/*" >/dev/null

echo "API:      ${API_URL}"
echo "Frontend: $(out FrontendUrl)"
echo "Warm the API before recording:  curl -s ${API_URL}/health && curl -s '${API_URL}/api/v1/risk/wards?city=new_delhi' >/dev/null"
