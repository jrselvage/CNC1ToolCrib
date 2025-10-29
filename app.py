import streamlit as st
import sqlite3
import pandas as pd
import fitz  # PyMuPDF
from datetime import datetime
import io

# ------------------- Database Setup -------------------
DB_PATH = "inventory.db"

@st.cache_resource
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")  # Better concurrency
    return conn

conn = get_connection()
cursor = conn.cursor()

# Ensure tables exist
cursor.execute("""
CREATE TABLE IF NOT EXISTS inventory (
    location TEXT,
    item TEXT,
    notes TEXT,
    quantity INTEGER
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    item TEXT,
    action TEXT,
    user TEXT,
    timestamp TEXT,
    qty INTEGER
)
""")
conn.commit()

# ------------------- Page Config -------------------
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory Management System")

# ------------------- Sidebar: Add Item -------------------
st.sidebar.header("Add New Inventory Item")
with st.sidebar.form("add_item_form"):
    new_item = st.text_input("Item Name")
    new_location = st.text_input("Location (e.g., 105A)").strip().upper()
    new_quantity = st.number_input("Quantity", min_value=0, step=1, value=0)
    new_notes = st.text_area("Notes")
    submitted = st.form_submit_button("Add Item")

    if submitted and new_item and new_location:
        cursor.execute(
            "INSERT INTO inventory (location, item, notes, quantity) VALUES (?, ?, ?, ?)",
            (new_location, new_item.strip(), new_notes.strip(), int(new_quantity))
        )
        conn.commit()
        st.sidebar.success(f"Added: {new_item}")

# ------------------- Tabs -------------------
tab_inventory, tab_transactions, tab_reports = st.tabs(["Inventory", "Transactions", "Reports"])

# ------------------- Helper: Cached Locations -------------------
@st.cache_data(ttl=300)  # Refresh every 5 mins
def get_locations():
    df = pd.read_sql_query("SELECT DISTINCT location FROM inventory", conn)
    return sorted(df['location'].dropna().tolist())

# ------------------- Inventory Tab -------------------
with tab_inventory:
    st.subheader("Search & Manage Inventory")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        search_name = st.text_input("Item Name", key="inv_name")
    with col2:
        cabinet = st.number_input("Cabinet #", min_value=0, step=1, key="inv_cabinet", value=0)
    with col3:
        drawer = st.text_input("Drawer", key="inv_drawer").strip().upper()
    with col4:
        qty_filter = st.number_input("Exact Qty", min_value=0, step=1, key="inv_qty", value=0)

    # Build dynamic query
    query = "SELECT rowid, * FROM inventory WHERE 1=1"
    params = []

    if search_name:
        query += " AND item LIKE ?"
        params.append(f"%{search_name}%")
    if cabinet > 0:
        query += " AND location LIKE ?"
        params.append(f"{cabinet}%")
    if drawer:
        query += " AND location LIKE ?"
        params.append(f"%{drawer}")
    if qty_filter > 0:
        query += " AND quantity = ?"
        params.append(qty_filter)

    df_items = pd.read_sql_query(query, conn, params=params)

    st.write(f"**Found {len(df_items)} items**")

    for _, row in df_items.iterrows():
        item_id, location, name, notes, quantity = row['rowid'], row['location'], row['item'], row['notes'], row['quantity']
        with st.expander(f"{name} @ {location} — Qty: {quantity}"):
            col1, col2 = st.columns([3, 1])
            with col1:
                edited_notes = st.text_area("Notes", value=notes or "", key=f"notes_{item_id}", height=80)
                if st.button("Save Notes", key=f"save_{item_id}"):
                    cursor.execute("UPDATE inventory SET notes = ? WHERE rowid = ?", (edited_notes.strip(), item_id))
                    conn.commit()
                    st.success("Notes saved")
                    st.experimental_rerun()

            # Actions
            action = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"act_{item_id}")
            user = st.text_input("Your Name", key=f"user_{item_id}")
            qty = st.number_input("Qty", min_value=1, step=1, key=f"qty_{item_id}")

            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                submit = st.button("Submit", key=f"submit_{item_id}")
            with col_btn2:
                delete = st.button("Delete", key=f"del_{item_id}")

            if submit and action != "None" and user.strip():
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?, ?, ?, ?, ?)",
                    (name, action, user.strip(), timestamp, qty)
                )
                new_qty = quantity - qty if action == "Check Out" else quantity + qty
                cursor.execute("UPDATE inventory SET quantity = ? WHERE rowid = ?", (max(0, new_qty), item_id))
                conn.commit()
                st.success(f"{action}: {qty} → {name}")
                st.experimental_rerun()

            if delete and user.strip():
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?, ?, ?, ?, ?)",
                    (name, "Deleted", user.strip(), timestamp, quantity)
                )
                cursor.execute("DELETE FROM inventory WHERE rowid = ?", (item_id,))
                conn.commit()
                st.warning(f"Deleted: {name}")
                st.experimental_rerun()

