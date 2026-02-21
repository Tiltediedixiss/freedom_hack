"""
F.I.R.E. Application Configuration.
Reads settings from environment variables.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # ── Database ──
    DATABASE_URL: str = "postgresql+asyncpg://fire_user:fire_secret_password@localhost:5432/fire_db"

    # ── OpenRouter ──
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "google/gemini-2.0-flash-001"
    OPENROUTER_SENTIMENT_MODEL: str = "google/gemini-2.0-flash-001"

    # ── 2GIS Geocoding ──
    TWOGIS_API_KEY: str = ""

    # ── App ──
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    SECRET_KEY: str = "change-me-in-production"

    # ── Upload ──
    UPLOAD_DIR: str = "/app/uploads"
    MAX_UPLOAD_SIZE_MB: int = 50

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
