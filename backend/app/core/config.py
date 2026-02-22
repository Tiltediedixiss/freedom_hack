"""
F.I.R.E. Application Configuration.
"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings

# Project root .env (so it works when running from backend/ or project root)
_ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_ENV_FILE = os.path.join(_ROOT_DIR, ".env")


class Settings(BaseSettings):
    # ── Database ──
    DATABASE_URL: str = "postgresql+asyncpg://fire_user:fire_secret_password@localhost:5432/fire_db"
    PGCRYPTO_KEY: str = "fire_encryption_key_change_me"

    # ── OpenRouter ──
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "google/gemini-2.0-flash-001"
    OPENROUTER_SENTIMENT_MODEL: str = "google/gemini-2.0-flash-001"

    # ── Groq (optional; used for sentiment when set) ──
    GROQ_API_KEY: str = ""
    GROQ_SENTIMENT_MODEL: str = "llama3-8b-8192"

    # ── 2GIS Geocoding ──
    TWOGIS_API_KEY: str = ""

    # ── Spam filter ──
    SPAM_THRESHOLD: float = 0.95

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
        env_file = _ENV_FILE
        case_sensitive = True
        extra = "ignore"  # allow extra .env vars (e.g. POSTGRES_* for docker-compose)


@lru_cache()
def get_settings() -> Settings:
    return Settings()