#!/usr/bin/env bash
# Build BLOG/ and publish it to S3 + CloudFront (stack: infra/blog-hosting.yaml).
#   scripts/deploy_blog.sh [stack-name] [region]
# Re-run any time: the stack update is a no-op when unchanged, files are synced, index.html is invalidated.
set -euo pipefail

STACK="${1:-heatrelief-blog}"
REGION="${2:-${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}}"
REGION="${REGION:-ap-south-1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

aws sts get-caller-identity >/dev/null

echo "==> Building blog"
(cd "$ROOT/BLOG" && npm ci --silent && npm run build)

echo "==> Deploying stack $STACK in $REGION"
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file "$ROOT/infra/blog-hosting.yaml" --no-fail-on-empty-changeset

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

aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/index.html" "/" >/dev/null

echo "==> Live at $URL  (a brand-new distribution can take a few minutes to start serving)"
