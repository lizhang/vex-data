CREATE EXTERNAL TABLE matches (
  match_id bigint,
  event_id bigint,
  event_sku string,
  event_name string,

  division_id bigint,
  division_name string,

  round int,
  round_name string,
  instance int,
  matchnum int,
  scheduled_time timestamp,
  started_time timestamp,

  field string,
  scored boolean,

  red_score int,
  blue_score int,

  red_teams array<struct<
    team_id: bigint,
    number: string
  >>,

  blue_teams array<struct<
    team_id: bigint,
    number: string
  >>
)
PARTITIONED BY (
  p_season_id int,
  p_program_id int,
  p_event_id bigint
)
STORED AS PARQUET
LOCATION 's3://vex-data/curated/matches/';