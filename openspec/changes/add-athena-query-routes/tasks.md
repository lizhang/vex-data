## 1. Athena execution service

- [ ] 1.1 Create `app/services/athena.py` with `AthenaTimeoutError` and `AthenaQueryError` exception classes
- [ ] 1.2 Implement `execute_query(sql, params, output_location, workgroup, timeout=60)` — submit via `start_query_execution`, coerce params to strings, pass as `ExecutionParameters`
- [ ] 1.3 Implement polling loop in `execute_query` — 2s interval, terminal states {SUCCEEDED, FAILED, CANCELLED}, raise `AthenaTimeoutError` after `timeout`
- [ ] 1.4 Implement result-fetch in `execute_query` — call `get_query_results`, return `(rows: list[dict[str, str|None]], columns: list[str])`; map empty/NULL values to `None`
- [ ] 1.5 Implement `create_tables(db, ddl_dir, output_location, workgroup)` — iterate `*.sql` files, execute each DDL, skip result fetch on DDL queries, return list of table names

## 2. Query routes

- [ ] 2.1 Create `app/api/routes/query.py` with FastAPI `APIRouter`
- [ ] 2.2 Implement `POST /create-tables` — call `athena.create_tables(...)` with values from `app.config`, return `{ status, database, tables_created }`
- [ ] 2.3 Implement `POST /execute` — call `build_query(query, db)`, then `athena.execute_query(sql, params, ...)`, return `QueryResponse(entity, sql_executed=sql, total=len(rows), columns, rows)`
- [ ] 2.4 Add exception handlers: `AthenaTimeoutError` → 504, `AthenaQueryError` → 502 with `state_reason` and `execution_id` in body
- [ ] 2.5 Let builder-raised `HTTPException(422, ...)` propagate unchanged (FastAPI handles natively)

## 3. App wiring

- [ ] 3.1 Create `app/main.py` — instantiate `FastAPI(title="VEX Data API")`
- [ ] 3.2 Mount query router at `/query` prefix (`app.include_router(query_router, prefix="/query")`)
- [ ] 3.3 Export `handler = Mangum(app)` for Lambda invocation
- [ ] 3.4 Confirm ingest/curate routers are NOT imported or mounted

## 4. Manual verification

- [ ] 4.1 `uvicorn app.main:app --reload` starts without errors
- [ ] 4.2 `POST /query/create-tables` returns 200 with all 8 table names against the configured Glue DB
- [ ] 4.3 Re-call `POST /query/create-tables` — confirms idempotency (still 200, same list)
- [ ] 4.4 `POST /query/execute` with the EVENTS sample query from `plan.md` §Verification returns 200 with rows
- [ ] 4.5 `POST /query/execute` with `matches.score` orderBy but no `teams.number` filter returns 422 with the expected detail message
- [ ] 4.6 `POST /query/execute` with `filter.field = "foo.bar"` returns 422 ("Unknown filter field")
- [ ] 4.7 `POST /ingest/events` returns 404 (router not mounted)
