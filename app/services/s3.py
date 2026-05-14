"""S3 helpers for raw JSON and curated Parquet."""

import io
import json
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

def _partition_suffix(season_id: int, program_id: int, event_id: int | None) -> str:
    suffix = f"p_season_id={season_id}/p_program_id={program_id}/"
    if event_id is not None:
        suffix += f"p_event_id={event_id}/"
    return suffix


def raw_key(
    entity: str,
    season_id: int,
    program_id: int,
    timestamp: str,
    event_id: int | None = None,
) -> str:
    partition = _partition_suffix(season_id, program_id, event_id)
    return f"{settings.s3_raw_prefix}/{entity}/{partition}{timestamp}.json"


def curated_key(
    entity: str,
    season_id: int,
    program_id: int,
    timestamp: str,
    event_id: int | None = None,
) -> str:
    partition = _partition_suffix(season_id, program_id, event_id)
    return f"{settings.s3_curated_prefix}/{entity}/{partition}{timestamp}.parquet"


def curated_s3_location(entity: str) -> str:
    return f"s3://{settings.s3_bucket}/{settings.s3_curated_prefix}/{entity}/"


# ── Raw JSON ───────────────────────────────────────────────────────────────

def upload_json(data: list | dict, key: str) -> None:
    body = json.dumps(data, default=str).encode("utf-8")
    _client().put_object(Bucket=settings.s3_bucket, Key=key, Body=body)


def download_json(key: str) -> Any:
    obj = _client().get_object(Bucket=settings.s3_bucket, Key=key)
    return json.loads(obj["Body"].read())


def list_raw_keys(
    entity: str,
    season_id: int | None = None,
    program_id: int | None = None,
    event_id: int | None = None,
) -> list[str]:
    prefix = _curated_or_raw_prefix(settings.s3_raw_prefix, entity, season_id, program_id, event_id)
    return _list_keys(prefix)


# ── Curated Parquet ────────────────────────────────────────────────────────

def upload_parquet(table: pa.Table, key: str) -> None:
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)
    _client().put_object(Bucket=settings.s3_bucket, Key=key, Body=buf.getvalue())


def list_curated_keys(
    entity: str,
    season_id: int | None = None,
    program_id: int | None = None,
    event_id: int | None = None,
) -> list[str]:
    prefix = _curated_or_raw_prefix(settings.s3_curated_prefix, entity, season_id, program_id, event_id)
    return _list_keys(prefix)


# ── Internal ───────────────────────────────────────────────────────────────

def _curated_or_raw_prefix(
    base_prefix: str,
    entity: str,
    season_id: int | None,
    program_id: int | None,
    event_id: int | None,
) -> str:
    prefix = f"{base_prefix}/{entity}/"
    if season_id is None:
        return prefix
    prefix += f"p_season_id={season_id}/"
    if program_id is None:
        return prefix
    prefix += f"p_program_id={program_id}/"
    if event_id is None:
        return prefix
    prefix += f"p_event_id={event_id}/"
    return prefix


def _list_keys(prefix: str) -> list[str]:
    s3 = _client()
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def delete_keys(keys: list[str]) -> None:
    """Batch-delete S3 objects. Used by `--clean` in scripts."""
    if not keys:
        return
    s3 = _client()
    for chunk_start in range(0, len(keys), 1000):
        chunk = keys[chunk_start:chunk_start + 1000]
        s3.delete_objects(
            Bucket=settings.s3_bucket,
            Delete={"Objects": [{"Key": k} for k in chunk]},
        )
