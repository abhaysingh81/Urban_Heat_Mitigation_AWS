"""AWS Lambda entrypoint: the FastAPI app behind API Gateway (HTTP API)."""

from mangum import Mangum

from api.main import app

handler = Mangum(app, lifespan="off")
