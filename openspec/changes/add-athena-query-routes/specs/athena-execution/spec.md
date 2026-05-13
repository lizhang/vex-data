## ADDED Requirements

### Requirement: execute_query submits parameterized SQL to Athena
`execute_query(sql, params, output_location, workgroup, timeout=60)` SHALL call `boto3.client("athena").start_query_execution` with `QueryString=sql`, `ExecutionParameters=params` (as a list of strings), `ResultConfiguration={"OutputLocation": output_location}`, and `WorkGroup=workgroup`.

#### Scenario: Parameters are passed as ExecutionParameters
- **WHEN** `execute_query("SELECT * FROM events WHERE p_season_id = ?", [190], ...)` is called
- **THEN** `start_query_execution` SHALL receive `ExecutionParameters=["190"]` and the SQL string SHALL contain `?` placeholders (never interpolated values)

#### Scenario: All param values are coerced to strings
- **WHEN** `params` contains a mix of int, float, and str values
- **THEN** each value SHALL be converted to `str` before being passed to `ExecutionParameters`

### Requirement: execute_query polls until terminal state
After submitting, `execute_query` SHALL call `get_query_execution(QueryExecutionId=...)` every 2 seconds, inspect `QueryExecution.Status.State`, and return when state ∈ {`SUCCEEDED`, `FAILED`, `CANCELLED`}.

#### Scenario: Query succeeds within timeout
- **WHEN** Athena returns state `SUCCEEDED` before the timeout
- **THEN** `execute_query` SHALL fetch all result rows via `get_query_results` and return `(rows, columns)` where `rows` is `list[dict[str, str]]` and `columns` is `list[str]`

#### Scenario: Query fails
- **WHEN** Athena returns state `FAILED` or `CANCELLED`
- **THEN** `execute_query` SHALL raise `AthenaQueryError` containing the state, the `StateChangeReason` string, and the `execution_id`

#### Scenario: Query times out
- **WHEN** state has not reached a terminal value within `timeout` seconds (default 60)
- **THEN** `execute_query` SHALL raise `AthenaTimeoutError` containing the `execution_id`

### Requirement: execute_query result rows preserve column order and string types
Result rows SHALL be returned as dicts with string keys matching Athena column names, in the column order reported by Athena. All values SHALL be returned as strings (Athena `GetQueryResults` returns strings); the caller is responsible for type coercion.

#### Scenario: Column order matches Athena response
- **WHEN** Athena reports columns `["event_id", "name", "start_date"]`
- **THEN** the returned `columns` list SHALL be `["event_id", "name", "start_date"]` and each row dict SHALL contain those exact keys

#### Scenario: Numeric columns returned as strings
- **WHEN** a column contains numeric values (e.g., `190`)
- **THEN** the corresponding dict value SHALL be the string `"190"`, not the integer `190`

#### Scenario: NULL values returned as None
- **WHEN** a column contains a NULL value
- **THEN** the corresponding dict value SHALL be `None`

### Requirement: create_tables registers all curated DDL files
`create_tables(db, ddl_dir, output_location, workgroup)` SHALL iterate every `*.sql` file in `ddl_dir`, execute each DDL via `execute_query`, and return `list[str]` of table names registered.

#### Scenario: All DDL files executed
- **WHEN** `ddl_dir` contains 8 files (events, teams, matches, skills, rankings, team_event_summary, team_skill_summary, team_score_summary)
- **THEN** 8 `start_query_execution` calls SHALL be made and the returned list SHALL contain those 8 table names (derived from filenames)

#### Scenario: Idempotent — safe to call twice
- **WHEN** all DDL files use `CREATE EXTERNAL TABLE IF NOT EXISTS` and the function is called a second time on a database where all tables already exist
- **THEN** all 8 queries SHALL reach state `SUCCEEDED` and the function SHALL return the same list of 8 table names

#### Scenario: DDL with no result rows
- **WHEN** a DDL statement reaches state `SUCCEEDED` but produces no result rows
- **THEN** `create_tables` SHALL NOT call `get_query_results` for that execution and SHALL treat the DDL as registered

### Requirement: AthenaTimeoutError and AthenaQueryError are distinct exception types
The `athena` module SHALL export `AthenaTimeoutError` (subclass of `Exception`) and `AthenaQueryError` (subclass of `Exception`) so callers can distinguish timeouts from failures and map them to different HTTP statuses.

#### Scenario: Both errors importable from module
- **WHEN** `from app.services.athena import AthenaTimeoutError, AthenaQueryError` is executed
- **THEN** both names SHALL resolve to exception classes
