import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import io

# ------------------- CONFIG -------------------
DB_PATH = "inventory.db"

# ------------------- DATABASE SETUP -------------------
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

# Indexes
cursor.execute("CREATE INDEX IF NOT EXISTS idx_location ON inventory(location)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_item ON inventory(item)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_item ON transactions(item)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)")
conn.commit()

# ------------------- PAGE -------------------
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory System")

# ------------------- CACHED: Cabinets & Drawers -------------------
@st.cache_data(ttl=300)
def get_cabinets():
    df = pd.read_sql_query("""
        SELECT DISTINCT SUBSTR(location, 1, 3) AS cab
        FROM inventory 
        WHERE location GLOB '[0-9][0-9][0-9]*'
    """, conn)
    return sorted(df['cab'].dropna().unique(), key=int)

@st.cache_data(ttl=300)
def get_drawers():
    df = pd.read_sql_query("""
        SELECT DISTINCT UPPER(SUBSTR(location, 4)) AS drw
        FROM inventory 
        WHERE location GLOB '*[A-Za-z]'
    """, conn)
    return sorted(df['drw'].dropna().unique().tolist())

# ------------------- SIDEBAR: ADD ITEM + EXCEL RESTORE -------------------
st.sidebar.header("Add New Item")
with st.sidebar.form("add_form", clear_on_submit=True):
    new_item = st.text_input("Item Name")
    new_loc = st.text_input("Location (e.g., 105A)").strip().upper()
    new_qty = st.number_input("Quantity", min_value=0, step=1, value=0)
    new_notes = st.text_area("Notes")
    add_submitted = st.form_submit_button("Add Item")

    if add_submitted and new_item and new_loc:
        cursor.execute(
            "INSERT INTO inventory (location, item, notes, quantity) VALUES (?, ?, ?, ?)",
            (new_loc, new_item.strip(), new_notes.strip(), int(new_qty))
        )
        conn.commit()
        st.success(f"Added: {new_item}")
        st.rerun()

# --- EXCEL RESTORE BUTTON (BOTTOM LEFT) ---
st.sidebar.markdown("---")
st.sidebar.subheader("Restore from Excel")
uploaded_file = st.sidebar.file_uploader("Upload .xlsx backup", type=["xlsx"], key="restore")

if uploaded_file:
    try:
        # Read both sheets
        dfs = pd.read_excel(uploaded_file, sheet_name=None)

        inv_df = dfs.get("Inventory", pd.DataFrame())
        tx_df = dfs.get("Transactions", pd.DataFrame())

        # Validate & clean
        inv_cols = ["location", "item", "notes", "quantity"]
        tx_cols = ["item", "action", "user", "timestamp", "qty"]

        inv_df = inv_df[inv_cols].fillna("") if not inv_df.empty else pd.DataFrame(columns=inv_cols)
        tx_df = tx_df[tx_cols].fillna("") if not tx_df.empty else pd.DataFrame(columns=tx_cols)

        # Replace DB tables
        cursor.execute("DELETE FROM inventory")
        cursor.execute("DELETE FROM transactions")

        for _, row in inv_df.iterrows():
            cursor.execute("INSERT INTO inventory VALUES (?, ?, ?, ?)",
                           (row['location'], row['item'], row['notes'], int(row['quantity'] or 0)))

        for _, row in tx_df.iterrows():
            cursor.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?)",
                           (row['item'], row['action'], row['user'], row['timestamp'], int(row['qty'] or 0)))

        conn.commit()
        st.success("Database restored from Excel!")
        st.rerun()
    except Exception as e:
        st.error(f"Restore failed: {e}")

# --- DB BACKUP ---
st.sidebar.markdown("---")
st.sidebar.subheader("Backup")
try:
    with open(DB_PATH, "rb") as f:
        st.sidebar.download_button(
            "Download DB (.db)",
            f.read(),
            file_name=f"inventory_backup_{datetime.now():%Y%m%d_%H%M}.db",
            mime="application/octet-stream"
        )
