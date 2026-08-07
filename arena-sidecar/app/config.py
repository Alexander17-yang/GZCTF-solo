from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(
        part.strip() for part in os.getenv(name, "").split(",") if part.strip()
    )


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    gzctf_internal_url: str
    profile_path: str
    request_timeout_seconds: float
    identity_cache_ttl_seconds: float
    identity_stale_if_error_seconds: float
    identity_error_backoff_seconds: float
    cookie_name: str
    cors_origins: tuple[str, ...]
    trusted_hosts: tuple[str, ...]
    root_path: str
    local_admin_enabled: bool
    local_admin_username: str
    local_admin_password_hash: str
    token_secret: str
    token_ttl_seconds: int
    flag_pepper: str

    @classmethod
    def from_env(cls) -> "Settings":
        database_path = Path(os.getenv("ARENA_DATABASE_PATH", "/data/arena.db"))
        return cls(
            database_path=database_path,
            gzctf_internal_url=os.getenv(
                "GZCTF_INTERNAL_URL", "http://gzctf:8080"
            ).rstrip("/"),
            profile_path=os.getenv("GZCTF_PROFILE_PATH", "/api/account/profile"),
            request_timeout_seconds=float(
                os.getenv("GZCTF_REQUEST_TIMEOUT_SECONDS", "5")
            ),
            identity_cache_ttl_seconds=float(
                os.getenv("GZCTF_IDENTITY_CACHE_TTL_SECONDS", "10")
            ),
            identity_stale_if_error_seconds=float(
                os.getenv("GZCTF_IDENTITY_STALE_IF_ERROR_SECONDS", "60")
            ),
            identity_error_backoff_seconds=float(
                os.getenv("GZCTF_IDENTITY_ERROR_BACKOFF_SECONDS", "3")
            ),
            cookie_name=os.getenv("GZCTF_COOKIE_NAME", "GZCTF_Token"),
            cors_origins=_csv_env("ARENA_CORS_ORIGINS"),
            trusted_hosts=_csv_env("ARENA_TRUSTED_HOSTS"),
            root_path=os.getenv("ARENA_ROOT_PATH", "").rstrip("/"),
            local_admin_enabled=_bool_env("ARENA_LOCAL_ADMIN_ENABLED", False),
            local_admin_username=os.getenv("ARENA_LOCAL_ADMIN_USERNAME", "Admin"),
            local_admin_password_hash=os.getenv("ARENA_LOCAL_ADMIN_PASSWORD_HASH", ""),
            token_secret=os.getenv("ARENA_TOKEN_SECRET", ""),
            token_ttl_seconds=int(os.getenv("ARENA_TOKEN_TTL_SECONDS", "3600")),
            flag_pepper=os.getenv("ARENA_FLAG_PEPPER", ""),
        )

    def validate(self) -> None:
        if not 0 < self.identity_cache_ttl_seconds <= 300:
            raise RuntimeError(
                "GZCTF_IDENTITY_CACHE_TTL_SECONDS must be greater than 0 and at most 300"
            )
        if not 0 <= self.identity_stale_if_error_seconds <= 3600:
            raise RuntimeError(
                "GZCTF_IDENTITY_STALE_IF_ERROR_SECONDS must be between 0 and 3600"
            )
        if not 0 <= self.identity_error_backoff_seconds <= 60:
            raise RuntimeError(
                "GZCTF_IDENTITY_ERROR_BACKOFF_SECONDS must be between 0 and 60"
            )
        if self.local_admin_enabled:
            if not self.local_admin_password_hash:
                raise RuntimeError(
                    "ARENA_LOCAL_ADMIN_PASSWORD_HASH is required when local admin login is enabled"
                )
            if len(self.token_secret) < 32:
                raise RuntimeError(
                    "ARENA_TOKEN_SECRET must contain at least 32 characters"
                )
        if self.flag_pepper and len(self.flag_pepper) < 16:
            raise RuntimeError(
                "ARENA_FLAG_PEPPER must contain at least 16 characters when configured"
            )


settings = Settings.from_env()
