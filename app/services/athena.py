"""Synchronous Athena execution: submit, poll, fetch."""

from __future__ import annotations

import time
from pathlib import Path

import boto3

from app.config import settings


TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}
POLL_INTERVAL_SECONDS = 2


class AthenaTimeoutError(Exception):
    def __init__(self, execution_id: str, timeout: int):
        self.execution_id = execution_id
        self.timeout = timeout
        super().__init__(f"Athena query {execution_id} did not finish within {timeout}s")


class AthenaQueryError(Exception):
    def __init__(self, execution_id: str, state: str, state_reason: str):
        self.execution_id = execution_id
        self.state = state
        self.state_reason = state_reason
        super().__init__(f"Athena query {execution_id} ended in state {state}: {state_reason}")


def _client():
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("athena", **kwargs)


def execute_query(
    sql: str,
    params: list,
    output_location: str,
    workgroup: str,
    timeout: int = 60,
    fetch_results: bool = True,
) -> tuple[list[dict[str, str | None]], list[str]]:
    """Submit SQL with parameters, poll until terminal, fetch rows.

    Returns (rows, columns). When fetch_results is False (DDL queries) returns ([], []).
    Raises AthenaTimeoutError or AthenaQueryError on non-success terminal states.
    """
    client = _client()

    start_kwargs = {
        "QueryString": sql,
        "ResultConfiguration": {"OutputLocation": output_location},
        "WorkGroup": workgroup,
    }
    string_params = [str(p) for p in params]
    if string_params:
        start_kwargs["ExecutionParameters"] = string_params

    execution_id = client.start_query_execution(**start_kwargs)["QueryExecutionId"]

    deadline = time.monotonic() + timeout
    while True:
        status = client.get_query_execution(QueryExecutionId=execution_id)["QueryExecution"]["Status"]
        state = status["State"]
        if state in TERMINAL_STATES:
            break
        if time.monotonic() >= deadline:
            raise AthenaTimeoutError(execution_id, timeout)
        time.sleep(POLL_INTERVAL_SECONDS)

    if state != "SUCCEEDED":
        raise AthenaQueryError(execution_id, state, status.get("StateChangeReason", ""))

    if not fetch_results:
        return [], []

    return _fetch_all_results(client, execution_id)


def _fetch_all_results(client, execution_id: str) -> tuple[list[dict[str, str | None]], list[str]]:
    paginator = client.get_paginator("get_query_results")
    rows: list[dict[str, str | None]] = []
    columns: list[str] = []
    header_skipped = False

    for page in paginator.paginate(QueryExecutionId=execution_id):
        if not columns:
            columns = [col["Name"] for col in page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]

        for row in page["ResultSet"]["Rows"]:
            if not header_skipped:
                header_skipped = True
                continue
            values = [cell.get("VarCharValue") if cell else None for cell in row["Data"]]
            rows.append({col: val for col, val in zip(columns, values)})

    return rows, columns


def create_tables(
    db: str,
    ddl_dir: str | Path,
    output_location: str,
    workgroup: str,
) -> list[str]:
    """Iterate *.sql files in ddl_dir, execute each DDL, return table names."""
    ddl_path = Path(ddl_dir)
    sql_files = sorted(ddl_path.glob("*.sql"))

    tables: list[str] = []
    for sql_file in sql_files:
        ddl = sql_file.read_text(encoding="utf-8")
        scoped_ddl = _scope_ddl_to_database(ddl, db)
        execute_query(
            sql=scoped_ddl,
            params=[],
            output_location=output_location,
            workgroup=workgroup,
            fetch_results=False,
        )
        tables.append(sql_file.stem)

    return tables


def _scope_ddl_to_database(ddl: str, db: str) -> str:
    stripped = ddl.lstrip()
    upper = stripped.upper()
    prefix = "CREATE EXTERNAL TABLE IF NOT EXISTS "
    plain = "CREATE EXTERNAL TABLE "
    if upper.startswith(prefix):
        rest = stripped[len(prefix):]
        return f"CREATE EXTERNAL TABLE IF NOT EXISTS {db}.{rest}"
    if upper.startswith(plain):
        rest = stripped[len(plain):]
        return f"CREATE EXTERNAL TABLE IF NOT EXISTS {db}.{rest}"
    return ddl
