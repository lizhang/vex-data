CREATE EXTERNAL TABLE events (
  event_id bigint,
  sku string,
  name string,
  program_id int,
  program_name string,
  season_id int,
  season_name string,

  start_date timestamp,
  end_date timestamp,

  city string,
  region string,
  postcode string,
  country string,
  venue string,

  event_type string,
  level string,
  divisions array<struct<
    id: bigint,
    name: string
  >>
)
PARTITIONED BY (
  p_season_id int,
  p_program_id int
)
STORED AS PARQUET
LOCATION 's3://vex-search-data-v1/curated/events/';