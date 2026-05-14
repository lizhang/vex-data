CREATE EXTERNAL TABLE IF NOT EXISTS rankings (
  event_id bigint,
  event_sku string,
  division_id bigint,
  division_name string,

  team_id bigint,
  team_number string,
  team_name string,

  rank int,
  wins int,
  losses int,
  ties int,
  wp int,
  ap int,
  sp int,
  high_score int,
  average_points double,
  total_points int
)
PARTITIONED BY (
  p_season_id int,
  p_program_id int,
  p_event_id bigint
)
STORED AS PARQUET
LOCATION 's3://vex-search-data-v1/curated/rankings/'
TBLPROPERTIES (
  'projection.enabled' = 'true',
  'projection.p_season_id.type' = 'integer',
  'projection.p_season_id.range' = '180,210',
  'projection.p_program_id.type' = 'integer',
  'projection.p_program_id.range' = '1,100',
  'projection.p_event_id.type' = 'integer',
  'projection.p_event_id.range' = '1,99999999',
  'storage.location.template' = 's3://vex-search-data-v1/curated/rankings/p_season_id=${p_season_id}/p_program_id=${p_program_id}/p_event_id=${p_event_id}/'
);