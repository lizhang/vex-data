"""S3 helpers for raw JSON and curated Parquet."""

import io
import json
from datetime import date
from typing import Any

import boto3
import pyarrow as pa
import pyarrow.parquet as pq

from app.config import settings


def _client():
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("s3", **kwargs)


# ── Path helpers ───────────────────────────────────────────────────────────

def raw_key(entity: str, run_date: date, timestamp: str) -> str:
    return f"{settings.s3_raw_prefix}/{entity}/dt={run_date.isoformat()}/{timestamp}.json"


def curated_key(entity: str, run_date: date, timestamp: str) -> str:
    return f"{settings.s3_curated_prefix}/{entity}/dt={run_date.isoformat()}/{timestamp}.parquet"


def curated_s3_location(entity: str) -> str:
    return f"s3://{settings.s3_bucket}/{settings.s3_curated_prefix}/{entity}/"


# ── Raw JSON ───────────────────────────────────────────────────────────────

def upload_json(data: list | dict, key: str) -> None:
    body = json.dumps(data, default=str).encode("utf-8")
    _client().put_object(Bucket=settings.s3_bucket, Key=key, Body=body)


def download_json(key: str) -> Any:
    obj = _client().get_object(Bucket=settings.s3_bucket, Key=key)
    return json.loads(obj["Body"].read())


def list_raw_keys(entity: str, run_date: date | None = None) -> list[str]:
    prefix = f"{settings.s3_raw_prefix}/{entity}/"
    if run_date:
        prefix += f"dt={run_date.isoformat()}/"
    return _list_keys(prefix)


# ── Curated Parquet ────────────────────────────────────────────────────────

def upload_parquet(table: pa.Table, key: str) -> None:
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)
    _client().put_object(Bucket=settings.s3_bucket, Key=key, Body=buf.getvalue())


def list_curated_keys(entity: str, run_date: date | None = None) -> list[str]:
    prefix = f"{settings.s3_curated_prefix}/{entity}/"
    if run_date:
        prefix += f"dt={run_date.isoformat()}/"
    return _list_keys(prefix)


# ── Internal ───────────────────────────────────────────────────────────────

def _list_keys(prefix: str) -> list[str]:
    s3 = _client()
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys
