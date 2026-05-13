## ADDED Requirements

### Requirement: POST /query/create-tables registers all 8 Glue external tables
The endpoint SHALL call `athena.create_tables(db, "curated/", output_location, workgroup)` and return the list of registered table names. The endpoint takes no request body.

#### Scenario: Tables created successfully
- **WHEN** `POST /query/create-tables` is called against a fresh Glue database
- **THEN** the response SHALL be HTTP 200 with body `{ "status": "ok", "database": "<db>", "tables_created": ["events", "teams", "matches", "skills", "rankings", "team_event_summary", "team_skill_summary", "team_score_summary"] }`

#### Scenario: Idempotent — safe to call twice
- **WHEN** `POST /query/create-tables` is called a second time
- **THEN** the response SHALL be HTTP 200 with the same `tables_created` list and no error

#### Scenario: Athena failure during table creation
- **WHEN** any DDL statement returns state `FAILED`
- **THEN** the endpoint SHALL return HTTP 502 with `{ "error": "Athena query failed", "state_reason": "<reason>", "execution_id": "<id>" }`

### Requirement: POST /query/execute accepts SearchQuery and returns inline results
The endpoint SHALL accept a `SearchQuery` JSON body, call `build_query(query, db)` to translate to SQL, execute the SQL synchronously via `athena.execute_query`, and return a `QueryResponse` with all result rows.

#### Scenario: Successful query returns rows
- **WHEN** `POST /query/execute` receives a valid `SearchQuery`
- **THEN** the response SHALL be HTTP 200 with body `{ "entity": "<entity>", "sql_executed": "<sql>", "total": <n>, "columns": [...], "rows": [...] }`

#### Scenario: Empty result set
- **WHEN** Athena returns zero rows for a valid query
- **THEN** the response SHALL be HTTP 200 with `"total": 0`, `"rows": []`, and the populated `columns` list

#### Scenario: Invalid entity value
- **WHEN** `entity` is not one of `"events"`, `"matches"`, `"team"`
- **THEN** the endpoint SHALL return HTTP 422 (Pydantic validation error) without calling `build_query` or Athena

#### Scenario: Builder rejects unknown filter field
- **WHEN** `filter.and[].field` is not in the global `FIELDS` map (e.g., `"foo.bar"`)
- **THEN** `build_query` SHALL raise `HTTPException(422, ...)` and the endpoint SHALL return HTTP 422 with the detail message

#### Scenario: matches.score without teams.number
- **WHEN** `orderBy.field = "matches.score"` is sent without a `teams.number` filter condition
- **THEN** the endpoint SHALL return HTTP 422 with the message `"orderBy.field='matches.score' requires a teams.number filter"`

#### Scenario: Athena query times out
- **WHEN** the Athena query does not complete within 60 seconds
- **THEN** the endpoint SHALL return HTTP 504 with `{ "error": "Query timed out", "execution_id": "<id>" }`

#### Scenario: Athena query fails
- **WHEN** Athena returns state `FAILED` or `CANCELLED` for a built query
- **THEN** the endpoint SHALL return HTTP 502 with `{ "error": "Athena query failed", "state_reason": "<reason>", "execution_id": "<id>" }`

### Requirement: QueryResponse includes the executed SQL string
Each successful `/query/execute` response SHALL include `sql_executed` — the exact SQL string passed to Athena (with `?` placeholders intact, not interpolated values).

#### Scenario: sql_executed contains placeholders
- **WHEN** the query has parameter values
- **THEN** `sql_executed` SHALL contain `?` placeholder characters and SHALL NOT contain the parameter values

### Requirement: app/main.py wires query router and exports Mangum handler
`app/main.py` SHALL create a `FastAPI` app, mount the query router at prefix `/query`, and export `handler = Mangum(app)` for AWS Lambda invocation.

#### Scenario: Local uvicorn run
- **WHEN** `uvicorn app.main:app --reload` is executed
- **THEN** the server SHALL start and the routes `POST /query/create-tables` and `POST /query/execute` SHALL be reachable

#### Scenario: Lambda handler exposed
- **WHEN** `app/main.py` is imported as `app.main`
- **THEN** the module SHALL expose a top-level `handler` attribute callable as a Lambda handler (`handler(event, context)`)

### Requirement: Ingest and curate routers are NOT mounted
`app/main.py` SHALL NOT import or mount `ingest.py` or `curate.py` routers, because those routes are on hold pending RobotEvents API availability.

#### Scenario: No /ingest or /curate routes exposed
- **WHEN** the app is running and a client requests `POST /ingest/events` or `POST /curate/teams`
- **THEN** the server SHALL respond with HTTP 404
