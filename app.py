import streamlit as st
import sqlite3
import pandas as pd
import fitz
from datetime import datetime, timedelta
import io
import re
import shutil
import os

# ------------------- AUTO BACKUP FUNCTION -------------------
def auto_backup():
    """Save inventory.db → inventory_backup.db after every change"""
    try:
        shutil.copy("inventory.db", "inventory_backup.db")
        # Optional: Show tiny toast
        st.toast("Auto-backup saved", icon="Success")
    except Exception as e:
        st.toast(f"Backup failed: {e}", icon="Error")

# ------------------- DATABASE: LOAD OR RESTORE -------------------
DB_PATH = "inventory.db"

def init_db():
    if os.path.exists(DB_PATH):
        return sqlite3.connect(DB_PATH, check_same_thread=False)
    
    st.error("inventory.db not found!")
    st.info("Upload your database to restore.")
    uploaded = st.file_uploader("Upload inventory.db", type="db", key="restore_db")
    if uploaded:
        with open(DB_PATH, "wb") as f:
            f.write(uploaded.getbuffer())
        auto_backup()
        st.success("Database restored! Restarting...")
        st.rerun()
    st.stop()

@st.cache_resource
def get_connection():
    conn = init_db()
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA cache_size=10000;")
    return conn

conn = get_connection()
cursor = conn.cursor()

# Create tables if missing
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='inventory'")
if not cursor.fetchone():
    cursor.execute("CREATE TABLE inventory (location TEXT, item TEXT, notes TEXT, quantity INTEGER)")
    cursor.execute("CREATE TABLE transactions (item TEXT, action TEXT, user TEXT, timestamp TEXT, qty INTEGER)")
    for idx in [
        "CREATE INDEX IF NOT EXISTS idx_location ON inventory(location)",
        "CREATE INDEX IF NOT EXISTS idx_item ON inventory(item)",
        "CREATE INDEX IF NOT EXISTS idx_tx_item ON transactions(item)",
        "CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)"
    ]:
        cursor.execute(idx)
    conn.commit()
    auto_backup()

# ------------------- Page Config -------------------
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory Management System")

# ------------------- DEBUG + AUTO DOWNLOAD -------------------
col1, col2 = st.columns(2)
with col1:
    if st.button("CHECK DB STATUS"):
        size = os.path.getsize(DB_PATH)
        items = pd.read_sql_query("SELECT COUNT(*) FROM inventory", conn).iloc[0,0]
        txs = pd.read_sql_query("SELECT COUNT(*) FROM transactions", conn).iloc[0,0]
        st.success(f"DB LOADED | {size:,} bytes | {items} items | {txs} txs")
with col2:
    with open(DB_PATH, "rb") as f:
        st.download_button(
            "DOWNLOAD CURRENT DB",
            f,
            "inventory.db",
            "application/octet-stream",
            help="Download your full database"
        )

# ------------------- Sidebar: Add Item -------------------
st.sidebar.header("Add New Inventory Item")
with st.sidebar.form("add_item_form", clear_on_submit=True):
    new_item = st.text_input("Item Name", key="add_name")
    new_location = st.text_input("Location (e.g., 105A)", key="add_loc").strip().upper()
    new_quantity = st.number_input("Quantity", min_value=0, step=1, value=0, key="add_qty")
    new_notes = st.text_area("Notes", key="add_notes")
    submitted = st.form_submit_button("Add Item")

    if submitted and new_item and new_location:
        cursor.execute(
            "INSERT INTO inventory (location, item, notes, quantity) VALUES (?, ?, ?, ?)",
            (new_location, new_item.strip(), new_notes.strip(), int(new_quantity))
        )
        conn.commit()
        auto_backup()  # BACKUP AFTER ADD
        st.cache_data.clear()
        st.success(f"Added: {new_item}")
        st.rerun()

# ------------------- Tabs -------------------
tab_inventory, tab_transactions, tab_reports = st.tabs(["Inventory", "Transactions", "Reports"])

# ------------------- Cabinets & Drawers -------------------
@st.cache_data(ttl=300)
def get_cabinets_and_drawers():
    df = pd.read_sql_query("SELECT DISTINCT location FROM inventory WHERE location IS NOT NULL", conn)
    locations = [loc.strip().upper() for loc in df['location'].dropna().unique() if loc.strip()]
    cabinet_nums = set()
    drawers = set()
    pattern = re.compile(r'^(\d+)(.*)$', re.IGNORECASE)
    for loc in locations:
        match = pattern.match(loc)
        if match:
            try: cabinet_nums.add(int(match.group(1)))
            except: pass
            drawer = match.group(2).strip()
            if drawer: drawers.add(drawer)
        else:
            drawers.add(loc)
    return [str(c) for c in sorted(cabinet_nums)], sorted(drawers)

