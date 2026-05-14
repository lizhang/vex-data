---
name: logging
description: Use this skill whenever adding, modifying, or reviewing logging in this VEX Data API project. Triggers when the user mentions logs/logging/observability, when adding a new HTTP route, when adding a new external call (boto3, httpx, any AWS or third-party service), when writing a new service module under app/services/, or when changing app/main.py / middleware. Defines the structlog-based JSON logging conventions, the X-Request-Id → API Gateway requestId → UUID4 priority for request_id, the start/end event-name pattern, and the contextvars propagation rule.
---

# Logging Conventions

This project uses **structlog** to emit one JSON object per log event to stdout. CloudWatch picks it up automatically on Lambda; uvicorn surfaces it locally.

## Configuration

- `app/logging_config.py` — `configure_logging()` is idempotent and called once from `app/main.py`.
- Processor chain: `merge_contextvars` → `add_log_level` → `TimeStamper(iso, utc)` → `StackInfoRenderer` → `format_exc_info` → `JSONRenderer`.
- Logger factory: `PrintLoggerFactory(file=sys.stdout)`. **Do not** add a file handler — Lambda's filesystem is read-only outside `/tmp`.

## Per-request id

Every request gets a `request_id` bound to a `contextvar` by `app/middleware/request_logging.py`. Resolution priority (see `_resolve_request_id`):

1. `X-Request-Id` request header → `request_id_source = "header"`
2. Mangum scope `aws.event["requestContext"]["requestId"]` (API Gateway request id) → `request_id_source = "api_gateway"`
3. `uuid.uuid4().hex` → `request_id_source = "generated"`

The middleware also echoes `X-Request-Id` on the response and emits `request.start` / `request.end` / `request.error` events with `duration_ms`.

## How to add logging to new code

### New service module

```python
import time
import structlog

log = structlog.get_logger(__name__)

def do_thing(...):
    log.info("module.operation.start", key=value, ...)
    start = time.monotonic()
    result = external_call(...)
    log.info(
        "module.operation.end",
        key=value,
        duration_ms=round((time.monotonic() - start) * 1000, 2),
        # plus result metadata: row_count, byte_count, status, etc.
    )
    return result
```

**Do not** add `request_id` as a function argument or to log calls — `structlog.contextvars.merge_contextvars` injects it automatically from the contextvar the middleware set.

### Event-name convention

Use dotted names: `<module>.<operation>.<phase>`.

- Module = the service/component (`athena`, `s3`, `query_builder`, `request`, `robotevents`).
- Operation = the specific action (`start_query_execution`, `upload_parquet`, `build`, `poll`, `fetch_results`).
- Phase = `start` / `end` / `error` / `timeout` / `failed`.

Examples already in the repo:

| Module | Events |
|---|---|
| `request` | `request.start`, `request.end`, `request.error` |
| `query_builder` | `query_builder.build.start`, `query_builder.build.end` |
| `athena` | `athena.start_query_execution.start/.end`, `athena.poll.end/.timeout`, `athena.query.failed`, `athena.fetch_results.start/.end`, `athena.create_table.start/.end` |
| `s3` | `s3.upload_json.start/.end`, `s3.download_json.start/.end`, `s3.upload_parquet.start/.end`, `s3.list_keys.start/.end`, `s3.delete_keys.start/.end` |

### Standard fields

- **Always include on `.end`**: `duration_ms` (rounded to 2 decimals via `round((time.monotonic() - start) * 1000, 2)`).
- **External calls**: include the resource — `bucket`+`key`, `execution_id`, `prefix`, `url`. For SQL, log `sql_preview` (first 200 chars) on `.start` and full `sql`+`params` only in `query_builder.build.end`.
- **Results**: log size hints — `row_count`, `column_count`, `byte_count`, `object_count`, `status_code`.
- **Errors**: use `log.exception(...)` (or `log.error(..., exc_info=True)`) so the JSON line carries the traceback.

### Query service

`app/services/query_builder/query_builder.py::build_query` logs:
- `query_builder.build.start` with `entity`, `filter` (model_dump), `order_by` (model_dump), `select_top`
- `query_builder.build.end` with `strategy`, `sql`, `params`

When extending the query builder, keep these two events as the only ones in `build_query`; do not sprinkle logs inside the resolver helpers.

## Anti-patterns

- Don't use `print()` or stdlib `logging.getLogger()` directly in service code — always `structlog.get_logger(__name__)`.
- Don't pass `request_id` through function signatures. Use contextvars.
- Don't log secrets or full credentials. Boto3 SSO/refresh messages on stdout are external and out of our control; ignore them.
- Don't add a rotating file handler. stdout only.
- Don't wrap one boto3 call in many log events. Pair: one `.start`, one `.end` (plus a `.failed`/`.timeout` on the error path).

## Verifying logging changes

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
curl -s -X POST http://127.0.0.1:8765/query/execute \
  -H "X-Request-Id: smoke-test" \
  -H "Content-Type: application/json" \
  -d '{"entity":"events","filter":{"and":[{"field":"season_id","op":"eq","value":190},{"field":"program_id","op":"eq","value":1}]},"selectTop":3}'
```

Expect: every JSON log line on stdout carries `"request_id":"smoke-test"`, and the trace covers `request.start` → `query_builder.build.start/.end` → `athena.*` events → `request.end`.
