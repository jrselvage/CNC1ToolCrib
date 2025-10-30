import streamlit as st
import sqlite3
import pandas as pd
import re
from datetime import datetime
import io

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

# tables
cur.execute("""CREATE TABLE IF NOT EXISTS inventory (
    location TEXT, item TEXT, notes TEXT, quantity INTEGER)""")
cur.execute("""CREATE TABLE IF NOT EXISTS transactions (
    item TEXT, action TEXT, user TEXT, timestamp TEXT, qty INTEGER)""")

# indexes
cur.execute("CREATE INDEX IF NOT EXISTS idx_loc   ON inventory(location)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_item  ON inventory(item)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_i  ON transactions(item)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_ts ON transactions(timestamp)")
conn.commit()

# -------------------------------------------------
#  PAGE
# -------------------------------------------------
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory System")

# -------------------------------------------------
#  HELPERS – ROBUST CABINET/DRAWER EXTRACTION
# -------------------------------------------------
def extract_cabinet(location):
    """Extract first 3 digits from location (e.g., '105A' → '105', 'Cab 105 Drawer A' → '105')"""
    if not location:
        return None
    match = re.search(r'\d{3}', str(location))
    return match.group(0) if match else None

def extract_drawer(location):
    """Extract first letter after digits (e.g., '105A' → 'A', '105 A' → 'A')"""
    if not location:
        return None
    match = re.search(r'(?<=\d)[A-Za-z]', str(location))
    return match.group(0).upper() if match else None

def get_cabinets():
    df = pd.read_sql_query("SELECT location FROM inventory", conn)
    cabinets = []
    for loc in df['location']:
        cab = extract_cabinet(loc)
        if cab:
            cabinets.append(cab)
    unique = sorted(set(cabinets), key=int)
    return unique

def get_drawers():
    df = pd.read_sql_query("SELECT location FROM inventory", conn)
    drawers = []
    for loc in df['location']:
        drw = extract_drawer(loc)
        if drw:
            drawers.append(drw)
    return sorted(set(drawers))

# -------------------------------------------------
#  SIDEBAR – add item
# -------------------------------------------------
st.sidebar.header("Add New Item")
with st.sidebar.form("add_form", clear_on_submit=True):
    new_item = st.text_input("Item Name")
    new_loc  = st.text_input("Location (e.g., 105A)").strip().upper()
    new_qty  = st.number_input("Quantity", min_value=0, step=1, value=0)
    new_notes= st.text_area("Notes")
    add = st.form_submit_button("Add Item")

    if add and new_item and new_loc:
        # Normalize location
        norm_loc = re.sub(r'\s+|-+', '', new_loc)  # Remove spaces and dashes
        cur.execute("INSERT INTO inventory (location, item, notes, quantity) VALUES (?,?,?,?)",
                    (norm_loc, new_item.strip(), new_notes.strip(), int(new_qty)))
        conn.commit()
        st.success(f"Added {new_item} @ {norm_loc}")
        st.rerun()

# -------------------------------------------------
#  SIDEBAR – RESTORE FROM CSV (NORMALIZED + DEBUG)
# -------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Restore from CSV")
st.sidebar.caption("CSV can have any location format. We'll normalize to `105A`.")

inv_csv = st.sidebar.file_uploader("Inventory CSV", type=["csv"], key="inv_csv")
tx_csv  = st.sidebar.file_uploader("Transactions CSV", type=["csv"], key="tx_csv")

if inv_csv and tx_csv:
    if st.sidebar.button("Restore Database from CSV", type="primary"):
        with st.spinner("Restoring and normalizing locations..."):
            try:
                inv = pd.read_csv(inv_csv).fillna("")
                tx  = pd.read_csv(tx_csv).fillna("")

                inv_cols = ["location", "item", "notes", "quantity"]
                tx_cols  = ["item", "action", "user", "timestamp", "qty"]

                inv = inv[[c for c in inv_cols if c in inv.columns]]
                tx  = tx[[c for c in tx_cols if c in tx.columns]]

                if len(inv.columns) < 4:
                    st.error("Inventory CSV must have: location, item, notes, quantity")
                    st.stop()

                # Normalize locations during import
                normalized_locs = []
                for loc in inv['location']:
                    clean = re.sub(r'\s+|-+', '', str(loc).strip().upper())
                    norm = re.sub(r'[^0-9A-Z]', '', clean)  # Keep only digits + letters
                    normalized_locs.append(norm)

                inv['location'] = normalized_locs

                # Debug: show first 5
                st.write("**First 5 normalized locations:**")
                st.write(inv['location'].head())

                cur.execute("DELETE FROM inventory")
                cur.execute("DELETE FROM transactions")

                for _, r in inv.iterrows():
                    loc = r['location']
                    if len(loc) < 4:
                        st.warning(f"Skipping invalid location: {loc}")
                        continue
                    cur.execute(
                        "INSERT INTO inventory (location, item, notes, quantity) VALUES (?,?,?,?)",
                        (loc, r['item'], r['notes'], int(r['quantity']))
                    )

                for _, r in tx.iterrows():
                    cur.execute(
                        "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?,?,?,?,?)",
                        (r['item'], r['action'], r['user'], r['timestamp'], int(r['qty']))
                    )

                conn.commit()
                st.success("Database restored! Page reloading...")
                st.rerun()
            except Exception as e:
                st.error(f"Restore failed: {e}")
