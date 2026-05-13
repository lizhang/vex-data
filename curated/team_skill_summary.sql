CREATE EXTERNAL TABLE team_skill_summary (
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
LOCATION 's3://vex-search-data-v1/curated/team_skill_summary/';