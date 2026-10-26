"""
Tofu (2026-10-26, https://github.com/tofu-gallery/bracket): every start's schema work, done by one start at a time.

Tofu's container hosting can start several copies of the app within a second or two when a new deployment gets its
first requests, all against the same database. Each used to find the database empty and create the tables at the same
moment as the others; all but one then stopped with a duplicate-object error and answered 500.

`prepare_schema` does the whole schema step in ONE transaction on ONE connection, and the transaction's first statements
take a PostgreSQL advisory lock (`pg_advisory_xact_lock`). The other starts wait for it, for at most SCHEMA_LOCK_WAIT,
and each then looks at the database again inside the lock and finds the work done. A transaction's lock holds through
Tofu's pooler in either of its modes: the pooler keeps a client's transaction on one server connection until it ends,
and the lock ends with the transaction (commit or rollback), so a start that dies leaves nothing locked. PostgreSQL's
DDL is transactional, so it leaves nothing half-made either.

The step: on an empty database the tables, Alembic's record that they are at the latest revision, and an account from
ADMIN_EMAIL and ADMIN_PASSWORD when both are set; Alembic's migrations; the logo table (bracket/utils/tofu_logos.py);
and row-level security on every table the app's role owns in `public`, so that the database's public Data API (its
roles anon and authenticated) can read and change none of them. Bracket's own connection owns the tables, so row-level
security does not limit it. See TOFU.md.
"""

from heliclockter import datetime_utc
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import DBAPIError

from bracket.config import Environment, config, environment
from bracket.database import engine
from bracket.models.db.account import UserAccountType
from bracket.schema import metadata, users
from bracket.utils.alembic import alembic_run_migrations, alembic_stamp_head
from bracket.utils.logging import logger
from bracket.utils.security import hash_password
from bracket.utils.tofu_logos import create_logo_table

# The lock's key, the same in every start of this app: the ASCII bytes of "brktschm".
SCHEMA_LOCK_KEY = 7093850510958225517
# How long a start waits for another start's schema step before it stops with an error.
SCHEMA_LOCK_WAIT = "180s"
# Errors that mean another process made the same object at the same moment (duplicate_table, duplicate_object,
# duplicate_schema, and unique_violation, which two CREATE TYPE or CREATE TABLE of one name meet in the catalog's unique
# indexes), or a deadlock with one (deadlock_detected): the whole step is done once more, from the start.
RETRY_CODES = {"42P07", "42710", "42P06", "23505", "40P01"}

# Row-level security on every ordinary table in `public` that the app's role owns and that does not have it yet. It
# never turns it off and adds no policy. A table that already has it is not touched, so later starts take no lock.
ENABLE_ROW_LEVEL_SECURITY = """
DO $tofu$
DECLARE
  t regclass;
BEGIN
  FOR t IN
    SELECT c.oid::regclass
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relrowsecurity
      AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
    ORDER BY 1
  LOOP
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t);
  END LOOP;
END
$tofu$
"""


def creates_tables(connection: Connection) -> bool:
    """Upstream's test in init_db_when_empty (bracket/utils/db_init.py), made inside the lock."""
    table_count = connection.execute(
        text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
    ).scalar_one()
    if table_count <= 1 and environment is not Environment.CI:
        return True
    # Upstream's development start also makes the tables and the admin account when that account is missing.
    return bool(
        environment is Environment.DEVELOPMENT
        and config.admin_email
        and config.admin_password
        and connection.execute(select(users.c.id).where(users.c.email == config.admin_email)).first()
        is None
    )


def prepare_schema_once() -> None:
    with engine.begin() as connection:
        connection.execute(text(f"SET LOCAL lock_timeout = '{SCHEMA_LOCK_WAIT}'"))
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK_KEY})

        if creates_tables(connection):
            logger.warning("Empty db detected, creating tables...")
            metadata.create_all(connection)
            alembic_stamp_head(connection)
            if config.admin_email and config.admin_password:
                logger.warning("Empty db detected, creating admin user...")
                connection.execute(
                    users.insert().values(
                        name="Admin",
                        email=config.admin_email,
                        password_hash=hash_password(config.admin_password),
                        created=datetime_utc.now(),
                        account_type=UserAccountType.REGULAR.value,
                    )
                )

        if config.auto_run_migrations and environment is not Environment.CI:
            alembic_run_migrations(connection)

        create_logo_table(connection)
        connection.execute(text(ENABLE_ROW_LEVEL_SECURITY))


def prepare_schema() -> None:
    try:
        prepare_schema_once()
    except DBAPIError as error:
        code = getattr(error.orig, "pgcode", None)
        if code not in RETRY_CODES:
            raise
        logger.warning("The schema step met another process's work (%s); doing it once more", code)
        prepare_schema_once()
