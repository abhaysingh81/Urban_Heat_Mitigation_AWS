# Build from the repo root:  sam build   (see infra/template.yaml)
FROM public.ecr.aws/lambda/python:3.11

COPY requirements-lambda.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements-lambda.txt

COPY api ${LAMBDA_TASK_ROOT}/api
COPY agent ${LAMBDA_TASK_ROOT}/agent
COPY lambdas ${LAMBDA_TASK_ROOT}/lambdas
COPY models ${LAMBDA_TASK_ROOT}/models
COPY pipeline/__init__.py pipeline/config.py ${LAMBDA_TASK_ROOT}/pipeline/
COPY pipeline/real/__init__.py pipeline/real/gridspec.py pipeline/real/weather.py ${LAMBDA_TASK_ROOT}/pipeline/real/
COPY data ${LAMBDA_TASK_ROOT}/data

# Default: the API. The forecast job overrides this command in template.yaml.
CMD ["api.lambda_handler.handler"]
