## 1. Schemas and S3 Updates

- [ ] 1.1 Add `ScoreFilter(min, max)` class to `app/models/schemas.py`
- [ ] 1.2 Add `score: Optional[ScoreFilter]` field to `Filter` in `app/models/schemas.py`
- [ ] 1.3 Update `SearchQuery.entity` pattern to `^(events|matches|team)$` in `app/models/schemas.py`
- [ ] 1.4 Rewrite `curated_key()` in `app/services/s3.py` to accept a partition dict (`p_season_id`, `p_program_id`, optional `p_event_id`) and produce Hive-style paths instead of `dt=` date paths
- [ ] 1.5 Add `mangum>=0.17.0` to `requirements.txt`

## 2. Sample Data Seed Script

- [ ] 2.1 Create `scripts/` directory and `scripts/seed_sample_data.py`
- [ ] 2.2 Define pyarrow schemas for all 7 tables matching `curated/*.sql` exactly (including `list<struct<...>>` for `matches.red_teams`/`blue_teams`)
- [ ] 2.3 Generate 3 sample events with realistic field values (`season_id=190`, `program_id=1`)
- [ ] 2.4 Generate 10 sample teams referenced by those events
- [ ] 2.5 Generate ~30 matches spread across 3 events; ensure `red_teams`/`blue_teams` reference the 10 seeded team numbers
- [ ] 2.6 Generate skills and rankings rows for each team × event combination
- [ ] 2.7 Generate `team_event_summary` rows joining the above (ranking, wins/losses, best scores)
- [ ] 2.8 Generate `team_skill_summary` rows aggregated per team (best/worst/avg skill score)
- [ ] 2.9 Write each table's rows to a pyarrow Table, serialize to Parquet (snappy compression)
- [ ] 2.10 Upload each Parquet file to S3 at the correct partition path using `app/services/s3.py`
- [ ] 2.11 Verify: run `python scripts/seed_sample_data.py` and confirm files appear in S3 console

## 3. Query Builder

- [ ] 3.1 Create `app/services/query_builder/__init__.py` (empty)
- [ ] 3.2 Create `app/services/query_builder/query_builder.py` with `build_query(query: SearchQuery, db: str) -> tuple[str, list[str]]` returning SQL + parameter list
- [ ] 3.3 Implement `_escape(v: str) -> str` for single-quote doubling fallback
- [ ] 3.4 Implement `_build_events(f, order_by, limit, db)` — EVENTS strategy with full filter→WHERE and orderBy allowlist
- [ ] 3.5 Implement `_build_matches(f, order_by, limit, db)` — MATCHES strategy including `EXISTS (UNNEST(...))` for team filter and score filter
- [ ] 3.6 Implement `_build_team_event(f, order_by, limit, db)` — TEAM_EVENT strategy querying `team_event_summary`
- [ ] 3.7 Implement `_build_team_skill(f, limit, db)` — TEAM_SKILL strategy joining `teams + team_skill_summary`
- [ ] 3.8 Implement `_build_team_ranking(f, order_by, limit, db)` — TEAM_RANKING strategy with GROUP BY aggregates; add `LEFT JOIN events` when `filter.time` or `orderBy="time"` is present
- [ ] 3.9 Implement `_build_team_match_score(f, limit, db)` — TEAM_MATCH_SCORE corner case joining `teams + matches + events`
- [ ] 3.10 Implement routing logic in `build_query()`: `entity` → EVENTS/MATCHES; `team` → event filter → TEAM_EVENT; `orderBy=score + no time` → TEAM_SKILL; `orderBy=score + time` → TEAM_MATCH_SCORE; default → TEAM_RANKING
- [ ] 3.11 Ensure all user values go into params list (`?` placeholders), never interpolated into SQL string
- [ ] 3.12 Ensure `orderBy` is resolved through per-strategy allowlist dict; raw value never embedded in SQL

## 4. Athena Service

- [ ] 4.1 Create `app/services/athena.py`
- [ ] 4.2 Implement `create_tables(ddl_dir: Path, database: str, workgroup: str, output_location: str)` — reads each `*.sql` file, prepends `IF NOT EXISTS`, executes DDL against Athena
- [ ] 4.3 Implement `execute_query(sql: str, params: list[str], database: str, workgroup: str, output_location: str) -> list[dict]` — submits query with `ExecutionParameters`, polls every 2 s up to 60 s, fetches all result pages, returns rows as list of dicts
- [ ] 4.4 Handle `FAILED`/`CANCELLED` state — raise exception with Athena state reason
- [ ] 4.5 Handle timeout (60 s) — raise exception with `execution_id` included in message
- [ ] 4.6 Strip Athena header row from `get_query_results` response when building row dicts

