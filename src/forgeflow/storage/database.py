"""SQLite connections with explicit transactions, WAL, and schema compatibility checks."""

import sqlite3
from pathlib import Path
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from forgeflow.domain import ErrorCode, ForgeFlowError


def open_database(path: Path, *, writable: bool) -> Engine:
    def connect() -> sqlite3.Connection:
        if writable:
            connection = sqlite3.connect(str(path), autocommit=True, check_same_thread=False)
        else:
            uri = "file:" + quote(path.resolve().as_posix(), safe="/:") + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, autocommit=True, check_same_thread=False)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=1000")
        if writable:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
        connection.autocommit = False
        return connection

    engine = create_engine("sqlite://", creator=connect)
    try:
        with engine.begin() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
            if revision == "0001":
                return engine
            if revision is not None or not writable or inspect(connection).get_table_names():
                raise ForgeFlowError(ErrorCode.SCHEMA)
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        return engine
    except BaseException:
        engine.dispose()
        raise
