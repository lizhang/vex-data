CREATE EXTERNAL TABLE rankings (
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
LOCATION 's3://vex-data/curated/rankings/';