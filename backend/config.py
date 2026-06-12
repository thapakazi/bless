from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_db: str = "bless"
    clickhouse_user: str = "bless"
    clickhouse_password: str = "bless"

    pioneer_api_key: str = ""
    pioneer_base_url: str = ""
    pioneer_model: str = ""

    truefoundry_endpoint: str = ""
    truefoundry_api_key: str = ""

    guild_api_key: str = ""

    airbyte_api_key: str = ""
    airbyte_workspace_id: str = ""

    composio_api_key: str = ""
    slack_channel: str = "#general"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
