from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "TB AI Copilot"
    host: str = "0.0.0.0"
    port: int = 8097

    tb_base_url: str = "http://127.0.0.1:9091"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 60.0

    redis_url: str = ""
    memory_ttl_seconds: int = 1800
    memory_max_messages: int = 12

    rate_limit_count: int = 12
    rate_limit_window_ms: int = 300_000
    rate_limit_min_interval_ms: int = 1500

    rag_persist_dir: str = str(ROOT / "data" / "chroma")
    knowledge_dir: str = str(ROOT / "knowledge")
    reports_dir: str = "/var/tmp/delhivery-reports"
    rag_top_k: int = 4

    cors_origins: str = "*"
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
