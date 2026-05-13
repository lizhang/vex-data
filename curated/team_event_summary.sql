CREATE EXTERNAL TABLE team_event_summary (
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
LOCATION 's3://vex-data/curated/team_event_summary/';