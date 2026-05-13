## Why

The query layer's translation logic (`build_query`) is implemented, but the service cannot yet execute queries — there is no Athena client to submit SQL and no FastAPI routes to receive `SearchQuery` requests. This change adds the runtime glue (`app/services/athena.py`) and the two endpoints (`POST /query/create-tables`, `POST /query/execute`) that turn the query_builder into a usable API.

## What Changes

- Add `app/services/athena.py` with two functions: `create_tables(db, ddl_dir)` (idempotent DDL registration from `curated/*.sql`) and `execute_query(sql, params, output_location, workgroup, timeout)` (synchronous submit + poll + fetch rows).
- Add `app/api/routes/query.py` exposing:
  - `POST /query/create-tables` — registers all 8 curated tables, returns `{ status, database, tables_created }`.
  - `POST /query/execute` — accepts `SearchQuery`, calls `build_query()`, runs it, returns `QueryResponse` with inline rows.
- Add `app/main.py` — FastAPI application that mounts the query router and exposes `handler = Mangum(app)` for Lambda.
- Error handling: Athena timeouts → 504; Athena failures → 502; builder-raised 422s → 422; unexpected exceptions → 500.

## Capabilities

### New Capabilities

- `athena-execution`: Synchronous Athena query execution service — submit SQL with parameters, poll until terminal state, fetch all result rows, register external tables from DDL files.
- `query-routes`: FastAPI endpoints `/query/create-tables` and `/query/execute` that expose the query layer over HTTP, including FastAPI app wiring and Lambda handler.

### Modified Capabilities

_(none — this is purely additive; `query_builder` is unchanged.)_

## Impact

- **New code**: `app/services/athena.py`, `app/api/routes/query.py`, `app/main.py`.
- **Dependencies**: `boto3` (Athena + Glue clients), `mangum` (Lambda adapter). Both already in `requirements.txt`.
- **Config consumed**: `ATHENA_DATABASE`, `ATHENA_OUTPUT_LOCATION`, `AWS_REGION`, Athena workgroup name (from `app/config.py`).
- **Downstream**: unblocks `scripts/seed_sample_data.py` end-to-end testing and SAM deployment (`template.yaml`).
- **No breaking changes**: `query_builder` and `schemas.py` remain unchanged.
