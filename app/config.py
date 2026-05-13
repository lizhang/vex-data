from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    robotevents_api_key: str
    robotevents_base_url: str = "https://www.robotevents.com/api/v2"

    s3_bucket: str
    s3_raw_prefix: str = "raw"
    s3_curated_prefix: str = "curated"

    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    athena_database: str = "vex_data"
    athena_output_location: str = ""
    athena_workgroup: str = "vex-data-wg"

    def model_post_init(self, __context) -> None:
        if not self.athena_output_location:
            object.__setattr__(
                self,
                "athena_output_location",
                f"s3://{self.s3_bucket}/athena-results/",
            )


settings = Settings()