else:
    st.sidebar.info("Upload both CSV files to enable restore.")

# -------------------------------------------------
#  SIDEBAR – DB backup
# -------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Backup")
try:
    with open(DB_PATH,"rb") as f:
        st.sidebar.download_button(
            "Download DB (.db)",
            f.read(),
            file_name=f"inv_backup_{datetime.now():%Y%m%d_%H%M}.db",
            mime="application/octet-stream")
except:
    st.sidebar.error("DB file not accessible")

# -------------------------------------------------
#  TABS
# -------------------------------------------------
tab_inv, tab_tx, tab_rep = st.tabs(["Inventory","Transactions","Reports"])

# -------------------------------------------------
#  INVENTORY TAB – DROPDOWNS NOW WORK
# -------------------------------------------------
with tab_inv:
    st.subheader("Search Inventory")

    cabinets = get_cabinets()
    drawers = get_drawers()

    if not cabinets:
        st.warning("No cabinet numbers found. Check CSV `location` column (e.g., `105A`, `105 A`, `Cab 105`).")
    if not drawers:
        st.info("No drawers found. Need letter after number (e.g., `105A`).")

    c1,c2,c3,c4 = st.columns(4)
    with c1: name = st.text_input("Item Name", key="s_name")
    with c2: cab  = st.selectbox("Cabinet #", ["All"] + cabinets, key="s_cab")
    with c3: drw  = st.selectbox("Drawer", ["All"] + drawers, key="s_drw")
    with c4: qty  = st.number_input("Exact Qty", min_value=0, value=0, key="s_qty")

    has_filter = name or (cab != "All") or (drw != "All") or (qty > 0)

    if not has_filter:
        st.info("Use filters to search.")
    else:
        def search(name="", cab="All", drw="All", qty=0):
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

        df = search(name, cab, drw, qty)

        if df.empty:
            st.warning("No items found.")
        else:
            st.write(f"**{len(df)} item(s) found**")
            for _, r in df.iterrows():
                with st.expander(f"{r['item']} @ {r['location']} — Qty: {r['quantity']}"):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        notes = st.text_area("Notes", value=r['notes'] or "", key=f"n_{r['id']}", height=70)
                        if st.button("Save Notes", key=f"sv_{r['id']}"):
                            cur.execute("UPDATE inventory SET notes=? WHERE rowid=?", (notes.strip(), r['id']))
                            conn.commit()
                            st.success("Saved")
                            st.rerun()
                    act = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"a_{r['id']}")
                    usr = st.text_input("Your Name", key=f"u_{r['id']}")
                    q = st.number_input("Qty", min_value=1, value=1, key=f"q_{r['id']}")

                    bc1, bc2 = st.columns(2)
                    with bc1:
                        if st.button("Submit", key=f"sub_{r['id']}") and act != "None" and usr.strip():
                            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            cur.execute("INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?,?,?,?,?)",
                                        (r['item'], act, usr.strip(), ts, q))
                            new_q = r['quantity'] - q if act == "Check Out" else r['quantity'] + q
                            cur.execute("UPDATE inventory SET quantity=? WHERE rowid=?", (max(0, new_q), r['id']))
                            conn.commit()
                            st.success(f"{act}: {q}")
                            st.rerun()
                    with bc2:
                        if st.button("Delete", key=f"del_{r['id']}") and usr.strip():
                            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            cur.execute("INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?,?,?,?,?)",
                                        (r['item'], "Deleted", usr.strip(), ts, r['quantity']))
                            cur.execute("DELETE FROM inventory WHERE rowid=?", (r['id'],))
                            conn.commit()
                            st.warning("Deleted")
                            st.rerun()

# -------------------------------------------------
#  TRANSACTIONS & REPORTS (unchanged)
# -------------------------------------------------
with tab_tx:
    st.subheader("Transaction History")
    # ... (same as before)
    pass  # Keep your existing code

with tab_rep:
    st.subheader("Generate Report")
    # ... (same as before)
    pass
