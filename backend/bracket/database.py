# Modified by Tofu on 2026-10-25 (https://github.com/tofu-gallery/bracket): the pool's size comes from the settings
# PG_POOL_MIN_SIZE and PG_POOL_MAX_SIZE, and the SQLAlchemy engine keeps no connection open. See TOFU.md.
from typing import Any

import sqlalchemy
from databases import Database
from heliclockter import datetime_utc
from sqlalchemy.pool import NullPool

from bracket.config import config


def datetime_decoder(value: str) -> datetime_utc:
    value = value.split(".")[0].replace("+00", "+00:00")
    return datetime_utc.fromisoformat(value)


async def asyncpg_init(connection: Any) -> None:
    for timestamp_type in ("timestamp", "timestamptz"):
        await connection.set_type_codec(
            timestamp_type,
            encoder=datetime_utc.isoformat,
            decoder=datetime_decoder,
            schema="pg_catalog",
        )


# Tofu (2026-10-25): a session-mode pooler admits only as many clients as its pool holds, so the pool stays small.
database = Database(
    str(config.pg_dsn),
    init=asyncpg_init,
    min_size=config.pg_pool_min_size,
    max_size=config.pg_pool_max_size,
)

# Tofu (2026-10-25): the engine only creates the tables on an empty database (bracket/utils/db_init.py). Without a pool
# its connection closes right after, instead of staying open beside the asyncpg pool's until the process ends.
engine = sqlalchemy.create_engine(str(config.pg_dsn), poolclass=NullPool)
