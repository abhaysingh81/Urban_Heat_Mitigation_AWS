#!/usr/bin/env bash
# After the wider-bbox rebuild of the real-data cities: wait for the builds, retry
# failed OSM tiles, retrain the model (predictions for every new cell), and rebuild
# the city-boundary masks. Safe to re-run: every stage is cached on disk.
set -uo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate

echo "[$(date +%T)] waiting for running builds…"
while pgrep -f "pipeline.real.build_dataset" >/dev/null; do sleep 20; done

echo "[$(date +%T)] retrying OSM tiles that failed (cached tiles are reused)"
for c in jaipur new_delhi bengaluru; do
  python -m pipeline.real.build_dataset "$c" --refresh osm 2>&1 | grep -E "osm|wrote" || true
done

echo "[$(date +%T)] retraining the real-data model"
python -m models.train_real 2>&1 | grep -vE "RuntimeWarning|nanmean|nanmedian" | tail -25
status=${PIPESTATUS[0]}
echo "[$(date +%T)] train_real exit ${status}"

echo "[$(date +%T)] rebuilding boundary masks"
python -m pipeline.real.boundary new_delhi jaipur bengaluru mumbai
echo "[$(date +%T)] done"
