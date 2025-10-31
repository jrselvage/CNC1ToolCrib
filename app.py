import streamlit as st
import sqlite3
import pandas as pd
import re
from datetime import datetime
import os.d
import os
import threading
import time
import schedule

# =============================================
# CONFIG: GOOGLE DRIVE SYNC
# =============================================
GDRIVE_FILE_ID = "1aBcDeFgHiJkLmN1234567890"  # ← CHANGE THIS!
DB_PATH = "inventory.db"
BACKUP_INTERVAL_MINUTES = 3  # Auto-save every 3 mins

# =============================================
# AUTO DOWNLOAD / UPLOAD FROM GOOGLE DRIVE
# =============================================
def download_db_from_drive():
    if not os.path.exists(DB_PATH):
        try:
            import gdown
            with st.spinner("Downloading database from Google Drive..."):
                url = f"https://drive.google.com/uc?id={GDRIVE_FILE_ID}"
                gdown.download(url, DB_PATH, quiet=False)
            st.success("Database restored from Google Drive")
            return True
        except Exception as e:
            st.error(f"Failed to download DB: {e}")
            return False
    return True

def upload_db_to_drive():
    try:
        import gdown
        url = f"https://drive.google.com/uc?id={GDRIVE_FILE_ID}"
        gdown.upload(DB_PATH, url, resume=True)
        st.sidebar.success(f"DB auto-saved to Drive @ {datetime.now():%H:%M}")
    except Exception as e:
        st.sidebar.error(f"Backup failed: {e}")

# Background auto-backup
def run_auto_backup():
    schedule.every(BACKUP_INTERVAL_MINUTES).minutes.do(upload_db_to_drive)
    while True:
        schedule.run_pending()
        time.sleep(30)

# Start backup thread (once)
if 'drive_sync_started' not in st.session_state:
    if download_db_from_drive():
        thread = threading.Thread(target=run_auto_backup, daemon=True)
        thread.start()
        st.session_state.drive_sync_started = True
    else:
        st.warning("Using local DB (will be lost on reboot unless backed up)")

# =============================================
# ENSURE DB EXISTS LOCALLY
# =============================================
if not os.path.exists(DB_PATH):
    # Create empty DB if download failed
    conn = sqlite3.connect(DB_PATH)
    conn.close()

# =============================================
# DATABASE CONNECTION
# =============================================
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

# =============================================
# PAGE CONFIG
# =============================================
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory System")

# =============================================
# HELPERS
# =============================================
def extract_cabinet(loc):
    match = re.search(r'\d{1,3}', str(loc))
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

# =============================================
# SIDEBAR: ADD ITEM
# =============================================
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
            upload_db_to_drive()  # Immediate backup
            st.rerun()

# =============================================
# SIDEBAR: MANUAL BACKUP/RESTORE
# =============================================
st.sidebar.markdown("---")
st.sidebar.subheader("Manual Backup")

# Download
with open(DB_PATH, "rb") as f:
    st.sidebar.download_button(
        "Download inventory.db",
        f.read(),
        file_name=f"inventory_backup_{datetime.now():%Y%m%d_%H%M}.db",
        mime="application/octet-stream"
    )

# Upload (fallback)
uploaded = st.sidebar.file_uploader("Restore from backup", type=["db"])
if uploaded:
    with open(DB_PATH, "wb") as f:
        f.write(uploaded.getbuffer())
    st.success("Database restored from upload!")
    upload_db_to_drive()
    st.rerun()

# =============================================
# ADMIN PANEL
# =============================================
st.sidebar.markdown("---")
st.sidebar.subheader("Admin Tools")
ADMIN_PASSWORD = "surgeprotection"

if 'admin_authenticated' not in st.session_state:
    st.session_state.admin_authenticated = False