cabinets, drawers = get_cabinets_and_drawers()

# ------------------- INVENTORY TAB -------------------
with tab_inventory:
    st.subheader("Inventory Search")
    col1, col2, col3, col4 = st.columns(4)
    with col1: search_name = st.text_input("Item Name (optional)", key="inv_name")
    with col2: cabinet = st.selectbox("Cabinet", ["All"] + cabinets, key="inv_cabinet")
    with col3: drawer = st.selectbox("Drawer", ["All"] + drawers, key="inv_drawer")
    with col4: qty_filter = st.number_input("Exact Qty", min_value=0, step=1, key="inv_qty", value=0)

    has_filter = search_name or (cabinet != "All") or (drawer != "All") or (qty_filter > 0)
    if not has_filter:
        st.info("Select a filter to search.")
    else:
        @st.cache_data(ttl=60)
        def load_inventory(_name="", _cab="All", _drw="All", _qty=0):
            q = "SELECT rowid AS id, location, item, notes, quantity FROM inventory WHERE 1=1"
            p = []
            if _name: q += " AND item LIKE ?"; p.append(f"%{_name}%")
            if _cab != "All" and _drw != "All": q += " AND location LIKE ?"; p.append(f"{_cab}{_drw}")
            elif _cab != "All": q += " AND location LIKE ?"; p.append(f"{_cab}%")
            elif _drw != "All": q += " AND location LIKE ?"; p.append(f"%{_drw}")
            if _qty > 0: q += " AND quantity = ?"; p.append(_qty)
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
                            auto_backup()  # BACKUP AFTER NOTES
                            st.cache_data.clear()
                            st.success("Saved")
                            st.rerun()
                    action = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"a_{row['id']}")
                    user = st.text_input("Your Name", key=f"u_{row['id']}")
                    qty = st.number_input("Qty", min_value=1, step=1, key=f"q_{row['id']}", value=1)

                    c1, c2 = st.columns(2)
                    with c1:
                        submit = st.button("Submit", key=f"sub_{row['id']}")
                    with c2:
                        delete = st.button("Delete", key=f"del_{row['id']}")

                    if submit and action != "None" and user.strip():
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cursor.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?)",
                                       (row['item'], action, user.strip(), ts, qty))
                        new_qty = row['quantity'] - qty if action == "Check Out" else row['quantity'] + qty
                        cursor.execute("UPDATE inventory SET quantity = ? WHERE rowid = ?", (max(0, new_qty), row['id']))
                        conn.commit()
                        auto_backup()  # BACKUP AFTER CHECK OUT/IN
                        st.cache_data.clear()
                        st.success(f"{action}: {qty}")
                        st.rerun()

                    if delete and user.strip():
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cursor.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?)",
                                       (row['item'], "Deleted", user.strip(), ts, row['quantity']))
                        cursor.execute("DELETE FROM inventory WHERE rowid = ?", (row['id'],))
                        conn.commit()
                        auto_backup()  # BACKUP AFTER DELETE
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
    with c4: t_qty = st.number_input("Qty", min_value=0, step=1, key="t_qty", value=0)

    today = datetime.today().date()
    start_date = st.date_input("From", value=datetime(2020, 1, 1), key="t_start")
    end_date = st.date_input("To", value=today, key="t_end")

    start_str = start_date.strftime("%Y-%m-%d 00:00:00")
    end_str = (end_date + timedelta(days=1) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

    @st.cache_data(ttl=60)
    def load_transactions(_item="", _user="", _action="All", _qty=0, _start="", _end=""):
        q = "SELECT * FROM transactions WHERE timestamp BETWEEN ? AND ?"
        p = [_start, _end]
        if _item: q += " AND item LIKE ?"; p.append(f"%{_item}%")
        if _user: q += " AND user LIKE ?"; p.append(f"%{_user}%")
        if _action != "All": q += " AND action = ?"; p.append(_action)
        if _qty > 0: q += " AND qty = ?"; p.append(_qty)
        q += " ORDER BY timestamp DESC LIMIT 1000"
        return pd.read_sql_query(q, conn, params=p)

    df_tx = load_transactions(t_item, t_user, t_action, t_qty, start_str, end_str)
    if df_tx.empty:
        st.info("No transactions found.")
    else:
        st.dataframe(df_tx[['timestamp', 'action', 'qty', 'item', 'user']], use_container_width=True, hide_index=True)

# ------------------- REPORTS TAB (unchanged) -------------------
# [Same as before — omitted for brevity]
