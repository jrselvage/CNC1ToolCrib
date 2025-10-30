import streamlit as st
import sqlite3
import pandas as pd
import fitz
from datetime import datetime, timedelta
import io
import os
import requests  # For GitHub download

# ------------------- CONFIG -------------------
DB_PATH = "inventory.db"
DB_URL = "https://raw.githubusercontent.com/jrselvage/CNC1ToolCrib/main/inventory.db"

# ------------------- AUTO-DOWNLOAD FROM GITHUB ON START -------------------
def ensure_db_from_github():
    if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 1000:
        st.toast("Using existing local database.")
        return  # Skip if local DB is valid
    try:
        with st.spinner("Downloading database from GitHub..."):
            r = requests.get(DB_URL, timeout=10)
            if r.status_code == 200 and len(r.content) > 100:
                with open(DB_PATH, "wb") as f:
                    f.write(r.content)
                st.toast("Database restored from GitHub!")
            else:
                st.toast("No valid backup on GitHub. Starting fresh.")
    except Exception as e:
        st.toast(f"Download failed: {e}. Starting fresh.")

# Run on startup
ensure_db_from_github()

# ------------------- DATABASE -------------------
@st.cache_resource
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA cache_size=10000;")
    return conn

conn = get_connection()
cursor = conn.cursor()

# Create tables if missing
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='inventory'")
if not cursor.fetchone():
    cursor.execute("""
    CREATE TABLE inventory (
        location TEXT,
        item TEXT,
        notes TEXT,
        quantity INTEGER
    )
    """)
    cursor.execute("""
    CREATE TABLE transactions (
        item TEXT,
        action TEXT,
        user TEXT,
        timestamp TEXT,
        qty INTEGER
    )
    """)
    for idx in [
        "CREATE INDEX IF NOT EXISTS idx_location ON inventory(location)",
        "CREATE INDEX IF NOT EXISTS idx_item ON inventory(item)",
        "CREATE INDEX IF NOT EXISTS idx_tx_item ON transactions(item)",
        "CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)"
    ]:
        cursor.execute(idx)
    conn.commit()

# ------------------- PAGE -------------------
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory System")

# ------------------- DEBUG + DOWNLOAD -------------------
col1, col2 = st.columns(2)
with col1:
    if st.button("CHECK DATABASE"):
        try:
            size = os.path.getsize(DB_PATH)
            items = pd.read_sql_query("SELECT COUNT(*) FROM inventory", conn).iloc[0,0]
            txs = pd.read_sql_query("SELECT COUNT(*) FROM transactions", conn).iloc[0,0]
            st.success(f"DB: {size:,} bytes | {items} items | {txs} txs")
        except Exception:
            st.error("DB not ready")

with col2:
    try:
        with open(DB_PATH, "rb") as f:
            db_bytes = f.read()
        st.download_button(
            label="DOWNLOAD DB BACKUP",
            data=db_bytes,
            file_name=f"inventory_backup_{datetime.now():%Y%m%d_%H%M%S}.db",
            mime="application/octet-stream"
        )
        st.caption(f"Size: {len(db_bytes):,} bytes")
    except Exception:
        st.error("DB not found")

# ------------------- ADD ITEM -------------------
st.sidebar.header("Add New Item")
with st.sidebar.form("add_form", clear_on_submit=True):
    new_item = st.text_input("Item Name", key="add_name")
    new_loc = st.text_input("Location (e.g., 105A)", key="add_loc").strip().upper()
    new_qty = st.number_input("Quantity", min_value=0, step=1, value=0, key="add_qty")
    new_notes = st.text_area("Notes", key="add_notes")
    submitted = st.form_submit_button("Add Item")

    if submitted and new_item and new_loc:
        cursor.execute(
            "INSERT INTO inventory (location, item, notes, quantity) VALUES (?, ?, ?, ?)",
            (new_loc, new_item.strip(), new_notes.strip(), int(new_qty))
        )
        conn.commit()
        st.cache_data.clear()
        st.success(f"Added: {new_item}")
        st.rerun()

# ------------------- TABS -------------------
tab_inventory, tab_transactions, tab_reports = st.tabs(["Inventory", "Transactions", "Reports"])

