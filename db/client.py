"""Database connection. DATABASE_URL picks the backend:

- unset                      -> SQLite file data/app.db (zero setup, good for a laptop demo)
- postgresql://... (Supabase)-> Postgres via psycopg 3
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from db.models import metadata

ROOT = Path(__file__).resolve().parents[1]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        (ROOT / "data").mkdir(exist_ok=True)
        return f"sqlite:///{ROOT / 'data' / 'app.db'}"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@lru_cache(maxsize=4)
def _engine_for(url: str) -> Engine:
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless asked
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return eng
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def get_engine() -> Engine:
    return _engine_for(database_url())


def init_db() -> None:
    """Create missing tables. Safe to call on every start."""
    metadata.create_all(get_engine())
