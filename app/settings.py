from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "local"
    port: int = 8000
    log_level: str = "INFO"

    # Database
    sqlite_db_path: str = "/app/data/takehome.sqlite3"

    # Monitoring
    monitor_source: str = "gdelt"
    gdelt_query: str = "manufacturing supply chain disruption"
    poll_interval_seconds: int = 300
    gdelt_max_records: int = 25

    # AI extraction (optional — falls back to rule-based if not set)
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    extraction_model: str = "rule_based"  # "rule_based" | "openai" | "anthropic"


@lru_cache
def get_settings() -> Settings:
    return Settings()