# ------------------- INVENTORY TAB -------------------
with tab_inventory:
    st.subheader("Search Inventory")
    col1, col2, col3, col4 = st.columns(4)
    with col1: search_name = st.text_input("Item Name", key="inv_name")
    with col2: cabinet = st.selectbox("Cabinet", ["All"] + [str(i) for i in range(1, 200)], key="inv_cab")
    with col3: drawer = st.selectbox("Drawer", ["All"] + ["A","B","C","D","E","F"], key="inv_drawer")
    with col4: qty_filter = st.number_input("Exact Qty", min_value=0, value=0, key="inv_qty")

    has_filter = search_name or (cabinet != "All") or (drawer != "All") or (qty_filter > 0)
    if not has_filter:
        st.info("Use filters to search.")
    else:
        @st.cache_data(ttl=60)
        def load_inventory(name="", cab="All", drw="All", qty=0):
            q = "SELECT rowid AS id, location, item, notes, quantity FROM inventory WHERE 1=1"
            p = []
            if name: q += " AND item LIKE ?"; p.append(f"%{name}%")
            if cab != "All" and drw != "All": q += " AND location = ?"; p.append(f"{cab}{drw}")
            elif cab != "All": q += " AND location LIKE ?"; p.append(f"{cab}%")
            elif drw != "All": q += " AND location LIKE ?"; p.append(f"%{drw}")
            if qty > 0: q += " AND quantity = ?"; p.append(qty)
            q += " ORDER BY location, item"
            return pd.read_sql_query(q, conn, params=p)

        df = load_inventory(search_name, cabinet, drawer, qty_filter)
        if df.empty:
            st.warning("No items found.")
        else:
            st.write(f"**{len(df)} item(s) found**")
            for _, row in df.iterrows():
                with st.expander(f"{row['item']} @ {row['location']} — Qty: {row['quantity']}"):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        notes = st.text_area("Notes", value=row['notes'] or "", key=f"n_{row['id']}", height=70)
                        if st.button("Save Notes", key=f"s_{row['id']}"):
                            cursor.execute("UPDATE inventory SET notes = ? WHERE rowid = ?", (notes.strip(), row['id']))
                            conn.commit()
                            st.cache_data.clear()
                            st.success("Saved")
                            st.rerun()
                    action = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"a_{row['id']}")
                    user = st.text_input("Your Name", key=f"u_{row['id']}")
                    qty = st.number_input("Qty", min_value=1, step=1, value=1, key=f"q_{row['id']}")

                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Submit", key=f"sub_{row['id']}") and action != "None" and user.strip():
                            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            cursor.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?)",
                                           (row['item'], action, user.strip(), ts, qty))
                            new_qty = row['quantity'] - qty if action == "Check Out" else row['quantity'] + qty
                            cursor.execute("UPDATE inventory SET quantity = ? WHERE rowid = ?", (max(0, new_qty), row['id']))
                            conn.commit()
                            st.cache_data.clear()
                            st.success(f"{action}: {qty}")
                            st.rerun()
                    with c2:
                        if st.button("Delete", key=f"del_{row['id']}") and user.strip():
                            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            cursor.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?)",
                                           (row['item'], "Deleted", user.strip(), ts, row['quantity']))
                            cursor.execute("DELETE FROM inventory WHERE rowid = ?", (row['id'],))
                            conn.commit()
                            st.cache_data.clear()
                            st.warning("Deleted")
                            st.rerun()

