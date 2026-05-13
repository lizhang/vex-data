CREATE EXTERNAL TABLE team_score_summary (
  team_id bigint,
  team_number string,
  team_name string,
  organization string,

  high_score int,
  average_points double,
  total_points int,

  best_score_event_id bigint
)
PARTITIONED BY (
  p_season_id int,
  p_program_id int
)
STORED AS PARQUET
LOCATION 's3://vex-search-data-v1/curated/team_score_summary/';