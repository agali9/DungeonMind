"""Application configuration, loaded once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    FLASK_ENV: str = os.getenv("FLASK_ENV", "development")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL", "sqlite:///dnd.db")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_NARRATION_MODEL: str = os.getenv("GEMINI_NARRATION_MODEL", "gemini-2.5-flash")
    GEMINI_REASONING_MODEL: str = os.getenv("GEMINI_REASONING_MODEL", "gemini-2.5-pro")

    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "1800"))

    TURNS_BEFORE_COMPACTION: int = int(os.getenv("TURNS_BEFORE_COMPACTION", "12"))
    MEMOIR_TARGET_CHARS: int = int(os.getenv("MEMOIR_TARGET_CHARS", "1200"))
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "")

    @property
    def SOCKETIO_CORS_ALLOWED_ORIGINS(self) -> list[str] | str:
        if self.FLASK_ENV == "development":
            return "*"
        origins = [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
        if not origins:
            raise RuntimeError("ALLOWED_ORIGINS must be set when FLASK_ENV is not development")
        return origins

    @property
    def SOCKETIO_ASYNC_MODE(self) -> str:
        return os.getenv("SOCKETIO_ASYNC_MODE", "gevent")


config = Config()
