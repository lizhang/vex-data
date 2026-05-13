## Why

The VEX data pipeline has curated Parquet tables in S3 and needs a query layer so callers can search events, matches, and teams using a structured JSON API rather than raw SQL. The RobotEvents ingest API is temporarily unavailable, so the immediate priority is building the query layer end-to-end against seeded sample data, with AWS infrastructure deployed via SAM.

## What Changes

- Add `scripts/seed_sample_data.py` — generates realistic sample rows for all 7 curated tables and uploads correctly partitioned Parquet files to S3 so the query layer can be tested without live ingest
- Update `app/models/schemas.py` — add `ScoreFilter`, fix `entity` pattern to `^(events|matches|team)$`
- Update `app/services/s3.py` — replace `dt=` date partition paths with `p_season_id/p_program_id/p_event_id` Hive partition paths matching the curated table DDL
- Add `app/services/query_builder/query_builder.py` — translates `SearchQuery` JSON into Athena SQL using 5 routing strategies (EVENTS, MATCHES, TEAM_EVENT, TEAM_SKILL, TEAM_MATCH_SCORE, TEAM_RANKING); parameterized queries; column and sort-field allowlists
- Add `app/services/athena.py` — creates Athena Glue tables from `curated/*.sql` DDL; executes queries and polls synchronously; returns result rows
- Add `app/api/routes/query.py` — `POST /query/create-tables` and `POST /query/execute`
- Add `app/main.py` — FastAPI app with Mangum Lambda handler; registers query router
- Add `template.yaml` + `samconfig.toml` — SAM template provisioning S3 bucket, Athena workgroup, Glue database, IAM role, Lambda function, HTTP API Gateway

## Capabilities

### New Capabilities

- `sample-data-seed`: Script that generates and uploads sample Parquet data for all 7 curated tables to S3 with correct partition paths
- `search-query`: JSON query API (`POST /query/execute`) that routes `SearchQuery` to one of 5 Athena SQL strategies and returns inline results
- `athena-table-management`: `POST /query/create-tables` creates all 7 Glue external tables from `curated/*.sql` DDL
- `sam-infrastructure`: CloudFormation/SAM template deploying all required AWS infrastructure (S3, Athena, Glue, Lambda, API Gateway, IAM)

### Modified Capabilities

## Impact

- **`app/models/schemas.py`**: add `ScoreFilter`; change entity regex; add `ScoreFilter` to `Filter`
- **`app/services/s3.py`**: `curated_key()` helper rewritten to use partition dict instead of date string
- **New files**: `scripts/seed_sample_data.py`, `app/services/query_builder/__init__.py`, `app/services/query_builder/query_builder.py`, `app/services/athena.py`, `app/api/routes/query.py`, `app/main.py`, `template.yaml`, `samconfig.toml`
- **Dependencies added**: `mangum>=0.17.0` (Lambda adapter)
- **AWS resources created by SAM**: S3 bucket `vex-data`, Athena workgroup `vex-data-wg`, Glue database `vex_data`, IAM execution role, Lambda function, HTTP API
