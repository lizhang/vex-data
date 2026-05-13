## ADDED Requirements

### Requirement: Every curated DDL enables partition projection

Each of the 8 `curated/*.sql` files SHALL declare `TBLPROPERTIES` enabling Athena partition projection, so that partitions are discovered from S3 path templates at query time without `MSCK REPAIR TABLE` or `ALTER TABLE ADD PARTITION`.

#### Scenario: Season-and-program-only tables enable projection on 2 columns

- **WHEN** the DDL is for `events`, `teams`, `team_event_summary`, `team_skill_summary`, or `team_score_summary`
- **THEN** `TBLPROPERTIES` SHALL include `'projection.enabled' = 'true'`, `'projection.p_season_id.type' = 'integer'`, `'projection.p_season_id.range' = '180,210'`, `'projection.p_program_id.type' = 'integer'`, `'projection.p_program_id.range' = '1,100'`, and `'storage.location.template' = 's3://${bucket}/curated/${table}/p_season_id=${p_season_id}/p_program_id=${p_program_id}/'`

#### Scenario: Event-scoped tables enable projection on 3 columns

- **WHEN** the DDL is for `matches`, `skills`, or `rankings`
- **THEN** `TBLPROPERTIES` SHALL additionally include `'projection.p_event_id.type' = 'integer'`, `'projection.p_event_id.range' = '1,99999999'`, and `'storage.location.template'` SHALL append `/p_event_id=${p_event_id}/`

### Requirement: Athena resolves partitions without external registration

After `POST /query/create-tables` creates these tables, querying a partition `(p_season_id=190, p_program_id=1[, p_event_id=N])` SHALL return any Parquet files at the matching S3 path, with no intervening `MSCK REPAIR TABLE`, `ALTER TABLE ADD PARTITION`, or Glue `BatchCreatePartition` call.

#### Scenario: Newly uploaded partition is queryable

- **WHEN** a Parquet file is uploaded to `s3://${bucket}/curated/events/p_season_id=190/p_program_id=1/{ts}.parquet`
- **AND** `POST /query/execute` is called with `entity = "events"` and a filter that prunes to `p_season_id = 190, p_program_id = 1`
- **THEN** the rows in that Parquet SHALL appear in the response

#### Scenario: Partition outside the declared range is invisible

- **WHEN** a Parquet file is uploaded under `p_program_id=999` and the DDL's `projection.p_program_id.range` is `'1,100'`
- **THEN** querying for `program_id = 999` SHALL return zero rows (documented constraint of partition projection)

### Requirement: Partition projection ranges accommodate VEX seasons and programs

The declared ranges SHALL cover all known VEX season IDs (currently 180–210) and all known VEX program IDs (currently 1–100).

#### Scenario: Range widening requires a DDL change and table re-create

- **WHEN** a new season or program id falls outside the declared range
- **THEN** the DDL SHALL be edited, the table SHALL be dropped, and `POST /query/create-tables` SHALL be re-run (Athena does not allow altering projection on existing tables)