# ------------------- Transactions Tab -------------------
with tab_transactions:
    st.subheader("Transaction History")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        t_item = st.text_input("Item", key="t_item")
    with c2:
        t_user = st.text_input("User", key="t_user")
    with c3:
        t_action = st.selectbox("Action", ["All", "Check Out", "Check In", "Deleted"], key="t_action")
    with c4:
        t_qty = st.number_input("Qty", min_value=0, step=1, key="t_qty", value=0)

    start_date = st.date_input("From", value=datetime(2020, 1, 1), key="t_start")
    end_date = st.date_input("To", value=datetime.today(), key="t_end")

    tx_query = "SELECT * FROM transactions WHERE timestamp BETWEEN ? AND ?"
    tx_params = [start_date.strftime("%Y-%m-%d"), f"{end_date.strftime('%Y-%m-%d')} 23:59:59"]

    if t_item:
        tx_query += " AND item LIKE ?"
        tx_params.append(f"%{t_item}%")
    if t_user:
        tx_query += " AND user LIKE ?"
        tx_params.append(f"%{t_user}%")
    if t_action != "All":
        tx_query += " AND action = ?"
        tx_params.append(t_action)
    if t_qty > 0:
        tx_query += " AND qty = ?"
        tx_params.append(t_qty)

    tx_query += " ORDER BY timestamp DESC"
    df_tx = pd.read_sql_query(tx_query, conn, params=tx_params)

    st.write(f"**{len(df_tx)} transactions**")
    for _, log in df_tx.iterrows():
        st.write(f"**{log['timestamp']}** — {log['action']} **{log['qty']}** of *{log['item']}* by **{log['user']}**")

# ------------------- Reports Tab -------------------
with tab_reports:
    st.subheader("Generate Report")
    locations = get_locations()
    prefixes = sorted({loc[:2] for loc in locations if len(loc) >= 2})

    with st.form("report_form"):
        prefix = st.selectbox("Location Prefix", ["All"] + prefixes, key="r_prefix")
        custom_loc = st.text_input("Custom Location Filter", key="r_custom")
        zero_only = st.checkbox("Show only zero-quantity items", key="r_zero")
        r_start = st.date_input("Start Date", value=datetime(2020, 1, 1), key="r_start")
        r_end = st.date_input("End Date", value=datetime.today(), key="r_end")
        generate = st.form_submit_button("Generate Report")

    if generate:
        q = "SELECT rowid, * FROM inventory WHERE 1=1"
        p = []

        if prefix != "All":
            q += " AND location LIKE ?"
            p.append(f"{prefix}%")
        if custom_loc:
            q += " AND location LIKE ?"
            p.append(f"%{custom_loc}%")
        if zero_only:
            q += " AND quantity = 0"

        df_inv = pd.read_sql_query(q, conn, params=p)

        # Last transaction per item
        last_tx = pd.read_sql_query("""
            SELECT item, MAX(timestamp) as last_tx 
            FROM transactions 
            GROUP BY item
        """, conn)
        df_report = df_inv.merge(last_tx, on='item', how='left')
        df_report['last_tx'] = pd.to_datetime(df_report['last_tx'], errors='coerce')

        # Date filter
        mask = (df_report['last_tx'].isna()) | \
               ((df_report['last_tx'] >= pd.Timestamp(r_start)) & 
                (df_report['last_tx'] <= pd.Timestamp(r_end)))
        df_report = df_report[mask]

        if df_report.empty:
            st.warning("No items match the filters.")
        else:
            st.write("### Report Preview")
            st.dataframe(df_report[['location', 'item', 'quantity', 'notes', 'last_tx']])

            # In-memory PDF
            buffer = io.BytesIO()
            doc = fitz.open()
            page = doc.new_page()
            text = "CNC1 Tool Crib Report\n\n" + df_report[['location', 'item', 'quantity', 'last_tx']].to_string(index=False)
            page.insert_text((50, 50), text, fontsize=9)
            doc.save(buffer)
            doc.close()
            buffer.seek(0)

            st.download_button(
                label="Download PDF Report",
                data=buffer.getvalue(),
                file_name=f"report_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf"
            )
