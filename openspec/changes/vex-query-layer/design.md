## Context

The VEX data pipeline stores curated Parquet files in S3 under Hive-style partitions (`p_season_id`, `p_program_id`, `p_event_id`). Seven Athena external tables are defined in `curated/*.sql`. The `app/services/query_builder/query_rule.md` fully specifies the routing logic: a `SearchQuery` JSON object maps to one of 5 SQL strategies based on `entity`, `filter.event`, and `orderBy`. The RobotEvents ingest API is unavailable, so sample data must be seeded directly into S3 before the query layer can be exercised.

The app must run both locally (uvicorn) and on AWS Lambda (via Mangum + SAM). Infrastructure is provisioned by a SAM template.

## Goals / Non-Goals

**Goals:**
- Implement `POST /query/execute` that accepts `SearchQuery`, builds Athena SQL via the 5-strategy router, polls for results, and returns rows inline
- Implement `POST /query/create-tables` that registers all 7 Glue external tables from `curated/*.sql`
- Provide `scripts/seed_sample_data.py` to upload realistic sample Parquet to S3 for local/CI testing
- SAM template that provisions all required AWS resources in one `sam deploy`
- Parameterized Athena queries; column and sort-field allowlists; no raw user input in SQL

**Non-Goals:**
- Ingest from RobotEvents API (on hold)
- ETL / curate routes (on hold)
- Async query polling via separate `/status` + `/results` endpoints
- Authentication / authorization on the API

## Decisions

### 1. Query routing via pure Python, not a DSL or ORM
`query_builder.py` uses a plain `if/elif` tree keyed on `entity` + filter presence + `orderBy`. Each branch calls a private `_build_*` function that assembles a SQL string using `?` placeholders and a parallel list of parameter values.

_Alternative considered_: SQLAlchemy Core for safe query building. Rejected because Athena's boto3 client does not accept SQLAlchemy dialects, and the query shapes are fixed enough that a custom builder is simpler and more auditable.

### 2. Athena parameterized queries via `ExecutionParameters`
All user-supplied strings and integers are passed as `ExecutionParameters` (list of strings) alongside a SQL template containing `?` placeholders. Athena substitutes them server-side, preventing SQL injection.

_Fallback_: If a future Athena API version drops `ExecutionParameters` support, `_escape(v)` doubles single quotes in string values as a secondary defence.

### 3. Synchronous Athena poll in `athena.py`
`execute_query(sql, params)` submits the query, then polls `get_query_execution` every 2 seconds up to 60 seconds. Results are fetched with `get_query_results` and returned as `list[dict]`. No background tasks or separate status endpoints.

_Rationale_: Most filtered queries against partitioned Parquet complete in < 10 s. A 60 s timeout is generous. Async polling adds API surface complexity that isn't needed at this stage.

### 4. Mangum for Lambda compatibility
`app/main.py` exports `handler = Mangum(app)` as the Lambda entry point. Locally, `uvicorn app.main:app` is used unchanged. No code-path divergence between local and Lambda.

### 5. SAM template provisions infrastructure; app does not create resources at startup
Bucket, Glue database, Athena workgroup, and IAM role are all declared in `template.yaml`. The app assumes these exist — it does not create them on first run. `POST /query/create-tables` creates Glue table definitions (DDL), which is idempotent (`IF NOT EXISTS`).

### 6. Seed script uses pyarrow to produce Parquet with exact schema
`seed_sample_data.py` defines a pyarrow schema per table that matches `curated/*.sql` column types exactly, including `list<struct<...>>` for `matches.red_teams`/`blue_teams`. This ensures Athena can read the files without a schema mismatch.

### 7. TEAM_RANKING strategy joins `rankings` + optionally `events`
When `filter.time` or `orderBy="time"` is present, a `LEFT JOIN events` is added via `rankings.event_id`. The `GROUP BY` aggregation (MIN rank, COUNT events, SUM wins/losses/ties, MAX high_score) then applies only to rankings rows that fall within the time window.

### 8. TEAM_MATCH_SCORE corner case (orderBy="score" + filter.time)
`team_skill_summary` pre-aggregates across all time, so it cannot honour a time filter. Instead, `teams JOIN matches JOIN events` is used: matches are correlated to teams via `EXISTS (SELECT 1 FROM UNNEST(red_teams/blue_teams) WHERE number = t.number)`, and events provide the time filter on `start_date`/`end_date`. Score is `MAX(GREATEST(red_score, blue_score))`.

## Risks / Trade-offs

- **UNNEST join cost**: The TEAM_MATCH_SCORE strategy unnests `red_teams`/`blue_teams` arrays per match row. On large datasets this is expensive. Mitigation: always require `season_id` + `program_id` (partition pruning) to limit scan size; document this in query_rule.md.
- **60 s Athena timeout**: Complex queries (e.g. TEAM_MATCH_SCORE without partition filters) may exceed 60 s. Mitigation: return a timeout error with the Athena `execution_id` so callers can manually check the console. Increase timeout if needed.
- **S3 bucket name collision**: `template.yaml` uses a hardcoded bucket name `vex-data`. If the name is already taken in the AWS account, `sam deploy` will fail. Mitigation: parameterise `BucketName` and set default to `vex-data`.
- **Mangum cold start**: First Lambda invocation after inactivity incurs a cold start (~1–2 s). Mitigation: acceptable for the current use case; provisioned concurrency can be added later.
- **Seed data is synthetic**: Sample Parquet does not reflect real VEX data distributions. Mitigation: sufficient for schema/routing validation; replace with real data once ingest is unblocked.

## Migration Plan

1. Run `sam build && sam deploy --guided` to provision AWS resources
2. Run `python scripts/seed_sample_data.py` to upload sample Parquet
3. Call `POST /query/create-tables` to register Glue tables
4. Verify with `POST /query/execute` calls (see Verification section in plan.md)

Rollback: `sam delete` removes all SAM-managed resources. S3 bucket must be emptied manually first (versioning enabled).

## Open Questions

- Should `selectTop` max (currently 1000) be enforced at the Athena level via workgroup scan limits, or only in the query builder?
- Should `POST /query/create-tables` use `DROP TABLE IF EXISTS` + recreate, or `IF NOT EXISTS` (idempotent skip)?
