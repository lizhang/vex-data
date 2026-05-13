CREATE EXTERNAL TABLE teams (
  team_id bigint,
  number string,
  team_name string,
  organization string,

  program_id int,
  program_name string,

  city string,
  region string,
  postcode string,
  country string,

  grade string,
  registered boolean
)
PARTITIONED BY (
  p_season_id int,
  p_program_id int
)
STORED AS PARQUET
LOCATION 's3://vex-data/curated/teams/';