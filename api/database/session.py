"""Database engine and session management for EvaliSense.

Configures SQLite with foreign-key constraints enabled and provides session dependency.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from config import config

# Ensure the database directory exists
if config.db_path.parent:
    config.db_path.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{config.db_path.resolve()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=config.debug,
)

# Enable foreign key support for SQLite
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and closes it on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_schema() -> None:
    """Ensure any newly added columns exist in SQLite database tables."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "exam_questions" in table_names:
        cols = [c["name"] for c in inspector.get_columns("exam_questions")]
        if "updated_at" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE exam_questions ADD COLUMN updated_at DATETIME"))
                conn.commit()


def init_db() -> None:
    """Create all tables and run initial seed."""
    from api.database import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    from api.database.seed import seed_initial_data
    seed_initial_data()

