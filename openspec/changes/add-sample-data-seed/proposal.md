## Why

The query layer (`POST /query/execute`) is wired end-to-end, but there is no curated data in S3 to query against — the RobotEvents API is unavailable, so `app/services/etl.py` and the ingest/curate routes are on hold. We need a way to populate the 8 curated tables with realistic, internally consistent sample data so the query routes can be exercised locally and during smoke tests, without depending on the upstream API.

A second, related gap blocks the same goal: the curated DDLs use Hive-partitioned S3 paths (`p_season_id={s}/p_program_id={p}/[p_event_id={e}/]`) but have no partition discovery mechanism. Even after uploading Parquet to the correct paths, Athena returns zero rows until partitions are registered. Today this would force a manual `MSCK REPAIR TABLE` step per table after every seed run.

## What Changes

- **Add partition projection to the 8 curated DDLs** (`curated/*.sql`) — `TBLPROPERTIES` with `projection.enabled = true` and per-partition-column `projection.<col>.*` settings. Athena reads partition values directly from S3 paths; no `MSCK` or `ALTER TABLE ADD PARTITION` needed.
- **Fix `app/services/s3.py` path helpers** — replace the stale `dt={date}` scheme with the Hive scheme matching the DDLs (`p_season_id/p_program_id/[p_event_id]`). Update `raw_key()`, `curated_key()`, and `list_*_keys()` signatures and call sites.
- **Add `scripts/seed_sample_data.py`** — argparse-driven CLI that:
  1. Generates base rows for `events`, `teams`, `matches`, `skills`, `rankings` (deterministic with `--seed`).
  2. Aggregates the 3 derived tables (`team_event_summary`, `team_skill_summary`, `team_score_summary`) from the base rows so JOINs across tables are coherent.
  3. Writes all 8 tables as Parquet to a local staging dir using pyarrow schemas that match the DDLs (including nested `array<struct<…>>`).
  4. Uploads each Parquet file to the corresponding S3 Hive-partitioned path via the fixed `s3.py` helpers (unless `--skip-upload`).
- **Add `scripts/sample_data_schemas.py`** (or a `scripts/_schemas.py` module) — single source of truth for the pyarrow schemas, indexed by table name. Imported by the seed script.
- **Update `plan.md`** — table list in §"Sample Data Seeding" includes `team_score_summary` (currently missing); flow no longer mentions `MSCK REPAIR` as a follow-up.

## Capabilities

### New Capabilities

- `sample-data-seed`: A local-then-upload script that produces internally consistent sample Parquet files for all 8 curated tables and writes them to the expected S3 Hive partitions.

### Modified Capabilities

- `curated-tables` (the existing DDLs as a capability): tables gain partition projection so Athena auto-discovers partitions without `MSCK`.
- `s3-paths` (the path helpers in `s3.py`): switch from `dt={date}` to `p_season_id/p_program_id/[p_event_id]`.

## Impact

- **New code**: `scripts/seed_sample_data.py`, `scripts/sample_data_schemas.py`. New `scripts/` directory.
- **Modified code**: `curated/*.sql` × 8 (add TBLPROPERTIES), `app/services/s3.py` (path helpers + any callers).
- **Dependencies**: `pyarrow` (already used by `s3.py`). No new requirements.
- **Downstream**:
  - Unblocks end-to-end manual verification of `POST /query/execute` (tasks 4.2 – 4.6 of `add-athena-query-routes`).
  - Removes the need for a `/query/repair-partitions` route.
- **Breaking**: `s3.py` path helpers change shape — any caller using `raw_key(entity, run_date, ts)` must switch to the new partition args. Today only on-hold modules (`etl.py`, `ingest.py`, `curate.py`) reference them, so impact is contained.
- **Re-deploy**: Adding `TBLPROPERTIES` requires dropping and recreating the tables (Athena doesn't allow adding projection via `ALTER`). `/query/create-tables` will need to either be called against an empty database, or a `DROP TABLE` step added before re-creating.
