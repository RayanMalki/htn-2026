from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/hypecheck.db"
    redis_url: str = "redis://localhost:6379/0"
    media_root: Path = Path("data")
    model_mode: Literal["mock", "live"] = "mock"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    elasticsearch_url: str = ""
    elasticsearch_api_key: str = ""
    elastic_index: str = "hypecheck-passages-v1"
    elastic_inference_id: str = ".elser-2-elastic"
    elastic_semantic: bool = True
    sentry_dsn: str = ""
    sentry_environment: str = "development"
    release: str = "hypecheck-local"
    admin_token: str = ""
    enable_failure_injection: bool = False
    max_active_cases: int = 10
    rate_limit_per_minute: int = 6
    case_timeout_seconds: int = 120
    research_timeout_seconds: int = 35
    uptime_url: str = "http://127.0.0.1:8000/healthz"
    # Appended rather than grouped with the other providers, so that concurrent
    # branches adding their own settings do not collide on the same anchor line.
    gptzero_api_key: str = ""
    gptzero_filler_reading: bool = False


@lru_cache
def settings() -> Settings:
    return Settings()
