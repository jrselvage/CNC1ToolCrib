from pathlib import Path
import os
import socket
import urllib.parse as urlparse
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

def _normalize_db_url(db_url: str) -> str:
    # SQLAlchemy prefers postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return db_url

def _engine_from_url(db_url: str, connect_args=None) -> Engine:
    # create the engine; do not expose the URL elsewhere
    return create_engine(db_url, future=True)

def _try_connect_and_maybe_ipv4_fallback(db_url: str) -> Engine:
    """
    Try to create an engine and connect. If a socket-level 'Cannot assign requested address'
    occurs (often due to IPv6 routing absence), resolve the host to an IPv4 address and retry.
    """
    parsed = urlparse.urlparse(db_url)
    # shortcut: if it's sqlite, just return engine
    if parsed.scheme.startswith("sqlite"):
        return _engine_from_url(db_url)

    engine = _engine_from_url(db_url)
    try:
        # test a quick connection
        with engine.connect():
            pass
        return engine
    except OperationalError as e:
        msg = str(e).lower()
        # detect the IPv6 socket error pattern
        if "cannot assign requested address" in msg:
            host = parsed.hostname
            port = parsed.port or 5432
            try:
                infos = socket.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
                if not infos:
                    raise RuntimeError("No IPv4 address found for host")
                ipv4 = infos[0][4][0]
            except Exception:
                # re-raise the original error if we cannot resolve IPv4
                raise

            # rebuild URL with IPv4 address (preserve username, password, dbname, query)
            username = parsed.username or ""
            password = parsed.password or ""
            userinfo = ""
            if username:
                userinfo = username
                if password:
                    userinfo += ":" + password
                userinfo += "@"
            netloc = f"{userinfo}{ipv4}:{port}"
            new_parsed = parsed._replace(netloc=netloc)
            new_url = urlparse.urlunparse(new_parsed)

            # create a new engine with the IPv4 address and test again
            engine_ipv4 = _engine_from_url(new_url)
            try:
                with engine_ipv4.connect():
                    pass
                return engine_ipv4
            except Exception:
                # If the IPv4 attempt fails, re-raise to surface the error
                raise
        # if not the specific socket error, re-raise
        raise

def get_database_engine() -> Engine:
    # 1) Use Streamlit secrets if present (preferred in cloud)
    db_url = None
    try:
        if st.secrets and st.secrets.get("DATABASE_URL"):
            db_url = st.secrets["DATABASE_URL"]
    except Exception:
        # st.secrets may raise when running outside Streamlit
        pass

    # 2) Fall back to environment variable
    if not db_url:
        db_url = os.environ.get("DATABASE_URL")

    # 3) If we have a URL use it (Postgres or other)
    if db_url:
        db_url = _normalize_db_url(db_url)
        # Try to create engine and attempt IPv4 fallback on socket-level failure
        return _try_connect_and_maybe_ipv4_fallback(db_url)

    # 4) Otherwise use local SQLite file next to this file: ./data/mydb.db
    local_db = Path(__file__).resolve().parent / "data" / "mydb.db"
    local_db.parent.mkdir(parents=True, exist_ok=True)
    sqlite_url = f"sqlite:///{local_db}"
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
        conn.execute(text(sql), params or {})