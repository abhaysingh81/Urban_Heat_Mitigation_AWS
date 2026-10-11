#!/usr/bin/env bash
# Build BLOG/ and publish it to S3 + CloudFront (or S3 static website when pending CloudFront verification).
#   scripts/deploy_blog.sh [stack-name] [region]
#   ENABLE_CLOUDFRONT=1 scripts/deploy_blog.sh ...
# Re-run any time: the stack update is a no-op when unchanged, files are synced, index.html is invalidated.
set -euo pipefail

STACK="${1:-heatrelief-blog}"
REGION="${2:-${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}}"
REGION="${REGION:-us-east-1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

aws sts get-caller-identity >/dev/null

echo "==> Building blog"
(cd "$ROOT/BLOG" && npm ci --silent && npm run build)

# If previous attempt failed into ROLLBACK_COMPLETE, delete it so it can be cleanly created
STATUS=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].StackStatus" --output text 2>/dev/null || true)
if [ "${STATUS}" = "ROLLBACK_COMPLETE" ]; then
  echo "==> Stack $STACK is in ROLLBACK_COMPLETE state from a prior failed attempt."
  echo "==> Deleting failed stack before re-creating..."
  aws cloudformation delete-stack --region "$REGION" --stack-name "$STACK"
  aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$STACK"
  echo "==> Failed stack deleted. Proceeding with deployment."
fi

ENABLE_CF="$([ "${ENABLE_CLOUDFRONT:-0}" = "1" ] && echo true || echo false)"
echo "==> Deploying stack $STACK in $REGION (EnableCloudFront=${ENABLE_CF})"
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file "$ROOT/infra/blog-hosting.yaml" --no-fail-on-empty-changeset \
  --parameter-overrides "EnableCloudFront=${ENABLE_CF}"

out() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
BUCKET="$(out BlogBucketName)"
DIST="$(out BlogDistributionId)"
URL="$(out BlogUrl)"

echo "==> Uploading to s3://$BUCKET"
# hashed assets never change: cache for a year; index.html must always revalidate
aws s3 sync "$ROOT/BLOG/dist/assets" "s3://$BUCKET/assets" --region "$REGION" --delete \
  --cache-control "public,max-age=31536000,immutable"
aws s3 cp "$ROOT/BLOG/dist/index.html" "s3://$BUCKET/index.html" --region "$REGION" \
  --cache-control "no-cache" --content-type "text/html; charset=utf-8"

if [ -n "$DIST" ] && [ "$DIST" != "None" ]; then
  aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/index.html" "/" >/dev/null || true
fi

echo "==> Live at $URL"
