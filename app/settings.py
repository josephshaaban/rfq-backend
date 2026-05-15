from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
