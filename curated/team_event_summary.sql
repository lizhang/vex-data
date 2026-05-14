CREATE EXTERNAL TABLE IF NOT EXISTS team_event_summary (
  event_id bigint,
  event_sku string,
  event_name string,
  event_start_date timestamp,

  team_id bigint,
  team_number string,
  team_name string,
  organization string,

  ranking int,
  wins int,
  losses int,
  ties int,

  best_score int,
  best_skills_score int,
  skills_rank int
)
PARTITIONED BY (
  p_season_id int,
  p_program_id int
)
STORED AS PARQUET
LOCATION 's3://vex-search-data-v1/curated/team_event_summary/'
TBLPROPERTIES (
  'projection.enabled' = 'true',
  'projection.p_season_id.type' = 'integer',
  'projection.p_season_id.range' = '180,210',
  'projection.p_program_id.type' = 'integer',
  'projection.p_program_id.range' = '1,100',
  'storage.location.template' = 's3://vex-search-data-v1/curated/team_event_summary/p_season_id=${p_season_id}/p_program_id=${p_program_id}/'
);