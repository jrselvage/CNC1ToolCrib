"""
db.py - helper to get a SQLAlchemy engine that:
- uses st.secrets['DATABASE_URL'] (or env var) in production (Postgres)
- falls back to a local SQLite file in data/mydb.db for local dev
- normalizes "postgres://" -> "postgresql://" for SQLAlchemy compatibility
"""

from pathlib import Path
import os
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

def _normalize_db_url(db_url: str) -> str:
    # SQLAlchemy prefers postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return db_url

def get_database_engine() -> Engine:
    # 1) Use Streamlit secrets if present (preferred in cloud)
    db_url = None
    try:
        if st.secrets and st.secrets.get("DATABASE_URL"):
            db_url = st.secrets["DATABASE_URL"]
    except Exception:
        # st.secrets access can raise when running outside Streamlit
        pass

    # 2) Fall back to environment variable
    if not db_url:
        db_url = os.environ.get("DATABASE_URL")

    # 3) If we have a URL use it (Postgres or other)
    if db_url:
        db_url = _normalize_db_url(db_url)
        engine = create_engine(db_url, future=True)
        return engine

    # 4) Otherwise use local SQLite file next to this file: ./data/mydb.db
    local_db = Path(__file__).resolve().parent / "data" / "mydb.db"
    local_db.parent.mkdir(parents=True, exist_ok=True)
    sqlite_url = f"sqlite:///{local_db}"
    # connect_args={"check_same_thread": False} is not needed for short scripts,
    # but you can add it if you see threading issues
    engine = create_engine(sqlite_url, future=True)
    return engine

# Convenience helpers
def read_query(sql: str, params=None):
    engine = get_database_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(row._mapping) for row in result]

def write_exec(sql: str, params=None):
    engine = get_database_engine()
    with engine.begin() as conn:
        conn.execute(text(sql), params or {});