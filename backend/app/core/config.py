"""Application settings, loaded from environment / .env.

Everything that differs between installations (mode, database, secrets, paths)
lives here. Nothing in this file is a manufacturing formula or constant.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


def read_version() -> str:
    try:
        return (ROOT_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


class AppMode(str, Enum):
    OFFLINE = "offline"
    ONLINE = "online"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_mode: AppMode = AppMode.OFFLINE
    app_name: str = "MYTech Solutions"

    # Runtime role: RLS enforced. Never owner, never BYPASSRLS.
    database_url: str = "postgresql+psycopg://mytech_app:mytech_app@localhost:5432/mytech"
    # Bootstrap role (BYPASSRLS): login lookup, background jobs, vendor tooling only.
    database_system_url: str = "postgresql+psycopg://mytech_system:mytech_system@localhost:5432/mytech"
    # Owner role: migrations only.
    database_owner_url: str = "postgresql+psycopg://mytech_owner:mytech_owner@localhost:5432/mytech"

    jwt_secret: str = Field(default="change-me-change-me-change-me-change-me", min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    # Offline licensing
    license_file: Path = Path("license/license.json")
    license_grace_days: int = 14

    # Files (model images etc.)
    media_dir: Path = Path("media")

    # Backups
    backup_dir: Path = Path("backups")
    backup_keep: int = 14
    backup_hour: int = 2
    pg_bin_dir: str = ""

    # Network
    discovery_enabled: bool = True
    discovery_udp_port: int = 47800
    http_port: int = 8000
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    cors_origins: list[str] = []

    # Oldest client version allowed to talk to this server.
    min_client_version: str = "0.1.0"

    @property
    def version(self) -> str:
        return read_version()

    @property
    def is_online(self) -> bool:
        return self.app_mode == AppMode.ONLINE


@lru_cache
def get_settings() -> Settings:
    return Settings()
