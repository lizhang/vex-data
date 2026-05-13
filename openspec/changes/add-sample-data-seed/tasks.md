## 1. Curated DDL — partition projection

- [ ] 1.1 Edit `curated/events.sql` — append `TBLPROPERTIES` with `projection.enabled = true`, `projection.p_season_id` (integer, 180–210), `projection.p_program_id` (integer, 1–100), and `storage.location.template` for the events Hive path
- [ ] 1.2 Edit `curated/teams.sql` — same 2-column projection block as events
- [ ] 1.3 Edit `curated/team_event_summary.sql` — same 2-column projection block
- [ ] 1.4 Edit `curated/team_skill_summary.sql` — same 2-column projection block
- [ ] 1.5 Edit `curated/team_score_summary.sql` — same 2-column projection block
- [ ] 1.6 Edit `curated/matches.sql` — add 3-column projection block (season, program, event_id integer 1–99999999) with event-scoped `storage.location.template`
- [ ] 1.7 Edit `curated/skills.sql` — same 3-column projection block as matches
- [ ] 1.8 Edit `curated/rankings.sql` — same 3-column projection block as matches
- [ ] 1.9 Verify each DDL still uses `CREATE EXTERNAL TABLE IF NOT EXISTS` so `POST /query/create-tables` stays idempotent for fresh databases

## 2. s3.py path helpers

- [ ] 2.1 Update `raw_key(entity, season_id, program_id, timestamp, event_id=None)` to emit Hive paths matching the DDLs
- [ ] 2.2 Update `curated_key(entity, season_id, program_id, timestamp, event_id=None)` to emit Hive paths matching the DDLs
- [ ] 2.3 Update `list_raw_keys` and `list_curated_keys` signatures to accept `season_id`, `program_id`, optional `event_id`
- [ ] 2.4 Mechanically update call sites in on-hold modules (`app/services/etl.py`, `app/api/routes/ingest.py`, `app/api/routes/curate.py`) so imports still parse; do not test
- [ ] 2.5 Update the `curated_s3_location(entity)` helper if its callers need it (no change to URL structure beyond bucket name)

## 3. Sample-data schemas module

- [ ] 3.1 Create `scripts/__init__.py` (empty) and `scripts/sample_data_schemas.py`
- [ ] 3.2 Define `SCHEMAS: dict[str, pa.Schema]` with entries for all 8 tables; column names/types match `curated/*.sql`
- [ ] 3.3 Define nested types — `events.divisions = list<struct<id, name>>`, `matches.red_teams` / `matches.blue_teams = list<struct<team_id, number>>`
- [ ] 3.4 Add a smoke check at import time (assertions or simple test in the module) that every table key matches a `curated/*.sql` file

## 4. Seed script — generation

- [ ] 4.1 Create `scripts/seed_sample_data.py` with the argparse block per the spec (`--season --program --events --teams --matches-per-event --seed --staging-dir --skip-upload --clean`)
- [ ] 4.2 Implement `generate_events(n, season_id, program_id, rng) -> list[dict]` — synthetic event ids, divisions list per event
- [ ] 4.3 Implement `generate_teams(n, season_id, program_id, rng) -> list[dict]` — team ids, numbers, city/region distribution
- [ ] 4.4 Implement `generate_matches(events, teams, k_per_event, rng) -> list[dict]` — draw 2 red + 2 blue from teams pool, scores
- [ ] 4.5 Implement `generate_skills(events, teams, rng) -> list[dict]` — 1–2 rows per (event, team)
- [ ] 4.6 Implement `generate_rankings(events, teams_per_event_from_matches, rng) -> list[dict]` — one row per team participating in an event
- [ ] 4.7 Implement `derive_team_event_summary(events, matches, teams)` — group by (event_id, team_id); wins/losses/ties from match scores
- [ ] 4.8 Implement `derive_team_skill_summary(skills, teams)` — group by team_id; best/worst/avg score
- [ ] 4.9 Implement `derive_team_score_summary(matches, teams)` — group by team_id; high_score, total_points

## 5. Seed script — write + upload

- [ ] 5.1 Implement `write_parquet(rows, schema, local_path)` — pa.Table from pylist + schema, `pq.write_table` with snappy compression
- [ ] 5.2 For each of the 8 tables, partition rows by their declared partition columns and write one Parquet per partition under `--staging-dir`, mirroring `curated_key(...)` from `s3.py`
- [ ] 5.3 Implement `--clean` semantics — `shutil.rmtree(staging_dir)` and (when uploading) `boto3 list_objects_v2 + delete_objects` per partition prefix
- [ ] 5.4 Implement S3 upload — iterate the local staging tree and `put_object` each Parquet using the local relative path as the S3 object key (skipped under `--skip-upload`)
- [ ] 5.5 Print a one-line summary per table on success (`events: 10 rows -> 1 file`, `matches: 100 rows -> 10 files`, ...)

## 6. Plan + docs

- [ ] 6.1 Edit `plan.md` §"Sample Data Seeding" — table list includes `team_score_summary` (was missing); remove any implied `MSCK REPAIR` follow-up
- [ ] 6.2 Edit `plan.md` §Verification — add a step "drop existing tables, then `POST /query/create-tables`" before the seed step (one-time re-create for projection)
- [ ] 6.3 No CLAUDE.md changes needed — seed script and DDL projection are detail-level, not orientation-level

## 7. Manual verification (requires live AWS)

- [ ] 7.1 `python scripts/seed_sample_data.py --skip-upload` produces 8 tables' worth of Parquet under `./sample_data/`
- [ ] 7.2 `python scripts/seed_sample_data.py --seed 42 --skip-upload --clean` run twice produces identical Parquet contents
- [ ] 7.3 Drop existing Athena tables, then `POST /query/create-tables` — confirms new DDLs apply
- [ ] 7.4 `python scripts/seed_sample_data.py --clean` uploads to S3 successfully
- [ ] 7.5 `POST /query/execute` with `entity=events, filter={and:[{field:"season_id",op:"eq",value:190}]}` returns 10 rows without any `MSCK REPAIR` having been run
- [ ] 7.6 `POST /query/execute` with `entity=team, orderBy={field:"rankings.rank"}` returns rows where every team_id appears in the teams table (referential consistency check)
- [ ] 7.7 `POST /query/execute` with `entity=matches, filter={and:[{field:"season_id",op:"eq",value:190},{field:"teams.number",op:"eq",value:<known-team>}]}` returns the matches that team played
