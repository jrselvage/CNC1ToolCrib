from pathlib import Path
import os
import socket
import urllib.parse as urlparse
import logging
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

# Configure logging for debug information (writes to stdout which appears in Streamlit logs)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _normalize_db_url(db_url: str) -> str:
    # SQLAlchemy prefers postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return db_url

def _engine_from_url(db_url: str, connect_args=None) -> Engine:
    # create the engine; do not expose the URL elsewhere
    return create_engine(db_url, future=True)

def _try_connect_and_maybe_address_fallback(db_url: str) -> Engine:
    """
    Try to create an engine and connect. If a socket-level failure occurs when
    attempting the original hostname (commonly due to IPv6 routing or DNS),
    resolve all addresses (IPv4 and IPv6) and attempt connections using each
    numeric address until one succeeds. This preserves username/password/dbname/query
    while replacing the host with a numeric address (IPv6 addresses are bracketed).
    """
    parsed = urlparse.urlparse(db_url)
    # shortcut: if it's sqlite, just return engine
    if parsed.scheme.startswith("sqlite"):
        logger.info("Using sqlite URL; skipping network connect tests")
        return _engine_from_url(db_url)

    logger.info("Attempting initial DB connection to host=%s port=%s user=%s",
                parsed.hostname, parsed.port or 5432, parsed.username or "<none>")

    # Try the original URL first
    engine = _engine_from_url(db_url)
    try:
        with engine.connect():
            logger.info("Connected to DB using original hostname %s", parsed.hostname)
            return engine
    except OperationalError as orig_err:
        orig_msg = str(orig_err).lower()
        logger.warning("Initial DB connection failed: %s", orig_msg)
        # If it's a network/socket-related error, try resolved addresses
        network_error_indicators = [
            "cannot assign requested address",
            "network is unreachable",
            "nodename nor servname provided",
            "temporary failure in name resolution",
            "name or service not known",
            "could not translate host name",
        ]
        if not any(ind in orig_msg for ind in network_error_indicators):
            logger.error("Non-network DB error; re-raising")
            raise

        host = parsed.hostname
        port = parsed.port or 5432
        try:
            # Ask the OS to resolve IPv4 and IPv6 addresses
            addrinfos = socket.getaddrinfo(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
            logger.info("Resolved %d address(es) for host %s", len(addrinfos), host)
        except Exception as e:
            logger.exception("Name resolution failed for host %s: %s", host, e)
            # If name resolution fails entirely, re-raise the original error
            raise orig_err

        # Try each resolved address
        attempted = []
        for family, socktype, proto, canonname, sockaddr in addrinfos:
            ip = sockaddr[0]
            attempted.append(ip)
            logger.info("Trying numeric address %s (family=%s)", ip, "AF_INET6" if family == socket.AF_INET6 else "AF_INET")

            # Build netloc with userinfo (username:password@) and numeric host
            username = parsed.username or ""
            password = parsed.password or ""
            userinfo = ""
            if username:
                userinfo = username
                if password:
                    userinfo += ":<redacted>"
                userinfo += "@"

            if family == socket.AF_INET6:
                # IPv6 must be bracketed
                host_part = f"[{ip}]"
            else:
                host_part = ip

            netloc = f"{userinfo}{host_part}:{port}"
            new_parsed = parsed._replace(netloc=netloc)
            new_url = urlparse.urlunparse(new_parsed)

            try:
                engine_try = _engine_from_url(new_url)
                with engine_try.connect():
                    logger.info("Connected to DB using numeric address %s", ip)
                    # show a Streamlit-level info for visibility in the app logs
                    try:
                        st.info(f"Connected to DB using numeric address {ip}")
                    except Exception:
                        # st may not be available at all call sites; ignore UI logging failures
                        pass
                    return engine_try
            except Exception as e:
                logger.warning("Connection attempt to %s failed: %s", ip, e)
                continue

        # If we reach here no resolved address worked; raise the original error
        logger.error("Tried resolved addresses but none connected: %s", attempted)
        raise orig_err

def get_database_engine() -> Engine:
    # 1) Use Streamlit secrets if present (preferred in cloud)
    db_url = None
    try:
        if st.secrets and st.secrets.get("DATABASE_URL"):
            db_url = st.secrets["DATABASE_URL"]
            logger.info("Found DATABASE_URL in Streamlit secrets")
    except Exception:
        # st.secrets may raise when running outside Streamlit
        logger.debug("st.secrets not available in this environment")

    # 2) Fall back to environment variable
    if not db_url:
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            logger.info("Found DATABASE_URL in environment variable")

    # 3) If we have a URL use it (Postgres or other)
    if db_url:
        # Log a redacted summary (do not log the password)
        try:
            parsed_summary = urlparse.urlparse(db_url)
            logger.info("Database summary: scheme=%s host=%s port=%s user=%s db=%s",
                        parsed_summary.scheme, parsed_summary.hostname, parsed_summary.port or "5432",
                        parsed_summary.username or "<none>", parsed_summary.path.lstrip("/") or "")
        except Exception:
            logger.debug("Failed to parse DATABASE_URL for summary")

        db_url = _normalize_db_url(db_url)
        # Try to create engine and attempt address fallback on socket-level failure
        return _try_connect_and_maybe_address_fallback(db_url)

    # 4) Otherwise use local SQLite file next to this file: ./data/mydb.db
    local_db = Path(__file__).resolve().parent / "data" / "mydb.db"
    local_db.parent.mkdir(parents=True, exist_ok=True)
    sqlite_url = f"sqlite:///{local_db}"
    logger.info("No DATABASE_URL found; using local SQLite at %s", local_db)
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