except:
    st.sidebar.error("DB not found")

# ------------------- TABS -------------------
tab_inventory, tab_transactions, tab_reports = st.tabs(["Inventory", "Transactions", "Reports"])

# ------------------- INVENTORY TAB -------------------
with tab_inventory:
    st.subheader("Search Inventory")

    cabinets = get_cabinets()
    drawers = get_drawers()

    col1, col2, col3, col4 = st.columns(4)
    with col1: search_name = st.text_input("Item Name", key="search_name")
    with col2: cabinet = st.selectbox("Cabinet #", ["All"] + cabinets, key="cabinet")
    with col3: drawer = st.selectbox("Drawer", ["All"] + drawers, key="drawer")
    with col4: qty_filter = st.number_input("Exact Qty", min_value=0, step=1, value=0, key="qty_filter")

    has_filter = search_name or (cabinet != "All") or (drawer != "All") or (qty_filter > 0)

    if not has_filter:
        st.info("Use filters to search.")
    else:
        @st.cache_data(ttl=60)
        def search_inventory(name="", cab="All", drw="All", qty=0):
            q = "SELECT rowid AS id, location, item, notes, quantity FROM inventory WHERE 1=1"
            p = []
            if name: q += " AND item LIKE ?"; p.append(f"%{name}%")
            if cab != "All" and drw != "All":
                q += " AND location = ?"; p.append(f"{cab}{drw}")
            elif cab != "All":
                q += " AND location LIKE ?"; p.append(f"{cab}%")
            elif drw != "All":
                q += " AND location LIKE ?"; p.append(f"%{drw}")
            if qty > 0: q += " AND quantity = ?"; p.append(qty)
            q += " ORDER BY location, item"
            return pd.read_sql_query(q, conn, params=p)

        df = search_inventory(search_name, cabinet, drawer, qty_filter)

        if df.empty:
            st.warning("No items found.")
        else:
            st.write(f"**{len(df)} item(s) found**")
            for _, row in df.iterrows():
                with st.expander(f"{row['item']} @ {row['location']} — Qty: {row['quantity']}"):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        notes = st.text_area("Notes", value=row['notes'] or "", key=f"notes_{row['id']}", height=70)
                        if st.button("Save Notes", key=f"save_{row['id']}"):
                            cursor.execute("UPDATE inventory SET notes = ? WHERE rowid = ?", (notes.strip(), row['id']))
                            conn.commit()
                            st.success("Saved")
                            st.rerun()

                    action = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"act_{row['id']}")
                    user = st.text_input("Your Name", key=f"user_{row['id']}")
                    qty = st.number_input("Qty", min_value=1, step=1, value=1, key=f"qty_{row['id']}")

                    bc1, bc2 = st.columns(2)
                    with bc1:
                        if st.button("Submit", key=f"sub_{row['id']}") and action != "None" and user.strip():
                            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            cursor.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?)",
                                           (row['item'], action, user.strip(), ts, qty))
                            new_qty = row['quantity'] - qty if action == "Check Out" else row['quantity'] + qty
                            cursor.execute("UPDATE inventory SET quantity = ? WHERE rowid = ?", (max(0, new_qty), row['id']))
                            conn.commit()
                            st.success(f"{action}: {qty}")
                            st.rerun()
                    with bc2:
                        if st.button("Delete", key=f"del_{row['id']}") and user.strip():
                            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            cursor.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?)",
                                           (row['item'], "Deleted", user.strip(), ts, row['quantity']))
                            cursor.execute("DELETE FROM inventory WHERE rowid = ?", (row['id'],))
                            conn.commit()
                            st.warning("Deleted")
                            st.rerun()

