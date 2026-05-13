## ADDED Requirements

### Requirement: Seed script generates valid Parquet for all 7 curated tables
`scripts/seed_sample_data.py` SHALL generate synthetic rows for all 7 curated tables (`events`, `teams`, `matches`, `skills`, `rankings`, `team_event_summary`, `team_skill_summary`) using pyarrow schemas that exactly match the column names and types defined in `curated/*.sql`, including `list<struct<...>>` types for `matches.red_teams` and `matches.blue_teams`.

#### Scenario: Schema matches DDL for base tables
- **WHEN** the seed script writes a Parquet file for `events`, `teams`, `matches`, `skills`, or `rankings`
- **THEN** every column name and Arrow type SHALL match the corresponding `curated/{entity}.sql` definition, and Athena SHALL be able to read the file without a schema error

#### Scenario: Schema matches DDL for derived tables
- **WHEN** the seed script writes a Parquet file for `team_event_summary` or `team_skill_summary`
- **THEN** every column name and Arrow type SHALL match the corresponding `curated/{entity}.sql` definition

#### Scenario: ARRAY<STRUCT> columns are correctly encoded
- **WHEN** the seed script writes `matches` Parquet
- **THEN** `red_teams` and `blue_teams` columns SHALL be encoded as `pa.list_(pa.struct([('team_id', pa.int64()), ('number', pa.string())]))` and Athena UNNEST SHALL work on those columns

### Requirement: Seed script uploads to correct S3 partition paths
The script SHALL write one Parquet file per partition group and upload each to the S3 path that matches the Hive partition scheme used by the Athena external tables.

#### Scenario: Season+program partitioned tables
- **WHEN** seeding `events`, `teams`, `team_event_summary`, or `team_skill_summary` with `season_id=190`, `program_id=1`
- **THEN** the file SHALL be uploaded to `s3://{bucket}/curated/{entity}/p_season_id=190/p_program_id=1/{timestamp}.parquet`

#### Scenario: Season+program+event partitioned tables
- **WHEN** seeding `matches`, `skills`, or `rankings` with `season_id=190`, `program_id=1`, `event_id=1001`
- **THEN** the file SHALL be uploaded to `s3://{bucket}/curated/{entity}/p_season_id=190/p_program_id=1/p_event_id=1001/{timestamp}.parquet`

### Requirement: Seed data covers all 5 query strategies
The seeded rows SHALL include enough variety to exercise all 5 `SearchQuery` routing strategies: EVENTS, MATCHES, TEAM_EVENT, TEAM_SKILL, TEAM_RANKING, and the TEAM_MATCH_SCORE corner case.

#### Scenario: Sufficient seed volume
- **WHEN** the seed script completes
- **THEN** there SHALL be at least 3 events, 10 teams, 30 matches, skills entries for each team per event, rankings entries for each team per event, and rows in both derived summary tables

#### Scenario: Teams appear in matches
- **WHEN** match rows are seeded
- **THEN** the `number` field in `red_teams` and `blue_teams` structs SHALL match `number` values from the seeded `teams` rows so UNNEST team-filter queries return results
