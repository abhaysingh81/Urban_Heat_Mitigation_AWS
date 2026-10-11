#!/usr/bin/env bash
# Deploy the cloud data pipeline (AWS Batch on Fargate + Step Functions) and push its image.
#   scripts/deploy_pipeline.sh [ops-email]
#   STAC_URL=https://planetarycomputer.microsoft.com/api/stac/v1 scripts/deploy_pipeline.sh ...
#   CAPACITY_TYPE=FARGATE scripts/deploy_pipeline.sh ...      # on-demand instead of Fargate Spot
# Requires: AWS credentials, Docker. Runs in us-west-2, next to the Landsat and Sentinel-2 archives.
set -euo pipefail
cd "$(dirname "$0")/.."
EMAIL="${1:-}"
STACK="heatrelief-pipeline"; REGION="us-west-2"
export AWS_DEFAULT_REGION="${REGION}" AWS_REGION="${REGION}"

PARAMS=("StacUrl=${STAC_URL:-https://earth-search.aws.element84.com/v1}")
PARAMS+=("CapacityType=${CAPACITY_TYPE:-FARGATE_SPOT}")   # CAPACITY_TYPE=FARGATE for uninterrupted on-demand tasks
[ -n "${EMAIL}" ] && PARAMS+=("OpsEmail=${EMAIL}")

aws cloudformation deploy --stack-name "${STACK}" --template-file infra/pipeline-template.yaml \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset --parameter-overrides "${PARAMS[@]}"

out() { aws cloudformation describe-stacks --stack-name "${STACK}" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
REPO="$(out PipelineRepositoryUri)"; MACHINE="$(out PipelineStateMachineArn)"; BUCKET="$(out PipelineBucketName)"

# image: the job definitions run <repo>:latest
aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO%%/*}"
# host networking: the default Docker bridge is IPv4-only, which can be far slower to PyPI
docker build --network host -f pipeline/Dockerfile -t "${REPO}:latest" .
docker push "${REPO}:latest"

RUN_ID="real-v1-$(date -u +%Y%m%d)"
echo
echo "Pipeline bucket: ${BUCKET}"
echo "Start a run (all four cities, about 30-60 minutes):"
echo "  aws stepfunctions start-execution --region ${REGION} --state-machine-arn ${MACHINE} \\"
echo "    --name ${RUN_ID}-\$(date -u +%H%M%S) \\"
echo "    --input '{\"cities\":[\"new_delhi\",\"mumbai\",\"jaipur\",\"bengaluru\"],\"run_id\":\"${RUN_ID}\"}'"
echo "When it succeeds, copy the result into the repo and redeploy the app:"
echo "  AWS_DEFAULT_REGION=${REGION} python scripts/promote_pipeline_run.py --bucket ${BUCKET} --run-id ${RUN_ID}"
echo "  pytest -q && ./scripts/deploy.sh <alert-email> <bedrock-model-id>"
