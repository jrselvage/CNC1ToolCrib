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

def _engine_from_url(db_url, connect_args=None) -> Engine:
    # create the engine; do not expose the URL elsewhere
    return create_engine(db_url, future=True)

def _try_connect_and_maybe_ipv4_fallback(db_url: str) -> Engine:
    """
    Try to create an engine and connect. If a socket-level 'Cannot assign requested address'
    occurs (often due to IPv6 routing absence), resolve the host to an IPv4 address and retry.
    """
    parsed = urlparse.urlparse(db_url)
    # quick shortcut: if not a network DB, just return engine
    if parsed.scheme.startswith("sqlite"):
        return _engine_from_url(db_url)

    engine = _engine_from_url(db_url)
    try:
        # test a quick connection
        with engine.connect() as conn:
            pass
        return engine
    except OperationalError as e:
        msg = str(e).lower()
        # detect the IPv6 socket error pattern
        if "cannot assign requested address" in msg:
            # attempt IPv4 resolution for the hostname
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
            netloc_user = ""
            if parsed.username:
                netloc_user = parsed.username
                if parsed.password:
                    netloc_user += ":