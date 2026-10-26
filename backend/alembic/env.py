# Modified by Tofu on 2026-10-26 (https://github.com/tofu-gallery/bracket): a command can run on a connection the
# caller gives, inside the caller's transaction. See TOFU.md.
import logging
import os
import sys

# ruff: noqa: E402 We first need to insert the path
from sqlalchemy import engine_from_config, pool

from alembic import context

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

from bracket.config import config
from bracket.schema import Base

ALEMBIC_CONFIG = context.config
logger = logging.getLogger("alembic")


def run_migrations_offline() -> None:
    url = ALEMBIC_CONFIG.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=Base.metadata, compare_type=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tofu (2026-10-26): a command given a connection (bracket/utils/alembic.py) runs on it, inside the caller's
    # transaction, which commits or rolls back the migrations with the rest of its work (bracket/utils/tofu_schema.py).
    shared_connection = ALEMBIC_CONFIG.attributes.get("connection")
    if shared_connection is not None:
        context.configure(
            connection=shared_connection, target_metadata=Base.metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    config_ini_section = ALEMBIC_CONFIG.get_section(ALEMBIC_CONFIG.config_ini_section)
    assert config_ini_section is not None, "No section 'alembic' found in config.ini"
    config_ini_section["sqlalchemy.url"] = str(config.pg_dsn)

    engine = engine_from_config(config_ini_section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    connection = engine.connect()
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)

    try:
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
