# Modified by Tofu on 2026-10-26 (https://github.com/tofu-gallery/bracket): a command can run on a connection the
# caller gives, inside the caller's transaction. See TOFU.md.
from alembic.config import Config
from sqlalchemy import Connection

from alembic import command
from bracket.utils.logging import logger


def get_alembic_config(connection: Connection | None = None) -> Config:
    alembic_config = Config("alembic.ini")
    # Tofu (2026-10-26): alembic/env.py runs the command on this connection, inside its transaction
    # (bracket/utils/tofu_schema.py).
    if connection is not None:
        alembic_config.attributes["connection"] = connection
    return alembic_config


def alembic_run_migrations(connection: Connection | None = None) -> None:
    logger.info("Running migrations")
    command.upgrade(get_alembic_config(connection), "head")


def alembic_stamp_head(connection: Connection | None = None) -> None:
    logger.info("Overwriting current version to be the latest revision (head)")
    command.stamp(get_alembic_config(connection), "head")
