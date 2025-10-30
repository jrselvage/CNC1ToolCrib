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
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA cache_size=10000;")
    return conn

conn = get_connection()
cursor = conn.cursor()

# Create tables
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

# ------------------- ADD INDEXES FOR SPEED -------------------
cursor.execute("CREATE INDEX IF NOT EXISTS idx_location ON inventory(location)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_item ON inventory(item)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_item ON transactions(item)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)")
conn.commit()

# ------------------- Page Config -------------------
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory Management System")

# ------------------- Sidebar: Add Item -------------------
st.sidebar.header("Add New Inventory Item")
with st.sidebar.form("add_item_form"):
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
        st.sidebar.success(f"Added: {new_item}")
        st.rerun()

# ------------------- Tabs -------------------
tab_inventory, tab_transactions, tab_reports = st.tabs(["Inventory", "Transactions", "Reports"])

# ------------------- Helper: Cached Locations -------------------
@st.cache_data(ttl=300)
def get_locations():
    df = pd.read_sql_query("SELECT DISTINCT location FROM inventory WHERE location IS NOT NULL", conn)
    return sorted(df['location'].dropna().unique().tolist())

# ------------------- Inventory Tab (ALL RESULTS, NO PAGINATION) -------------------
with tab_inventory:
    st.subheader("Inventory Search")

    col1, col2, col3, col4 = st.columns(4)
    with col1: search_name = st.text_input("Item Name", key="inv_name")
    with col2: cabinet = st.number_input("Cabinet #", min_value=0, step=1, key="inv_cabinet", value=0)
    with col3: drawer = st.text_input("Drawer", key="inv_drawer").strip().upper()
    with col4: qty_filter = st.number_input("Qty", min_value=0, step=1, key="inv_qty", value=0)

    @st.cache_data(ttl=60)
    def load_inventory(name="", cab=0, drw="", qty=0):
        query = """
        SELECT rowid AS id, location, item, notes, quantity
        FROM inventory
        WHERE 1=1
        """
        params = []
        if name:
            query += " AND item LIKE ?"
            params.append(f"%{name}%")
        if cab > 0:
            query += " AND location LIKE ?"
            params.append(f"{cab}%")
        if drw:
            query += " AND location LIKE ?"
            params.append(f"%{drw}")
        if qty > 0:
            query += " AND quantity = ?"
            params.append(qty)
        query += " ORDER BY location, item"
        return pd.read_sql_query(query, conn, params=params)

    df = load_inventory(search_name, cabinet, drawer, qty_filter)

    if df.empty:
        st.info("No items found.")
    else:
        st.write(f"**Found {len(df)} item(s)**")

        # SHOW ALL RESULTS — NO PAGINATION
        for _, row in df.iterrows():
            item_id = row['id']
            location = row['location']
            name = row['item']
            notes = row['notes'] or ""
            quantity = row['quantity']

            with st.expander(f"{name} @ {location} — Qty: {quantity}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    edited_notes = st.text_area("Notes", value=notes, key=f"n_{item_id}", height=70)
                    if st.button("Save Notes", key=f"s_{item_id}"):
                        cursor.execute("UPDATE inventory SET notes = ? WHERE rowid = ?", (edited_notes.strip(), item_id))
                        conn.commit()
                        st.success("Notes saved")
                        st.rerun()

                action = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"a_{item_id}")
                user = st.text_input("Your Name", key=f"u_{item_id}")
                qty = st.number_input("Qty", min_value=1, step=1, key=f"q_{item_id}", value=1)

                c1, c2 = st.columns(2)
                with c1:
                    submit = st.button("Submit", key=f"sub_{item_id}")
                with c2:
                    delete = st.button("Delete", key=f"del_{item_id}")

                if submit and action != "None" and user.strip():
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute(
                        "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?, ?, ?, ?, ?)",
                        (name, action, user.strip(), ts, qty)
                    )
                    new_qty = quantity - qty if action == "Check Out" else quantity + qty
                    cursor.execute("UPDATE inventory SET quantity = ? WHERE rowid = ?", (max(0, new_qty), item_id))
                    conn.commit()
                    st.success(f"{action}: {qty} of {name}")
                    st.rerun()

                if delete and user.strip():
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute(
                        "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?, ?, ?, ?, ?)",
                        (name, "Deleted", user.strip(), ts, quantity)
                    )
                    cursor.execute("DELETE FROM inventory WHERE rowid = ?", (item_id,))
                    conn.commit()
                    st.warning(f"Deleted: {name}")
                    st.rerun()