## 5. Query Route

- [ ] 5.1 Create `app/api/routes/query.py`
- [ ] 5.2 Implement `POST /query/create-tables` — calls `athena.create_tables()`, returns `{ status, database, tables_created }`
- [ ] 5.3 Implement `POST /query/execute` — validates `SearchQuery`, calls `query_builder.build_query()`, calls `athena.execute_query()`, returns `QueryResponse`
- [ ] 5.4 Add error handling: 504 on timeout (include `execution_id`), 500 on Athena failure (include reason)

## 6. Main App

- [ ] 6.1 Create `app/main.py` — instantiate `FastAPI` app, register query router under prefix `/query`
- [ ] 6.2 Add `handler = Mangum(app)` as the Lambda entry point export
- [ ] 6.3 Verify `uvicorn app.main:app --reload` starts without errors

## 7. SAM Infrastructure Template

- [ ] 7.1 Create `template.yaml` with `Transform: AWS::Serverless-2016-10-31`
- [ ] 7.2 Add `Parameters`: `RobotEventsApiKey` (NoEcho), `BucketName` (default `vex-data`), `AthenaDatabase` (default `vex_data`)
- [ ] 7.3 Add `VexDataBucket` (`AWS::S3::Bucket`) with versioning enabled, name from `!Ref BucketName`
- [ ] 7.4 Add `AthenaWorkgroup` (`AWS::Athena::WorkGroup`) with output location `s3://{bucket}/athena-results/` and `EnforceWorkGroupConfiguration: true`
- [ ] 7.5 Add `GlueDatabase` (`AWS::Glue::Database`) with name from `!Ref AthenaDatabase`
- [ ] 7.6 Add `AppRole` (`AWS::IAM::Role`) with Lambda trust policy, basic execution managed policy, and inline policy granting S3 (scoped to bucket ARN), Athena, and Glue
- [ ] 7.7 Add `VexDataFunction` (`AWS::Serverless::Function`) — handler `app.main.handler`, runtime `python3.12`, role `!GetAtt AppRole.Arn`, env vars from Globals, `HttpApi` event catching `/{proxy+}` ANY
- [ ] 7.8 Add `VexDataApi` (`AWS::Serverless::HttpApi`)
- [ ] 7.9 Add `Outputs` block with `ApiUrl` (`!Sub https://${VexDataApi}.execute-api.${AWS::Region}.amazonaws.com`)
- [ ] 7.10 Create `samconfig.toml` with default stack name `vex-data-stack`, region, S3 deployment bucket, and `parameter_overrides` placeholder
- [ ] 7.11 Verify `sam build` completes without errors
- [ ] 7.12 Verify `sam deploy --guided` creates all resources and stack Outputs show the API URL

## 8. End-to-End Verification

- [ ] 8.1 Run `python scripts/seed_sample_data.py` — confirm Parquet files in S3
- [ ] 8.2 Run `POST /query/create-tables` — confirm 7 tables appear in Athena console
- [ ] 8.3 Run `POST /query/execute` with EVENTS query — confirm rows returned
- [ ] 8.4 Run `POST /query/execute` with MATCHES + team number filter — confirm EXISTS/UNNEST works
- [ ] 8.5 Run `POST /query/execute` with TEAM_RANKING (`entity=team`, `orderBy=ranking`) — confirm aggregated columns present
- [ ] 8.6 Run `POST /query/execute` with TEAM_SKILL (`entity=team`, `orderBy=score`, no time) — confirm `best_skill_score` in rows
- [ ] 8.7 Run `POST /query/execute` with TEAM_EVENT (`entity=team`, `filter.event.name` set) — confirm `team_event_summary` rows
- [ ] 8.8 Run `POST /query/execute` with TEAM_MATCH_SCORE (`entity=team`, `orderBy=score`, `filter.time` set) — confirm corner case returns `best_match_score`
- [ ] 8.9 Run `POST /query/execute` with TEAM_RANKING + `filter.time` — confirm events join and time-window results
