# Modified by Tofu on 2026-10-25 (https://github.com/tofu-gallery/bracket): reads the DATABASE_URL Tofu gives the
# app, derives JWT_SECRET from it when unset, sizes the database pool and adds SOURCE_URL. See TOFU.md.
import hashlib
import logging
import os
import sys
from enum import auto
from typing import Annotated
from urllib.parse import urlsplit, urlunsplit

import sentry_sdk
from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

from bracket.utils.types import EnumAutoStr


class Environment(EnumAutoStr):
    PRODUCTION = auto()
    DEVELOPMENT = auto()
    DEMO = auto()
    CI = auto()

    def get_log_level(self) -> int:
        return {
            Environment.CI: logging.WARNING,
            Environment.DEVELOPMENT: logging.DEBUG,
            Environment.PRODUCTION: logging.INFO,
            Environment.DEMO: logging.INFO,
        }[self]


class Config(BaseSettings):
    admin_email: str | None = None
    admin_password: str | None = None
    allow_insecure_http_sso: bool = False
    allow_user_registration: bool = True
    allow_demo_user_registration: bool = True
    captcha_secret: str | None = None
    base_url: str = "http://localhost:8400"
    cors_origin_regex: str = ""
    cors_origins: str = "*"
    jwt_secret: str
    auto_run_migrations: bool = True
    pg_dsn: PostgresDsn = PostgresDsn("postgresql://user:pass@localhost:5432/db")
    sentry_dsn: str | None = None
    serve_frontend: bool = False
    api_prefix: str = ""
    # Tofu (2026-10-25): the database pool (asyncpg's own default is 10 connections, held from the start), and the
    # address of this copy's source code, which GET <API_PREFIX>/source redirects to (AGPL-3.0 section 13).
    pg_pool_min_size: int = 1
    pg_pool_max_size: int = 5
    source_url: str = "https://github.com/tofu-gallery/bracket"

    def is_cors_enabled(self) -> bool:
        return self.cors_origins != "*"


class CIConfig(Config):
    model_config = SettingsConfigDict(env_file="ci.env")


class DevelopmentConfig(Config):
    admin_email: Annotated[str | None, Field("test@example.org")]
    admin_password: Annotated[str | None, Field("aeGhoe1ahng2Aezai0Dei6Aih6dieHoo")]
    allow_insecure_http_sso: Annotated[bool, Field(True)]
    jwt_secret: Annotated[
        str, Field("7495204c062787f257b12d03b88d80da1d338796a6449666eb634c9efbbf5fa7")
    ]

    model_config = SettingsConfigDict(env_file="dev.env")


class ProductionConfig(Config):
    model_config = SettingsConfigDict(env_file="prod.env")


class DemoConfig(Config):
    model_config = SettingsConfigDict(env_file="demo.env")


def currently_testing() -> bool:
    return "pytest" in sys.modules


def tofu_pg_dsn(database_url: str) -> str:
    """
    Tofu (2026-10-25): PG_DSN from the DATABASE_URL Tofu gives the app.

    Tofu's DATABASE_URL names Supabase's transaction pooler (port 6543 on <region>.pooler.supabase.com). Bracket talks
    to PostgreSQL through asyncpg, which prepares every statement and runs it in a second round trip, outside any
    transaction; the transaction pooler may send that second round trip to another server connection, where the
    statement does not exist. The same pooler serves session mode on port 5432 with the same user and password, and
    keeps one server connection per client connection, so the port is moved there. Any other address is kept as it is.
    """
    parts = urlsplit(database_url)
    scheme = "postgresql" if parts.scheme in ("postgres", "postgresql") else parts.scheme
    netloc = parts.netloc
    if (parts.hostname or "").endswith(".pooler.supabase.com") and parts.port == 6543:
        netloc = f"{netloc.rsplit(':', 1)[0]}:5432"
    return urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))


def apply_tofu_defaults() -> None:
    """
    Tofu (2026-10-25): when DATABASE_URL is set, fill in the two settings Bracket needs to start and Tofu does not set.
    A PG_DSN or JWT_SECRET the owner sets is always kept.

    - PG_DSN: DATABASE_URL in session mode (see tofu_pg_dsn).
    - JWT_SECRET: the SHA-256 of "bracket-jwt-secret:" followed by the whole DATABASE_URL, as 64 hex characters. It
      signs the sign-in tokens, so a new DATABASE_URL (a new password, host or option) signs everybody out once.
    """
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return
    if not os.getenv("PG_DSN"):
        os.environ["PG_DSN"] = tofu_pg_dsn(database_url)
    if not os.getenv("JWT_SECRET"):
        digest = hashlib.sha256(f"bracket-jwt-secret:{database_url}".encode()).hexdigest()
        os.environ["JWT_SECRET"] = digest


apply_tofu_defaults()


environment = Environment(
    os.getenv("ENVIRONMENT", "CI" if currently_testing() else "DEVELOPMENT").upper()
)
config: Config

match environment:
    case Environment.CI:
        config = CIConfig()  # type: ignore[call-arg]
    case Environment.DEVELOPMENT:
        config = DevelopmentConfig()  # type: ignore[call-arg]
    case Environment.PRODUCTION:
        config = ProductionConfig()  # type: ignore[call-arg]
    case Environment.DEMO:
        config = DemoConfig()  # type: ignore[call-arg]


def init_sentry() -> None:
    if config.sentry_dsn:
        sentry_sdk.init(
            dsn=config.sentry_dsn,
            environment=str(environment.value),
            include_local_variables=False,
        )