# ------------------- Transactions Tab (FAST) -------------------
with tab_transactions:
    st.subheader("Transaction History")

    c1, c2, c3, c4 = st.columns(4)
    with c1: t_item = st.text_input("Item", key="t_item")
    with c2: t_user = st.text_input("User", key="t_user")
    with c3: t_action = st.selectbox("Action", ["All", "Check Out", "Check In", "Deleted"], key="t_action")
    with c4: t_qty = st.number_input("Qty", min_value=0, step=1, key="t_qty", value=0)

    start_date = st.date_input("From", value=datetime(2020, 1, 1), key="t_start")
    end_date = st.date_input("To", value=datetime.today(), key="t_end")

    @st.cache_data(ttl=60)
    def load_transactions(item="", user="", action="All", qty=0, s=start_date, e=end_date):
        q = "SELECT * FROM transactions WHERE timestamp BETWEEN ? AND ?"
        p = [s.strftime("%Y-%m-%d"), f"{e.strftime('%Y-%m-%d')} 23:59:59"]
        if item: q += " AND item LIKE ?"; p.append(f"%{item}%")
        if user: q += " AND user LIKE ?"; p.append(f"%{user}%")
        if action != "All": q += " AND action = ?"; p.append(action)
        if qty > 0: q += " AND qty = ?"; p.append(qty)
        q += " ORDER BY timestamp DESC LIMIT 1000"
        return pd.read_sql_query(q, conn, params=p)

    df_tx = load_transactions(t_item, t_user, t_action, t_qty)

    if df_tx.empty:
        st.info("No transactions found.")
    else:
        st.dataframe(
            df_tx[['timestamp', 'action', 'qty', 'item', 'user']],
            use_container_width=True,
            hide_index=True
        )

# ------------------- Reports Tab (ON-DEMAND) -------------------
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
        @st.cache_data
        def build_report(pfx, cust, zero_only, s, e):
            q = """
            SELECT rowid AS id, location, item, notes, quantity
            FROM inventory
            WHERE 1=1
            """
            p = []
            if pfx != "All":
                q += " AND location LIKE ?"
                p.append(f"{pfx}%")
            if cust:
                q += " AND location LIKE ?"
                p.append(f"%{cust}%")
            if zero_only:
                q += " AND quantity = 0"
            df = pd.read_sql_query(q, conn, params=p)

            last_tx = pd.read_sql_query("""
                SELECT item, MAX(timestamp) as last_tx 
                FROM transactions 
                GROUP BY item
            """, conn)
            df = df.merge(last_tx, on='item', how='left')
            df['last_tx'] = pd.to_datetime(df['last_tx'], errors='coerce')
            mask = df['last_tx'].isna() | ((df['last_tx'] >= pd.Timestamp(s)) & (df['last_tx'] <= pd.Timestamp(e)))
            return df[mask]

        df_report = build_report(prefix, custom_loc, zero_only, r_start, r_end)

        if df_report.empty:
            st.warning("No data matches the selected filters.")
        else:
            st.write("### Report Preview")
            display_cols = ['location', 'item', 'quantity', 'notes', 'last_tx']
            st.dataframe(df_report[display_cols], use_container_width=True)

            # In-memory PDF
            buffer = io.BytesIO()
            doc = fitz.open()
            page = doc.new_page(width=800, height=1100)
            text = "CNC1 Tool Crib Inventory Report\n\n" + \
                   df_report[['location', 'item', 'quantity', 'last_tx']].to_string(index=False)
            page.insert_text((50, 50), text, fontsize=9)
            doc.save(buffer)
            doc.close()
            buffer.seek(0)

            st.download_button(
                label="Download PDF Report",
                data=buffer.getvalue(),
                file_name=f"tool_crib_report_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf"
            )