# ------------------- TRANSACTIONS TAB -------------------
with tab_transactions:
    st.subheader("Transaction History")
    c1, c2, c3, c4 = st.columns(4)
    with c1: t_item = st.text_input("Item", key="t_item")
    with c2: t_user = st.text_input("User", key="t_user")
    with c3: t_action = st.selectbox("Action", ["All", "Check Out", "Check In", "Deleted"], key="t_action")
    with c4: t_qty = st.number_input("Qty", min_value=0, value=0, key="t_qty")

    start_date = st.date_input("From", value=datetime(2020, 1, 1), key="t_start")
    end_date = st.date_input("To", value=datetime.today().date(), key="t_end")

    start_str = start_date.strftime("%Y-%m-%d 00:00:00")
    end_str = (end_date + timedelta(days=1) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

    @st.cache_data(ttl=60)
    def load_transactions(item="", user="", action="All", qty=0, s="", e=""):
        q = "SELECT * FROM transactions WHERE timestamp BETWEEN ? AND ?"
        p = [s, e]
        if item: q += " AND item LIKE ?"; p.append(f"%{item}%")
        if user: q += " AND user LIKE ?"; p.append(f"%{user}%")
        if action != "All": q += " AND action = ?"; p.append(action)
        if qty > 0: q += " AND qty = ?"; p.append(qty)
        q += " ORDER BY timestamp DESC LIMIT 1000"
        return pd.read_sql_query(q, conn, params=p)

    df_tx = load_transactions(t_item, t_user, t_action, t_qty, start_str, end_str)
    if df_tx.empty:
        st.info("No transactions found.")
    else:
        st.dataframe(df_tx[['timestamp', 'action', 'qty', 'item', 'user']], use_container_width=True, hide_index=True)

# ------------------- REPORTS TAB -------------------
with tab_reports:
    st.subheader("Generate Report")
    @st.cache_data(ttl=300)
    def get_locations():
        df = pd.read_sql_query("SELECT DISTINCT location FROM inventory WHERE location IS NOT NULL", conn)
        return sorted(df['location'].dropna().unique().tolist())

    locations = get_locations()
    prefixes = sorted({loc[:2] for loc in locations if len(loc) >= 2})

    with st.form("report_form"):
        prefix = st.selectbox("Location Prefix", ["All"] + prefixes, key="r_prefix")
        custom_loc = st.text_input("Custom Location Filter", key="r_custom")
        zero_only = st.checkbox("Show only zero-quantity items", key="r_zero")
        r_start = st.date_input("Start Date", value=datetime(2020, 1, 1), key="r_start")
        r_end = st.date_input("End Date", value=datetime.today().date(), key="r_end")
        generate = st.form_submit_button("Generate Report")

    if generate:
        r_start_str = r_start.strftime("%Y-%m-%d 00:00:00")
        r_end_str = (r_end + timedelta(days=1) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

        @st.cache_data
        def build_report(pfx, cust, zero_only, s, e):
            q = "SELECT location, item, quantity, notes FROM inventory WHERE 1=1"
            p = []
            if pfx != "All": q += " AND location LIKE ?"; p.append(f"{pfx}%")
            if cust: q += " AND location LIKE ?"; p.append(f"%{cust}%")
            if zero_only: q += " AND quantity = 0"
            df = pd.read_sql_query(q, conn, params=p)
            last_tx = pd.read_sql_query("""
                SELECT item, MAX(timestamp) as last_tx
                FROM transactions WHERE timestamp BETWEEN ? AND ?
                GROUP BY item
            """, conn, params=[s, e])
            df = df.merge(last_tx, on='item', how='left')
            df['last_tx'] = pd.to_datetime(df['last_tx'], errors='coerce')
            mask = df['last_tx'].isna() | ((df['last_tx'] >= pd.Timestamp(s)) & (df['last_tx'] <= pd.Timestamp(e)))
            return df[mask]

        with st.spinner("Building report..."):
            df_report = build_report(prefix, custom_loc, zero_only, r_start_str, r_end_str)

        if df_report.empty:
            st.warning("No data matches the filters.")
        else:
            st.write("### Report Preview")
            st.dataframe(df_report, use_container_width=True)

            buffer = io.BytesIO()
            doc = fitz.open()
            page = doc.new_page(width=800, height=1100)
            text = "CNC1 Tool Crib Report\n\n" + df_report[['location', 'item', 'quantity', 'last_tx']].to_string(index=False)
            page.insert_text((50, 50), text, fontsize=9)
            doc.save(buffer)
            doc.close()
            buffer.seek(0)

            st.download_button(
                "Download PDF Report",
                buffer.getvalue(),
                f"report_{datetime.now():%Y%m%d}.pdf",
                "application/pdf"
            )
