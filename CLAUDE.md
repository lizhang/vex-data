# VEX Data Pipeline

FastAPI service that queries historical VEX robotics data stored in S3/Athena. Deployed to AWS Lambda via SAM.

## Current Focus

The **query layer** is the active work — `POST /query/execute` and `POST /query/create-tables`. Ingest and curate routes are **on hold** (RobotEvents API unavailable). See `plan.md` for full status and `openspec/changes/vex-query-layer/tasks.md` for the task checklist.

## Running Locally

```bash
cp .env.example .env   # fill in values
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Requires real AWS credentials in `.env` (or IAM role) — Athena and S3 calls are live.

To seed sample data before querying:
```bash
python scripts/seed_sample_data.py
```

## Project Layout

```
app/
  config.py                        # pydantic-settings; reads .env
  main.py                          # FastAPI app + handler = Mangum(app) for Lambda
  models/schemas.py                # all Pydantic request/response models
  services/
    s3.py                          # S3 upload/download; Hive partition paths
    athena.py                      # DDL creation + synchronous query execute+poll
    query_builder/
      query_rule.md                # routing rules and SQL templates (source of truth — read this first)
      search_rule_reference.md     # full filter field / orderBy field / constraint reference
      query_builder.py             # build_query(SearchQuery) → (sql, params)
  api/routes/
    query.py                       # POST /query/create-tables, POST /query/execute
curated/                           # Athena DDL — one .sql per table
examples/
  athena_search_query.py           # original SearchQuery schema reference
  query_rule_example.md            # worked query examples (3 scenarios)
  search_rule_reference.md         # original (superseded — use app/services/query_builder/search_rule_reference.md)
scripts/
  seed_sample_data.py              # generates + uploads sample Parquet to S3
template.yaml                      # SAM/CloudFormation infrastructure
samconfig.toml                     # sam deploy defaults
```

## Query System

`POST /query/execute` accepts a `SearchQuery` JSON body — never raw SQL.

### SearchQuery shape

```json
{
  "entity": "events | matches | team",
  "filter": {
    "and": [
      { "field": "season_id",    "op": "eq",       "value": 190 },
      { "field": "teams.city",   "op": "eq",       "value": "Los Angeles" },
      { "field": "events.name",  "op": "contains", "value": "regional" }
    ]
  },
  "orderBy": { "field": "rankings.rank", "direction": "asc" },
  "selectTop": 25
}
```

Routing, filter→WHERE mappings, SQL templates, security, and encoding conventions: **`app/services/query_builder/query_rule.md`**

## S3 Layout

```
s3://vex-search-data-v1/
  raw/         {entity}/p_season_id={s}/p_program_id={p}/[p_event_id={e}/]{ts}.json
  curated/     {entity}/p_season_id={s}/p_program_id={p}/[p_event_id={e}/]{ts}.parquet
  athena-results/
```

Tables partitioned by `p_season_id` + `p_program_id` (all), plus `p_event_id` for `matches`, `skills`, `rankings`. Always provide `season_id` + `program_id` in queries for partition pruning.

## Athena Tables (8 total)

Base: `events`, `teams`, `matches`, `skills`, `rankings`
Derived: `team_event_summary`, `team_skill_summary`, `team_score_summary`

DDL in `curated/*.sql`. Register with `POST /query/create-tables` (idempotent — uses `IF NOT EXISTS`).

## AWS Deployment (SAM)

```bash
sam build
sam deploy --guided    # first time — writes samconfig.toml
sam deploy             # subsequent
```

Resources created: S3 bucket `vex-search-data-v1`, Athena workgroup `vex-data-wg`, Glue database `vex_data`, IAM role, Lambda function, HTTP API Gateway.

The Lambda entry point is `handler = Mangum(app)` in `app/main.py`.

## Config

All config via environment variables (`.env` locally, SAM `Globals.Function.Environment` on Lambda):

| Variable | Default | Notes |
|----------|---------|-------|
| `ROBOTEVENTS_API_KEY` | — | required |
| `S3_BUCKET` | — | `vex-search-data-v1` |
| `S3_RAW_PREFIX` | `raw` | |
| `S3_CURATED_PREFIX` | `curated` | |
| `AWS_REGION` | `us-east-1` | |
| `ATHENA_DATABASE` | `vex_data` | |
| `ATHENA_OUTPUT_LOCATION` | auto-derived | defaults to `s3://{S3_BUCKET}/athena-results/` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | — | omit to use IAM role |

## Key Conventions

- Athena poll interval: 2 s, timeout: 60 s
- Field mappings, SQL encoding, time formats, and security: `app/services/query_builder/query_rule.md`

## On Hold

- `app/services/robotevents.py` — RobotEvents API v2 client (API unavailable)
- `app/services/etl.py` — raw JSON → Parquet cleaners
- `app/api/routes/ingest.py` — `/ingest/*` endpoints
- `app/api/routes/curate.py` — `/curate/*` endpoints
