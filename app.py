import streamlit as st
import sqlite3
import pandas as pd
import re
from datetime import datetime

# -------------------------------------------------
#  CONFIG
# -------------------------------------------------
DB_PATH = "inventory.db"

# -------------------------------------------------
#  DATABASE
# -------------------------------------------------
@st.cache_resource
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

conn = get_connection()
cur = conn.cursor()

# Create tables
cur.execute("""CREATE TABLE IF NOT EXISTS inventory (
    location TEXT, item TEXT, notes TEXT, quantity INTEGER
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS transactions (
    item TEXT, action TEXT, user TEXT, timestamp TEXT, qty INTEGER
)""")

# Indexes
cur.execute("CREATE INDEX IF NOT EXISTS idx_loc ON inventory(location)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_item ON inventory(item)")
conn.commit()

# -------------------------------------------------
#  PAGE
# -------------------------------------------------
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory System")

# -------------------------------------------------
#  HELPERS – EXTRACT 1, 2, OR 3-DIGIT CABINETS
# -------------------------------------------------
def extract_cabinet(loc):
    """Extract first 1–3 digits: 5A → 5, 12B → 12, 105C → 105"""
    if not loc:
        return None
    match = re.search(r'\d{1,3}', str(loc))
    return match.group(0) if match else None

def extract_drawer(loc):
    """Extract first letter after digits: 5A → A, 12 B → B"""
    if not loc:
        return None
    match = re.search(r'(?<=\d)[A-Za-z]', str(loc))
    return match.group(0).upper() if match else None

def get_cabinets():
    df = pd.read_sql_query("SELECT location FROM inventory", conn)
    cabs = [extract_cabinet(loc) for loc in df['location']]
    return sorted({c for c in cabs if c}, key=int)

def get_drawers():
    df = pd.read_sql_query("SELECT location FROM inventory", conn)
    drws = [extract_drawer(loc) for loc in df['location']]
    return sorted({d for d in drws if d})

# -------------------------------------------------
#  SIDEBAR – ADD ITEM (SUPPORTS 1–3 DIGIT CABINETS)
# -------------------------------------------------
st.sidebar.header("Add New Item")
with st.sidebar.form("add_form", clear_on_submit=True):
    new_item = st.text_input("Item Name")
    new_loc = st.text_input("Location (e.g., 5A, 12B, 105C)").strip().upper()
    new_qty = st.number_input("Quantity", min_value=0, step=1, value=0)
    new_notes = st.text_area("Notes")
    add = st.form_submit_button("Add Item")

    if add and new_item and new_loc:
        clean_loc = re.sub(r'[^0-9A-Z]', '', new_loc)
        if not re.match(r'^\d{1,3}[A-Z]$', clean_loc):
            st.error("Location must be like 5A, 12B, or 105C")
        else:
            cur.execute(
                "INSERT INTO inventory (location, item, notes, quantity) VALUES (?, ?, ?, ?)",
                (clean_loc, new_item.strip(), new_notes.strip(), int(new_qty))
            )
            conn.commit()
            st.success(f"Added {new_item} @ {clean_loc}")
            st.rerun()

# -------------------------------------------------
#  SIDEBAR – DB BACKUP
# -------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Backup")
try:
    with open(DB_PATH, "rb") as f:
        st.sidebar.download_button(
            "Download DB (.db)",
            f.read(),
            file_name=f"backup_{datetime.now():%Y%m%d}.db",
            mime="application/octet-stream"
        )
except:
    st.sidebar.error("DB not accessible")

# -------------------------------------------------
#  TABS
# -------------------------------------------------
tab_inv, tab_tx, tab_rep = st.tabs(["Inventory", "Transactions", "Reports"])

# -------------------------------------------------
#  INVENTORY TAB – SHOWS 1–3 DIGIT CABINETS
# -------------------------------------------------
with tab_inv:
    st.subheader("Search Inventory")

    cabinets = get_cabinets()
    drawers = get_drawers()

    if not cabinets:
        st.warning("No cabinet numbers found. Use format like 5A, 12B, 105C.")
    if not drawers:
        st.info("No drawers found. Need letter after number (e.g., 5A).")

    c1, c2, c3, c4 = st.columns(4)
    with c1: name = st.text_input("Item Name", key="s_name")
    with c2: cab = st.selectbox("Cabinet #", ["All"] + cabinets, key="s_cab")
    with c3: drw = st.selectbox("Drawer", ["All"] + drawers, key="s_drw")
    with c4: qty = st.number_input("Exact Qty", min_value=0, value=0, key="s_qty")

    has_filter = name or (cab != "All") or (drw != "All") or (qty > 0)

    if not has_filter:
        st.info("Use filters to search.")
    else:
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

        df = pd.read_sql_query(q, conn, params=p)

        if df.empty:
            st.warning("No items found.")
        else:
            st.write(f"**{len(df)} item(s) found**")
            for _, r in df.iterrows():
                with st.expander(f"{r['item']} @ {r['location']} — Qty: {r['quantity']}"):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        notes = st.text_area("Notes", value=r['notes'] or "", key=f"n_{r['id']}", height=70)
                        if st.button("Save", key=f"sv_{r['id']}"):
                            cur.execute("UPDATE inventory SET notes=? WHERE rowid=?", (notes.strip(), r['id']))
                            conn.commit()
                            st.success("Saved")
                            st.rerun()
                    act = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"a_{r['id']}")
                    usr = st.text_input("User", key=f"u_{r['id']}")
                    q_val = st.number_input("Qty", min_value=1, value=1, key=f"q_{r['id']}")

                    if st.button("Submit", key=f"sub_{r['id']}") and act != "None" and usr:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cur.execute(
                            "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?, ?, ?, ?, ?)",
                            (r['item'], act, usr.strip(), ts, q_val)
                        )
                        new_qty = r['quantity'] - q_val if act == "Check Out" else r['quantity'] + q_val
                        cur.execute("UPDATE inventory SET quantity=? WHERE rowid=?", (max(0, new_qty), r['id']))
                        conn.commit()
                        st.success(f"{act}: {q_val}")
                        st.rerun()

# -------------------------------------------------
#  TRANSACTIONS TAB
# -------------------------------------------------
with tab_tx:
    st.subheader("Recent Transactions")
    df_tx = pd.read_sql_query("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 100", conn)
    if df_tx.empty:
        st.info("No transactions yet.")
    else:
        st.dataframe(df_tx[['timestamp', 'action', 'qty', 'item', 'user']], use_container_width=True)

# -------------------------------------------------
#  REPORTS TAB
# -------------------------------------------------
with tab_rep:
    st.subheader("Full Report")
    df = pd.read_sql_query("SELECT location, item, quantity, notes FROM inventory ORDER BY location", conn)
    if df.empty:
        st.info("No data in inventory.")
    else:
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False).encode()
        st.download_button("Download Report (CSV)", csv, "report.csv", "text/csv")
