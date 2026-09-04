from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://wallet:wallet@localhost:5432/wallet_db"
    # Отдельная БД для тестов, чтобы pytest не чистил рабочие данные.
    test_database_url: str | None = None

    db_echo: bool = False
    db_pool_size: int = Field(default=20, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout: int = Field(default=10, ge=1)
    db_pool_recycle: int = Field(default=1800, ge=-1)

    app_name: str = "Wallet API"
    app_version: str = "2.0.0"
    log_level: str = "INFO"
    serve_ui: bool = True
    cors_origins: list[str] = Field(default_factory=list)

    rate_limit_enabled: bool = True
    rate_limit_requests: int = Field(default=100, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)

    metrics_enabled: bool = True

    @property
    def effective_test_database_url(self) -> str:
        return self.test_database_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
