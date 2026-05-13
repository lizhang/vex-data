## Context

`query_builder.build_query()` is complete and tested-by-hand — it returns `(sql, params)` ready for Athena. The remaining glue is a thin Athena client and the FastAPI surface. The service is sync-execution-only (no long-running query semantics): clients wait for results inline. Deployment target is AWS Lambda via Mangum, which constrains us to a 30s default timeout (configurable via SAM template; current plan caps Athena polling at 60s).

Existing pieces consumed by this change:
- `app/services/query_builder/build_query()` — translates `SearchQuery` → `(sql, params)`.
- `app/models/schemas.py` — `SearchQuery`, `QueryResponse`.
- `app/config.py` — `ATHENA_DATABASE`, `ATHENA_OUTPUT_LOCATION`, `AWS_REGION`, workgroup name.
- `curated/*.sql` — 8 DDL files (one per table, all use `CREATE EXTERNAL TABLE IF NOT EXISTS`).

## Goals / Non-Goals

**Goals:**
- Synchronous Athena execution: submit → poll → fetch → return rows in one HTTP request.
- Idempotent table registration: `/query/create-tables` safe to call repeatedly.
- Parameterized queries only — `ExecutionParameters` carries every user value; SQL string has only `?` placeholders.
- Map Athena/builder failures to appropriate HTTP status codes (504 / 502 / 422 / 500).
- Lambda-ready: `handler = Mangum(app)` exported from `app/main.py`.

**Non-Goals:**
- Async / queued query execution. Caller waits inline; 60s cap is intentional.
- Result caching, pagination, or streaming. All rows are returned in one response (Athena `selectTop` cap of 1000 keeps payloads bounded).
- Re-implementing query building. `build_query()` is consumed as-is.
- New Pydantic models. `SearchQuery` and `QueryResponse` are reused from `schemas.py`.

## Decisions

### 1. Use boto3 Athena client directly (no AWS SDK abstraction)

Use `boto3.client("athena")` with `start_query_execution`, `get_query_execution`, `get_query_results`. Pass parameters via `ExecutionParameters` to enforce parameterization.

**Why:** boto3 is already a transitive dependency, and the Athena workflow (start → poll → fetch) is simple enough that a wrapper library adds dependency weight without clarity gain.

**Alternatives considered:**
- `awswrangler` — adds pandas dependency and bloats Lambda zip; we only need `list[dict]` results.
- `aioboto3` — async client. Mangum + FastAPI handle sync handlers fine on Lambda, and Athena polling is naturally serial.

### 2. Synchronous polling at 2s intervals, 60s timeout

`execute_query()` calls `get_query_execution` every 2 seconds until state ∈ {SUCCEEDED, FAILED, CANCELLED}. Timeout raises a dedicated `AthenaTimeoutError` that the route maps to HTTP 504.

**Why:** Most queries against the sample data return in under 5s. The 2s cadence is a balance between latency on small queries and API call overhead.

### 3. Result rows as `list[dict[str, str]]`

Athena's `GetQueryResults` returns all values as strings. We do NOT coerce types in `athena.py` — the route returns them as-is in `QueryResponse.rows`.

**Why:** Type coercion requires schema knowledge that lives in the query layer, not the Athena layer. Keeping `athena.py` schema-agnostic preserves reusability. Clients can coerce based on `QueryResponse.columns` if needed.

### 4. `/query/create-tables` reads `curated/*.sql` at request time

The DDL files are bundled into the Lambda zip via SAM. The route iterates files, executes each DDL as a query, returns the list of registered table names. Idempotency is provided by `CREATE EXTERNAL TABLE IF NOT EXISTS` in every DDL file.

**Why:** Reading at request time keeps the deployment simple (no separate "deploy schema" step) and lets us add a new curated table by dropping a `.sql` file into `curated/`.

### 5. Error → HTTP status mapping

| Source | HTTP |
|--------|------|
| Pydantic validation failure | 422 (FastAPI default) |
| `build_query` `HTTPException(422, ...)` | 422 (FastAPI passthrough) |
| `AthenaTimeoutError` | 504 with `{ "error": "Query timed out", "execution_id": ... }` |
| `AthenaQueryError` (FAILED / CANCELLED) | 502 with `{ "error": ..., "state_reason": ..., "execution_id": ... }` |
| Unhandled `Exception` | 500 (FastAPI default) |

The route catches `AthenaTimeoutError` and `AthenaQueryError` explicitly to control the response shape; everything else bubbles to FastAPI's default handler.

### 6. App wiring in `app/main.py`

```python
app = FastAPI(title="VEX Data API", version="1.0")
app.include_router(query_router, prefix="/query")
handler = Mangum(app)
```

No other routers (`ingest`, `curate`) are mounted — they're on hold per `plan.md`.

## Risks / Trade-offs

- **Lambda 30s default timeout vs 60s Athena poll cap** → Set Lambda timeout to 90s in `template.yaml` to leave headroom; document this requirement.
- **`get_query_results` paginates at 1000 rows max per page** → With `selectTop` capped at 1000 we fit in one page; if a future change raises the cap, add a loop.
- **Athena cold start on first query in a workgroup** → Acceptable for this stage; not optimizing.
- **DDL execution returns no rows** → `execute_query` must tolerate an empty `ResultSet`; explicit handling in `create_tables` (don't call `get_query_results`, just verify SUCCEEDED state).
- **String-only result values** → Clients that need typed values must coerce themselves; documented in spec.
