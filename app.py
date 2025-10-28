import streamlit as st
import pandas as pd
import os
from sqlalchemy import text
from db import get_database_engine

st.set_page_config(page_title="Tool Crib", layout="centered")

engine = get_database_engine()

def using_remote_db() -> bool:
    try:
        return bool(st.secrets.get("DATABASE_URL"))
    except Exception:
        return bool(os.environ.get("DATABASE_URL"))

def ensure_tools_table():
    """Create the tools table if it does not exist. Uses dialect-aware SQL."""
    dialect = engine.dialect.name if hasattr(engine, "dialect") else ""
    if dialect == "postgresql":
        create_sql = """
        CREATE TABLE IF NOT EXISTS tools (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT
        );
        """
    else:
        # SQLite and other dialects
        create_sql = """
        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT
        );
        """
    try:
        with engine.begin() as conn:
            conn.execute(text(create_sql))
    except Exception as e:
        # table creation is best-effort; log to Streamlit for debugging
        st.warning(f"Could not ensure tools table exists: {e}")


def list_tools() -> pd.DataFrame:
    try:
        with engine.connect() as conn:
            df = pd.read_sql_query("SELECT * FROM tools ORDER BY id", conn)
    except Exception as e:
        st.error(f"Error reading tools: {e}")
        return pd.DataFrame()
    return df


def add_tool(name: str, description: str):
    if not name:
        raise ValueError("Name is required")
    sql = text("INSERT INTO tools (name, description) VALUES (:name, :desc)")
    with engine.begin() as conn:
        conn.execute(sql, {"name": name, "desc": description})


# Ensure table exists on startup (best-effort)
ensure_tools_table()

st.title("Tool Crib")

# Indicate which DB is being used (safe disclosure)
if using_remote_db():
    st.info("Using remote Postgres (DATABASE_URL). Writes will persist.")
else:
    st.warning("Using local SQLite (data/mydb.db). Writes on Streamlit Cloud are ephemeral.")

# Show current tools
st.header("Existing tools")
df = list_tools()
if df.empty:
    st.write("No tools found.")
else:
    st.dataframe(df)

# Add new tool form
st.header("Add a new tool")
with st.form("add_tool_form", clear_on_submit=True):
    name = st.text_input("Name")
    desc = st.text_area("Description")
    submitted = st.form_submit_button("Add tool")
    if submitted:
        try:
            add_tool(name.strip(), desc.strip())
            st.success("Tool added.")
            # refresh displayed data
            st.experimental_rerun()
        except Exception as e:
            st.error(f"Failed to add tool: {e}")

# Debugging / logs area (optional)
with st.expander("Connection info (safe)"):
    try:
        info = engine.url if hasattr(engine, "url") else None
        if info:
            scheme = str(info.scheme)
            host = str(info.host) if info.host else "local"
            dbname = str(info.database) if info.database else ""
            st.write(f"DB scheme: {scheme}, host: {host}, db: {dbname}")
        else:
            st.write("Engine created (no URL available)")
    except Exception:
        st.write("Unable to show connection info.")
