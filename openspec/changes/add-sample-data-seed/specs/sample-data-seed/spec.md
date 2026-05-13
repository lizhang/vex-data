## ADDED Requirements

### Requirement: scripts/seed_sample_data.py is an argparse CLI

The script SHALL expose the following CLI flags via `argparse`:

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--season` | int | 190 | `p_season_id` partition value |
| `--program` | int | 1 | `p_program_id` partition value (VRC) |
| `--events` | int | 10 | number of events to generate |
| `--teams` | int | 100 | number of teams in the pool |
| `--matches-per-event` | int | 10 | matches generated per event |
| `--seed` | int | 42 | random seed for determinism |
| `--staging-dir` | path | `./sample_data` | local Parquet output directory |
| `--skip-upload` | flag | false | when set, skip S3 upload |
| `--clean` | flag | false | when set, delete prior local + S3 partition contents before writing |

#### Scenario: Defaults produce a runnable dataset

- **WHEN** `python scripts/seed_sample_data.py` is run with no flags
- **THEN** the script SHALL generate and upload 10 events / 100 teams / 100 matches with `season_id=190`, `program_id=1`

#### Scenario: `--skip-upload` writes locally only

- **WHEN** the flag is set
- **THEN** the script SHALL write all 8 Parquet files under `--staging-dir` and SHALL NOT call any S3 API

#### Scenario: `--clean` empties the partition first

- **WHEN** the flag is set and the staging dir or S3 partition already contains files
- **THEN** the prior contents SHALL be deleted before any new files are written (local: `shutil.rmtree`; S3: `list_objects_v2` + `delete_objects`)

### Requirement: Generated data is referentially consistent across all 8 tables

Every foreign-key-like reference between generated tables SHALL be valid:

- Every `event_id` referenced in `matches`, `skills`, `rankings` SHALL exist in `events`.
- Every `team_id` referenced in `matches.red_teams[]`, `matches.blue_teams[]`, `skills`, `rankings` SHALL exist in `teams`.
- Each derived table SHALL be a pure aggregation of its source base tables (no independent random values).

#### Scenario: Derived team_event_summary aggregates matches

- **WHEN** the base `matches` rows contain `K` matches for a given `(event_id, team_id)`
- **THEN** the `team_event_summary` row for that key SHALL have `wins + losses + ties = K`

#### Scenario: Derived team_skill_summary aggregates skills

- **WHEN** the base `skills` rows for a given `team_id` contain scores `[s1, s2, ..., sn]`
- **THEN** the `team_skill_summary` row SHALL have `best_skill_score = max(s)` and `worst_skill_score = min(s)`

#### Scenario: Derived team_score_summary aggregates matches

- **WHEN** the base `matches` rows contain scores attributable to a given `team_id`
- **THEN** the `team_score_summary` row SHALL have `high_score = max(...)` and `total_points = sum(...)`

### Requirement: Parquet schemas match curated/*.sql exactly

A `scripts/sample_data_schemas.py` module SHALL export `SCHEMAS: dict[str, pa.Schema]` keyed by table name. Each schema SHALL match the column names, types, and nested `array<struct<…>>` shapes declared in the corresponding `curated/<table>.sql`.

#### Scenario: Schemas dict has all 8 tables

- **WHEN** `from scripts.sample_data_schemas import SCHEMAS` is executed
- **THEN** `SCHEMAS.keys()` SHALL equal `{events, teams, matches, skills, rankings, team_event_summary, team_skill_summary, team_score_summary}`

#### Scenario: Nested array<struct<…>> fields are valid pyarrow types

- **WHEN** `SCHEMAS["matches"]` is inspected
- **THEN** the `red_teams` and `blue_teams` fields SHALL be `pa.list_(pa.struct([("team_id", pa.int64()), ("number", pa.string())]))` (or equivalent), and `SCHEMAS["events"].field("divisions")` SHALL be `pa.list_(pa.struct([("id", pa.int64()), ("name", pa.string())]))`

#### Scenario: Athena reads the produced Parquet without schema mismatch

- **WHEN** the script writes a Parquet file using `SCHEMAS["events"]` and uploads it to the curated `events` partition path
- **AND** `POST /query/execute` selects from `events`
- **THEN** Athena SHALL return the rows without `HIVE_BAD_DATA` or `HIVE_CANNOT_OPEN_SPLIT_ERROR`

### Requirement: Determinism via `--seed`

Two runs of the script with the same `--seed`, scale flags, and `--clean` SHALL produce byte-identical Parquet content for each table.

#### Scenario: Same seed reproduces the same dataset

- **WHEN** `seed_sample_data.py --seed 42 --skip-upload --clean` is run twice
- **THEN** the two runs SHALL produce Parquet files whose contents (rows, in order) are identical (excluding the timestamp in the filename)

### Requirement: Local staging directory mirrors S3 layout

For each table, the local Parquet path SHALL be `<staging_dir>/<curated_key(...)>` where `curated_key` is the helper in `app/services/s3.py`. The S3 upload target SHALL use the same `curated_key(...)` value as the S3 object key.

#### Scenario: Local and S3 paths share a key

- **WHEN** the script generates a `matches` Parquet for `(season=190, program=1, event=12345)`
- **THEN** the local file path SHALL be `<staging_dir>/curated/matches/p_season_id=190/p_program_id=1/p_event_id=12345/{ts}.parquet`
- **AND** the uploaded S3 object key SHALL be `curated/matches/p_season_id=190/p_program_id=1/p_event_id=12345/{ts}.parquet`

## MODIFIED Requirements

### Requirement: `app/services/s3.py` path helpers use Hive partition keys

`raw_key` and `curated_key` SHALL accept Hive partition values (`season_id`, `program_id`, optional `event_id`) and produce paths that match the curated DDL's partition columns. The earlier `dt={iso-date}` scheme is replaced.

#### Scenario: curated_key for a season-and-program table

- **WHEN** `curated_key("events", season_id=190, program_id=1, timestamp="20260512T000000Z")` is called
- **THEN** it SHALL return `curated/events/p_season_id=190/p_program_id=1/20260512T000000Z.parquet`

#### Scenario: curated_key for an event-scoped table

- **WHEN** `curated_key("matches", season_id=190, program_id=1, timestamp="20260512T000000Z", event_id=12345)` is called
- **THEN** it SHALL return `curated/matches/p_season_id=190/p_program_id=1/p_event_id=12345/20260512T000000Z.parquet`

#### Scenario: list_curated_keys filters by partition

- **WHEN** `list_curated_keys("events", season_id=190, program_id=1)` is called
- **THEN** the prefix SHALL be `curated/events/p_season_id=190/p_program_id=1/` and the result SHALL be the matching object keys
