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
    conn.execute("PRAGMA cache_size=10000;")
    return conn

conn = get_connection()
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS inventory (
    location TEXT, item TEXT, notes TEXT, quantity INTEGER)""")
cur.execute("""CREATE TABLE IF NOT EXISTS transactions (
    item TEXT, action TEXT, user TEXT, timestamp TEXT, qty INTEGER)""")

cur.execute("CREATE INDEX IF NOT EXISTS idx_loc ON inventory(location)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_item ON inventory(item)")
conn.commit()

# -------------------------------------------------
#  PAGE
# -------------------------------------------------
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory System")

# -------------------------------------------------
#  HELPERS – EXTRACT CABINET & DRAWER
# -------------------------------------------------
def extract_cabinet(loc):
    match = re.search(r'\d{3}', str(loc))
    return match.group(0) if match else None

def extract_drawer(loc):
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
#  SIDEBAR – ADD ITEM
# -------------------------------------------------
st.sidebar.header("Add New Item")
with st.sidebar.form("add_form", clear_on_submit=True):
    new_item = st.text_input("Item Name")
    new_loc = st.text_input("Location (e.g., 105A)").strip().upper()
    new_qty = st.number_input("Quantity", min_value=0, step=1, value=0)
    new_notes = st.text_area("Notes")
    add = st.form_submit_button("Add Item")

    if add and new_item and new_loc:
        clean_loc = re.sub(r'[^0-9A-Z]', '', new_loc)
        if len(clean_loc) < 4:
            st.error("Location must be like 105A")
        else:
            cur.execute("INSERT INTO inventory (location, item, notes, quantity) VALUES (?,?,?,?)",
                        (clean_loc, new_item.strip(), new_notes.strip(), int(new_qty)))
            conn.commit()
            st.success(f"Added {new_item} @ {clean_loc}")
            st.rerun()

# -------------------------------------------------
#  SIDEBAR – RESTORE FROM CSV (FLEXIBLE COLUMNS)
# -------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Restore from CSV")
st.sidebar.caption("**Required:** `Location`, `Item`  \n**Optional:** `quantity`, `notes`, `last_tx`")

inv_csv = st.sidebar.file_uploader("Inventory CSV", type=["csv"], key="inv_csv")
tx_csv  = st.sidebar.file_uploader("Transactions CSV", type=["csv"], key="tx_csv")

if inv_csv and tx_csv:
    if st.sidebar.button("Restore Database from CSV", type="primary"):
        with st.spinner("Restoring..."):
            try:
                inv = pd.read_csv(inv_csv)
                tx  = pd.read_csv(tx_csv)

                # --- INVENTORY: Only Location & Item required ---
                if 'Location' not in inv.columns or 'Item' not in inv.columns:
                    st.error("Inventory CSV must have: **Location**, **Item**")
                    st.stop()

                # Rename to lowercase
                inv = inv.rename(columns={
                    "Location": "location",
                    "Item": "item",
                    "quantity": "quantity",
                    "notes": "notes"
                })

                # Normalize location
                inv['location'] = inv['location'].astype(str).str.strip().str.upper()
                inv['location'] = inv['location'].str.replace(r'[^0-9A-Z]', '', regex=True)

                # Validate format: 105A
                valid = inv['location'].str.match(r'^\d{3}[A-Z]$')
                invalid = inv[~valid]
                if len(invalid) > 0:
                    st.warning(f"Skipped {len(invalid)} invalid locations (need 105A format):")
                    st.write(invalid[['location']].head())
                inv = inv[valid].copy()

                # Fill missing columns
                inv['quantity'] = pd.to_numeric(inv.get('quantity', 0), errors='coerce').fillna(0).astype(int)
                inv['notes'] = inv.get('notes', '').fillna("").astype(str)

                # --- TRANSACTIONS ---
                req_tx = ["item", "action", "user", "timestamp", "qty"]
                if not all(col in tx.columns for col in req_tx):
                    st.error(f"Transactions CSV must have: {', '.join(req_tx)}")
                    st.stop()

                tx['qty'] = pd.to_numeric(tx['qty'], errors='coerce').fillna(0).astype(int)

                # --- CLEAR & INSERT ---
                cur.execute("DELETE FROM inventory")
                cur.execute("DELETE FROM transactions")

                for _, r in inv.iterrows():
                    cur.execute(
                        "INSERT INTO inventory (location, item, notes, quantity) VALUES (?,?,?,?)",
                        (r['location'], r['item'], r['notes'], r['quantity'])
                    )

                for _, r in tx.iterrows():
                    cur.execute(
                        "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?,?,?,?,?)",
                        (r['item'], r['action'], r['user'], r['timestamp'], r['qty'])
                    )

                conn.commit()
                st.success("Restore complete! Reloading...")
                st.rerun()

            except Exception as e:
                st.error(f"Error: {e}")
else:
    st.sidebar.info("Upload both CSV files to restore.")

# -------------------------------------------------
#  SIDEBAR – BACKUP
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
#  INVENTORY TAB
# -------------------------------------------------
with tab_inv:
    st.subheader("Search Inventory")

    cabinets = get_cabinets()
    drawers = get_drawers()

    if not cabinets:
        st.warning("No cabinets found. Check `Location` format (e.g., `105A`).")
    if not drawers:
        st.info("No drawers found. Need letter after number (e.g., `105A`).")

    c1, c2, c3, c4 = st.columns(4)
    with c1: name = st.text_input("Item Name", key="s_name")
    with c2: cab = st.selectbox("Cabinet #", ["All"] + cabinets, key="s_cab")
    with c3: drw = st.selectbox("Drawer", ["All"] + drawers, key="s_drw")
    with c4: qty = st.number_input("Exact Qty", min_value=0, value=0, key="s_qty")

    has_filter = name or (cab != "All") or (drw != "All") or (qty > 0)

    if not has_filter:
        st.info("Apply filters to search.")
    else:
        q = "SELECT rowid AS id, location, item, notes, quantity FROM inventory WHERE 1=1"
        p = []
        if name: q += " AND item LIKE ?"; p.append(f"%{name}%")
        if cab != "All" and drw != "All": q += " AND location = ?"; p.append(f"{cab}{drw}")
        elif cab != "All": q += " AND location LIKE ?"; p.append(f"{cab}%")
        elif drw != "All": q += " AND location LIKE ?"; p.append(f"%{drw}")
        if qty > 0: q += " AND quantity = ?"; p.append(qty)
        q += " ORDER BY location, item"

        df = pd.read_sql_query(q, conn, params=p)

        if df.empty:
            st.warning("No items found.")
        else:
            st.write(f"**{len(df)} item(s)**")
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
                        cur.execute("INSERT INTO transactions VALUES (?,?,?,?,?)",
                                    (r['item'], act, usr, ts, q_val))
                        new_qty = r['quantity'] - q_val if act == "Check Out" else r['quantity'] + q_val
                        cur.execute("UPDATE inventory SET quantity=? WHERE rowid=?", (max(0, new_qty), r['id']))
                        conn.commit()
                        st.success(f"{act}: {q_val}")
                        st.rerun()

# -------------------------------------------------
#  TRANSACTIONS & REPORTS
# -------------------------------------------------
with tab_tx:
    st.subheader("Recent Transactions")
    df_tx = pd.read_sql_query("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 50", conn)
    if not df_tx.empty:
        st.dataframe(df_tx[['timestamp', 'action', 'qty', 'item', 'user']], use_container_width=True)
    else:
        st.info("No transactions yet.")

with tab_rep:
    st.subheader("Report")
    df = pd.read_sql_query("SELECT location, item, quantity, notes FROM inventory ORDER BY location", conn)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False).encode()
        st.download_button("Download Report (CSV)", csv, "report.csv", "text/csv")
    else:
        st.info("No data.")
