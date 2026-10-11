# Data pipeline image for AWS Batch on Fargate (Feature D). Build from the repo root:
#   docker build -f pipeline/Dockerfile -t heatrelief-pipeline .
# rasterio/pyproj/shapely wheels bundle GDAL, PROJ and GEOS, so no compiler or GDAL packages are needed;
# libexpat is the one shared library the rasterio wheel expects from the system.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-satellite.txt ./
RUN pip install --no-cache-dir --only-binary=:all: --default-timeout=120 --retries 10 \
      -r requirements.txt -r requirements-satellite.txt

COPY pipeline/ pipeline/
COPY models/ models/
# boundaries, masks and the current dataset (data/raw and data/runtime are excluded by .dockerignore)
COPY data/ data/

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    AWS_REQUEST_PAYER=requester \
    STAC_URL=https://earth-search.aws.element84.com/v1 \
    GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR \
    GDAL_HTTP_MAX_RETRY=4 \
    GDAL_HTTP_RETRY_DELAY=2

# The state machine overrides this with the city / the training module.
CMD ["python", "-m", "pipeline.real.build_dataset", "--help"]
