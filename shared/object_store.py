from __future__ import annotations

import io
import os

import boto3
import pandas as pd
from botocore.config import Config


def _client():
    endpoint = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
    access_key = os.getenv("AWS_ACCESS_KEY_ID", os.getenv("MINIO_ROOT_USER", "minio"))
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", os.getenv("MINIO_ROOT_PASSWORD", "minio123"))
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        config=Config(s3={"addressing_style": "path"}),
    )


def read_csv(bucket: str, key: str) -> pd.DataFrame:
    response = _client().get_object(Bucket=bucket, Key=key)
    return pd.read_csv(io.BytesIO(response["Body"].read()))


def put_text(bucket: str, key: str, text: str, content_type: str = "text/plain") -> str:
    _client().put_object(
        Bucket=bucket,
        Key=key,
        Body=text.encode("utf-8"),
        ContentType=content_type,
    )
    return f"s3://{bucket}/{key}"
