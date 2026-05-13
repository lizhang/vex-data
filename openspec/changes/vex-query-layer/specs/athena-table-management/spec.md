## ADDED Requirements

### Requirement: POST /query/create-tables registers all 7 Glue external tables
The endpoint SHALL read each file in `curated/*.sql`, execute the DDL against Athena, and register all 7 tables (`events`, `teams`, `matches`, `skills`, `rankings`, `team_event_summary`, `team_skill_summary`) in the Glue catalog under the configured database.

#### Scenario: All tables created successfully
- **WHEN** `POST /query/create-tables` is called against a fresh Glue database
- **THEN** the response SHALL be HTTP 200 with `{ "status": "ok", "database": "<db>", "tables_created": ["events", "teams", "matches", "skills", "rankings", "team_event_summary", "team_skill_summary"] }`

#### Scenario: Idempotent — safe to call twice
- **WHEN** `POST /query/create-tables` is called a second time on a database where all tables already exist
- **THEN** the DDL SHALL use `IF NOT EXISTS` and the response SHALL be HTTP 200 with no error

### Requirement: athena.py executes queries and polls until completion
`execute_query(sql, params, workgroup, output_location)` SHALL submit the query to Athena, poll `get_query_execution` every 2 seconds, and return when state is `SUCCEEDED` or raise an error when state is `FAILED` or `CANCELLED`.

#### Scenario: Successful query returns result rows
- **WHEN** Athena returns state `SUCCEEDED`
- **THEN** `execute_query` SHALL fetch all result pages via `get_query_results` and return them as `list[dict[str, Any]]` with column names as keys

#### Scenario: Failed query raises exception
- **WHEN** Athena returns state `FAILED` or `CANCELLED`
- **THEN** `execute_query` SHALL raise an exception containing the Athena state reason string

#### Scenario: Timeout after 60 seconds
- **WHEN** the query has not reached a terminal state within 60 seconds
- **THEN** `execute_query` SHALL raise a timeout exception containing the `execution_id`

### Requirement: athena.py result rows preserve column order and types
Result rows SHALL be returned as dicts with string keys matching Athena column names. All values are returned as strings (Athena GetQueryResults returns strings); the caller is responsible for type coercion.

#### Scenario: Column names match SELECT list
- **WHEN** a query returns columns `team_id`, `number`, `team_name`
- **THEN** each row dict SHALL have keys `"team_id"`, `"number"`, `"team_name"` in that order
