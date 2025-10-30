import streamlit as st
import sqlite3
import pandas as pd
import fitz
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

# ------------------- CACHED: Get All Unique Locations -------------------
@st.cache_data(ttl=300)
def get_all_locations():
    df = pd.read_sql_query("SELECT DISTINCT location FROM inventory WHERE location IS NOT NULL", conn)
    locations = sorted(df['location'].dropna().unique().tolist())
    return locations

# ------------------- SIDEBAR: ADD ITEM -------------------
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

# ------------------- TABS -------------------
tab_inventory, tab_transactions, tab_reports = st.tabs(["Inventory", "Transactions", "Reports"])

# ------------------- INVENTORY TAB -------------------
with tab_inventory:
    st.subheader("Search Inventory")

    # Get locations for dropdowns
    locations = get_all_locations()
    if not locations:
        st.info("No items in inventory yet. Add items to see locations.")
    else:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            search_name = st.text_input("Item Name", key="search_name")
        with col2:
            cabinet_loc = st.selectbox("Cabinet (Full Location)", ["All"] + locations, key="cabinet_loc")
        with col3:
            drawer_loc = st.selectbox("Drawer (Full Location)", ["All"] + locations, key="drawer_loc")
        with col4:
            qty_filter = st.number_input("Exact Qty", min_value=0, step=1, value=0, key="qty_filter")

        # Only search if at least one filter is active
        has_filter = search_name or (cabinet_loc != "All") or (drawer_loc != "All") or (qty_filter > 0)

        if not has_filter:
            st.info("Use filters above to search inventory.")
        else:
            @st.cache_data(ttl=60)
            def search_inventory(name="", cab="All", drw="All", qty=0):
                q = "SELECT rowid AS id, location, item, notes, quantity FROM inventory WHERE 1=1"
                p = []
                if name:
                    q += " AND item LIKE ?"
                    p.append(f"%{name}%")
                if cab != "All":
                    q += " AND location = ?"
                    p.append(cab)
                if drw != "All":
                    q += " AND location = ?"
                    p.append(drw)
                if qty > 0:
                    q += " AND quantity = ?"
                    p.append(qty)
                q += " ORDER BY location, item"
                return pd.read_sql_query(q, conn, params=p)

            df = search_inventory(search_name, cabinet_loc, drawer_loc, qty_filter)

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

# ------------------- TRANSACTIONS TAB -------------------
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

# ------------------- REPORTS TAB -------------------
with tab_reports:
    st.subheader("Generate Report")

    with st.form("report_form"):
        locations = get_all_locations()
        prefix = st.selectbox("Location", ["All"] + locations, key="r_loc")
        custom = st.text_input("Custom Filter", key="r_custom")
        zero = st.checkbox("Zero quantity only", key="r_zero")
        r_start = st.date_input("Start Date", value=datetime(2020,1,1), key="r_start")
        r_end = st.date_input("End Date", value=datetime.today(), key="r_end")
        gen = st.form_submit_button("Generate")

    if gen:
        @st.cache_data
        def build_report(loc, cust, zero, s, e):
            q = "SELECT location, item, quantity, notes FROM inventory WHERE 1=1"
            p = []
            if loc != "All": q += " AND location = ?"; p.append(loc)
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

            buffer = io.BytesIO()
            doc = fitz.open()
            page = doc.new_page(width=800, height=1100)
            txt = "CNC1 Tool Crib Report\n\n" + df_r[['location','item','quantity','last_tx']].to_string(index=False)
            page.insert_text((50,50), txt, fontsize=9)
            doc.save(buffer)
            doc.close()
            buffer.seek(0)

            st.download_button("Download PDF", buffer.getvalue(), f"report_{datetime.now():%Y%m%d}.pdf", "application/pdf")

# ------------------- BACKUP: DB DOWNLOAD -------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Backup")
try:
    with open(DB_PATH, "rb") as f:
        st.sidebar.download_button(
            "Download DB Backup",
            f.read(),
            file_name=f"inventory_backup_{datetime.now():%Y%m%d_%H%M}.db",
            mime="application/octet-stream"
        )
except:
    st.sidebar.error("DB not found")