# ------------------- TRANSACTIONS TAB (WITH EXCEL EXPORT) -------------------
with tab_transactions:
    st.subheader("Transaction History")

    c1, c2, c3, c4 = st.columns(4)
    with c1: t_item = st.text_input("Item", key="t_item")
    with c2: t_user = st.text_input("User", key="t_user")
    with c3: t_action = st.selectbox("Action", ["All", "Check Out", "Check In", "Deleted"], key="t_action")
    with c4: t_qty = st.number_input("Qty", min_value=0, value=0, key="t_qty")

    start = st.date_input("From", value=datetime(2020,1,1), key="t_start")
    end = st.date_input("To", value=datetime.today(), key="t_end")

    s_str = start.strftime("%Y-%m-%d 00:00:00")
    e_str = (end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

    @st.cache_data(ttl=60)
    def load_tx(item="", user="", action="All", qty=0, s="", e=""):
        q = "SELECT * FROM transactions WHERE timestamp BETWEEN ? AND ?"
        p = [s, e]
        if item: q += " AND item LIKE ?"; p.append(f"%{item}%")
        if user: q += " AND user LIKE ?"; p.append(f"%{user}%")
        if action != "All": q += " AND action = ?"; p.append(action)
        if qty > 0: q += " AND qty = ?"; p.append(qty)
        q += " ORDER BY timestamp DESC LIMIT 1000"
        return pd.read_sql_query(q, conn, params=p)

    df_tx = load_tx(t_item, t_user, t_action, t_qty, s_str, e_str)

    if df_tx.empty:
        st.info("No transactions.")
    else:
        st.dataframe(df_tx[['timestamp','action','qty','item','user']], use_container_width=True, hide_index=True)

        # --- EXPORT TRANSACTIONS TO EXCEL ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df_tx.to_excel(writer, sheet_name="Transactions", index=False)
        output.seek(0)

        st.download_button(
            "Download Transactions (.xlsx)",
            output.getvalue(),
            file_name=f"transactions_{datetime.now():%Y%m%d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ------------------- REPORTS TAB (EXCEL OUTPUT) -------------------
with tab_reports:
    st.subheader("Generate Report")

    cabinets_report = get_cabinets()

    with st.form("report_form"):
        prefix = st.selectbox("Cabinet #", ["All"] + cabinets_report, key="r_prefix")
        custom = st.text_input("Custom Location Filter", key="r_custom")
        zero = st.checkbox("Zero quantity only", key="r_zero")
        r_start = st.date_input("Start Date", value=datetime(2020,1,1), key="r_start")
        r_end = st.date_input("End Date", value=datetime.today(), key="r_end")
        gen = st.form_submit_button("Generate")

    if gen:
        @st.cache_data
        def build_report(pfx, cust, zero, s, e):
            q = "SELECT location, item, quantity, notes FROM inventory WHERE 1=1"
            p = []
            if pfx != "All": q += " AND location LIKE ?"; p.append(f"{pfx}%")
            if cust: q += " AND location LIKE ?"; p.append(f"%{cust}%")
            if zero: q += " AND quantity = 0"
            df = pd.read_sql_query(q, conn, params=p)

            tx_q = "SELECT item, MAX(timestamp) as last_tx FROM transactions WHERE timestamp BETWEEN ? AND ? GROUP BY item"
            s_str = s.strftime("%Y-%m-%d 00:00:00")
            e_str = e.strftime("%Y-%m-%d 23:59:59")
            last_tx = pd.read_sql_query(tx_q, conn, params=[s_str, e_str])
            df = df.merge(last_tx, on='item', how='left')
            return df

        df_r = build_report(prefix, custom, zero, r_start, r_end)

        if df_r.empty:
            st.warning("No data.")
        else:
            st.write("### Preview")
            st.dataframe(df_r, use_container_width=True)

            # --- EXPORT TO EXCEL ---
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_r.to_excel(writer, sheet_name="Inventory Report", index=False)
            output.seek(0)

            st.download_button(
                "Download Report (.xlsx)",
                output.getvalue(),
                file_name=f"report_{datetime.now():%Y%m%d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
