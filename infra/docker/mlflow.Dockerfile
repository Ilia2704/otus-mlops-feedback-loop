FROM ghcr.io/mlflow/mlflow:v2.17.2

# The upstream MLflow image does not ship the optional S3 client dependency.
RUN pip install --no-cache-dir boto3==1.35.76
