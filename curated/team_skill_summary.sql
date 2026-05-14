CREATE EXTERNAL TABLE IF NOT EXISTS team_skill_summary (
  team_id bigint,
  team_number string,
  team_name string,
  organization string,

  best_skill_score int,
  worst_skill_score int,
  avg_skill_score int,

  best_skill_event_id bigint,
  worst_skill_event_id bigint
)
PARTITIONED BY (
  p_season_id int,
  p_program_id int
)
STORED AS PARQUET
LOCATION 's3://vex-search-data-v1/curated/team_skill_summary/'
TBLPROPERTIES (
  'projection.enabled' = 'true',
  'projection.p_season_id.type' = 'integer',
  'projection.p_season_id.range' = '180,210',
  'projection.p_program_id.type' = 'integer',
  'projection.p_program_id.range' = '1,100',
  'storage.location.template' = 's3://vex-search-data-v1/curated/team_skill_summary/p_season_id=${p_season_id}/p_program_id=${p_program_id}/'
);