with st.sidebar.expander("Admin: Toggle 0 to 1", expanded=False):
    if not st.session_state.admin_authenticated:
        pwd = st.text_input("Password", type="password", key="admin_pwd")
        if st.button("Login", key="admin_login"):
            if pwd == ADMIN_PASSWORD:
                st.session_state.admin_authenticated = True
                st.rerun()
            else:
                st.error("Wrong password")
    else:
        st.success("Authenticated")
        if st.button("Logout"):
            st.session_state.admin_authenticated = False
            st.rerun()

        st.markdown("**Toggle 0 ↔ 1**")
        cabinets = get_cabinets()
        drawers = get_drawers()

        toggle_cab = st.selectbox("Cabinet", ["All"] + cabinets, key="toggle_cab")
        toggle_drw = st.selectbox("Drawer", ["All"] + drawers, key="toggle_drw")

        if st.button("Toggle 0 to 1", type="primary"):
            with st.spinner("Updating..."):
                q = "SELECT rowid, quantity FROM inventory WHERE 1=1"
                p = []
                if toggle_cab != "All" and toggle_drw != "All":
                    q += " AND location = ?"; p.append(f"{toggle_cab}{toggle_drw}")
                elif toggle_cab != "All":
                    q += " AND location LIKE ?"; p.append(f"{toggle_cab}%")
                elif toggle_drw != "All":
                    q += " AND location LIKE ?"; p.append(f"%{toggle_drw}")

                cur.execute(q, p)
                rows = cur.fetchall()
                updated = 0
                for rowid, qty in rows:
                    new_qty = 1 if qty == 0 else 0
                    cur.execute("UPDATE inventory SET quantity=? WHERE rowid=?", (new_qty, rowid))
                    updated += 1
                conn.commit()
                upload_db_to_drive()  # Backup after admin change
                st.success(f"Toggled {updated} items")
                st.rerun()

# =============================================
# TABS
# =============================================
tab_inv, tab_tx, tab_rep = st.tabs(["Inventory", "Transactions", "Reports"])

# =============================================
# INVENTORY TAB
# =============================================
with tab_inv:
    st.subheader("Search Inventory")

    cabinets = get_cabinets()
    drawers = get_drawers()

    if not cabinets:
        st.warning("No cabinets found. Add items with locations like 5A.")
    if not drawers:
        st.info("No drawers found. Use letters like 5A, 12B.")

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
                            upload_db_to_drive()
                            st.success("Saved")
                            st.rerun()
                    act = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"a_{r['id']}")
                    usr = st.text_input("User", key=f"u_{r['id']}")
                    q_val = st.number_input("Qty", min_value=1, value=1, key=f"q_{r['id']}")

                    if st.button("Submit", key=f"sub_{r['id']}") and act != "None" and usr.strip():
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cur.execute(
                            "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?, ?, ?, ?, ?)",
                            (r['item'], act, usr.strip(), ts, q_val)
                        )
                        new_qty = r['quantity'] - q_val if act == "Check Out" else r['quantity'] + q_val
                        cur.execute("UPDATE inventory SET quantity=? WHERE rowid=?", (max(0, new_qty), r['id']))
                        conn.commit()
                        upload_db_to_drive()
                        st.success(f"{act}: {q_val}")
                        st.rerun()

# =============================================
# TRANSACTIONS TAB
# =============================================
with tab_tx:
    st.subheader("Recent Transactions")
    df_tx = pd.read_sql_query("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 100", conn)
    if df_tx.empty:
        st.info("No transactions yet.")
    else:
        st.dataframe(df_tx[['timestamp', 'action', 'qty', 'item', 'user']], use_container_width=True)

# =============================================
# REPORTS TAB
# =============================================
with tab_rep:
    st.subheader("Full Inventory Report")
    df = pd.read_sql_query("SELECT location, item, quantity, notes FROM inventory ORDER BY location", conn)
    if df.empty:
        st.info("No items.")
    else:
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False).encode()
        st.download_button(
            "Download CSV",
            csv,
            file_name=f"inventory_report_{datetime.now():%Y%m%d}.csv",
            mime="text/csv"
        )
