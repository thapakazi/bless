from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_db: str = "bless"
    clickhouse_user: str = "bless"
    clickhouse_password: str = "bless"
    # ClickHouse Cloud needs HTTPS. Auto-enabled when host looks like *.clickhouse.cloud
    # unless explicitly overridden.
    clickhouse_secure: bool | None = None

    anthropic_api_key: str = ""
    claude_model_enricher: str = "claude-sonnet-4-6"
    claude_model_reporter: str = "claude-opus-4-7"
    claude_model_chat: str = "claude-opus-4-7"

    truefoundry_endpoint: str = ""
    truefoundry_api_key: str = ""

    guild_api_key: str = ""

    # Airbyte Cloud OAuth client (preferred — matches Airbyte Cloud UI)
    airbyte_organization_id: str = ""
    airbyte_client_id: str = ""
    airbyte_client_secret: str = ""
    # Legacy single-key flow (kept for prompt.md compatibility)
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
