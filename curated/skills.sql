CREATE EXTERNAL TABLE skills (
  event_id bigint,
  event_sku string,

  team_id bigint,
  team_number string,
  team_name string,

  type string,              -- driver / programming / autonomous
  score int,
  attempts int,
  rank int,

  skills_stop_time int,
  created_at timestamp
)
PARTITIONED BY (
  p_season_id int,
  p_program_id int,
  p_event_id bigint
)
STORED AS PARQUET
LOCATION 's3://vex-data/curated/skills/';