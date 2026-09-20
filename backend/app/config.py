from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/hypecheck.db"
    redis_url: str = "redis://localhost:6379/0"
    media_root: Path = Path("data")
    model_mode: Literal["mock", "live"] = "mock"
    model_provider: Literal["openai", "backboard", "gemini"] = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    backboard_api_key: str = ""
    backboard_model: str = "gpt-4o-mini"
    backboard_llm_provider: str = "openai"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    elasticsearch_url: str = ""
    elasticsearch_api_key: str = ""
    elastic_index: str = "hypecheck-passages-v2"
    elastic_inference_id: str = ".elser-2-elastic"
    elastic_semantic: bool = True
    medlineplus_enabled: bool = True
    sentry_dsn: str = ""
    sentry_environment: str = "development"
    sentry_enable_logs: bool = True
    sentry_traces_sample_rate: float = Field(default=1.0, ge=0, le=1)
    sentry_profile_session_sample_rate: float = Field(default=0.2, ge=0, le=1)
    release: str = "hypecheck-local"
    admin_token: str = ""
    enable_failure_injection: bool = False
    max_active_cases: int = 10
    rate_limit_per_minute: int = 6
    case_timeout_seconds: int = 120
    research_timeout_seconds: int = 35
    video_enabled: bool = True
    video_timeout_seconds: int = 150
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "coral"
    uptime_url: str = "http://127.0.0.1:8000/healthz"

    @property
    def model_configured(self) -> bool:
        return self.model_mode == "mock" or bool(
            {"openai": self.openai_api_key, "backboard": self.backboard_api_key, "gemini": self.gemini_api_key}[self.model_provider])

    @property
    def model_id(self) -> str:
        if self.model_mode == "mock":
            return "prepared-fixture-v1"
        if self.model_provider == "openai":
            return f"openai/{self.openai_model}/whisper-1"
        if self.model_provider == "backboard":
            return f"backboard/{self.backboard_llm_provider}/{self.backboard_model}/whisper-1/windows-10s"
        return self.gemini_model


@lru_cache
def settings() -> Settings:
    return Settings()
