import streamlit as st
import sqlite3
import pandas as pd
import re
from datetime import datetime
import os
import threading
import time
import schedule
import io
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# =============================================
# LOGGING SETUP (SEE SYNC IN LOGS)
# =============================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
# CONFIG: GOOGLE DRIVE API
# =============================================
DRIVE_FILE_ID = "1LK4IygkqQCHGC02W8KufRIixIqNpHux6"
DB_PATH = "inventory.db"
BACKUP_INTERVAL_MINUTES = 3

# =============================================
# GOOGLE DRIVE SERVICE
# =============================================
def get_drive_service():
    try:
        credentials = service_account.Credentials.from_service_account_info(
            st.secrets["google_drive"]["service_account"],
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=credentials)
    except Exception as e:
        logger.error(f"[SYNC] Service creation failed: {e}")
        st.error("Google Drive auth failed. Check secrets.")
        return None

# =============================================
# DOWNLOAD FROM GOOGLE DRIVE
# =============================================
def download_db():
    if os.path.exists(DB_PATH):
        logger.info("[SYNC] Local DB exists, skipping download.")
        return True
    try:
        service = get_drive_service()
        if not service:
            return False
        logger.info("[SYNC] Starting download from Google Drive...")
        request = service.files().get_media(fileId=DRIVE_FILE_ID)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        with st.spinner("Downloading database from Google Drive..."):
            while not done:
                status, done = downloader.next_chunk()
        fh.seek(0)
        with open(DB_PATH, "wb") as f:
            f.write(fh.read())
        logger.info("[SYNC] Database restored from Google Drive")
        st.success("Database restored from Google Drive")
        return True
    except Exception as e:
        logger.error(f"[SYNC] Download failed: {e}")
        st.error(f"Download failed: {e}")
        st.info("Starting with empty database.")
        return False

# =============================================
# UPLOAD TO GOOGLE DRIVE (WITH DEBUG)
# =============================================
def upload_db():
    st.sidebar.warning("DEBUG: upload_db() CALLED")  # ← YOU WILL SEE THIS
    try:
        service = get_drive_service()
        if not service:
            st.sidebar.error("Drive service failed")
            return
        logger.info("[SYNC] Starting upload to Google Drive...")
        media = MediaFileUpload(DB_PATH, mimetype="application/octet-stream")
        response = service.files().update(
            fileId=DRIVE_FILE_ID,
            media_body=media
        ).execute()
        msg = f"Saved to Drive @ {datetime.now().strftime('%H:%M:%S')}"
        st.sidebar.success(msg)
        logger.info(f"[SYNC] {msg} | File ID: {response.get('id')}")
        
        # Auto-versioning
        today = datetime.now().strftime("%Y%m%d")
        version_name = f"inventory_{today}.db"
        try:
            service.files().copy(fileId=DRIVE_FILE_ID, body={"name": version_name}).execute()
            logger.info(f"[SYNC] Versioned backup: {version_name}")
        except:
            pass
    except Exception as e:
        error_msg = f"Upload failed: {e}"
        st.sidebar.error(error_msg)
        logger.error(f"[SYNC ERROR] {error_msg}")
        st.sidebar.code(f"Error: {type(e).__name__}")

# =============================================
# AUTO-BACKUP THREAD
# =============================================
def run_auto_backup():
    schedule.every(BACKUP_INTERVAL_MINUTES).minutes.do(upload_db)
    while True:
        schedule.run_pending()
        time.sleep(30)

# Start sync once
if 'sync_started' not in st.session_state:
    download_db()
    if os.path.exists(DB_PATH):
        thread = threading.Thread(target=run_auto_backup, daemon=True)
        thread.start()
        logger.info("[SYNC] Auto-backup thread started")
    st.session_state.sync_started = True

# =============================================
# ENSURE LOCAL DB EXISTS
# =============================================
if not os.path.exists(DB_PATH):
    open(DB_PATH, "a").close()
    logger.info("[DB] Created empty local database")

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
cur.execute("CREATE INDEX IF NOT EXISTS idx_loc ON inventory(location)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_item ON inventory(item)")
conn.commit()

# =============================================
# PAGE CONFIG
# =============================================
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory System")

# Sync status
if st.session_state.get('sync_started', False):
    st.sidebar.success("Cloud Sync: ACTIVE")
else:
    st.sidebar.warning("Cloud Sync: OFFLINE")

# Last local update
if os.path.exists(DB_PATH):
    mod_time = datetime.fromtimestamp(os.path.getmtime(DB_PATH))
    st.sidebar.caption(f"Last local update: {mod_time.strftime('%H:%M:%S')}")

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
            upload_db()  # ← MUST BE HERE
            st.rerun()

# =============================================
# SIDEBAR: MANUAL BACKUP
# =============================================
st.sidebar.markdown("---")
st.sidebar.subheader("Backup Tools")

with open(DB_PATH, "rb") as f:
    st.sidebar.download_button(
        "Download DB",
        f.read(),
        file_name=f"inventory_{datetime.now():%Y%m%d_%H%M}.db",
        mime="application/octet-stream"
    )

if st.sidebar.button("Force Backup Now"):
    upload_db()

uploaded = st.sidebar.file_uploader("Restore DB", type=["db"])
if uploaded:
    with open(DB_PATH, "wb") as f:
        f.write(uploaded.getbuffer())
    st.success("DB restored!")
    upload_db()
    st.rerun()

# =============================================
# ADMIN PANEL
# =============================================
st.sidebar.markdown("---")
st.sidebar.subheader("Admin Tools")
ADMIN_PASSWORD = "surgeprotection"

if 'admin_authenticated' not in st.session_state:
    st.session_state.admin_authenticated = False

with st.sidebar.expander("Toggle 0 to 1", expanded=False):
    if not st.session_state.admin_authenticated:
        pwd = st.text_input("Password", type="password")
        if st.button("Login"):
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

        cabinets = get_cabinets()
        drawers = get_drawers()
        toggle_cab = st.selectbox("Cabinet", ["All"] + cabinets)
        toggle_drw = st.selectbox("Drawer", ["All"] + drawers)

        if st.button("Toggle 0 to 1"):
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
            for rowid, qty in rows:
                new_qty = 1 if qty == 0 else 0
                cur.execute("UPDATE inventory SET quantity=? WHERE rowid=?", (new_qty, rowid))
            conn.commit()
            upload_db()  # ← MUST BE HERE
            st.success(f"Toggled {len(rows)} items")
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

    c1, c2, c3, c4 = st.columns(4)
    with c1: name = st.text_input("Item Name", key="s_name")
    with c2: cab = st.selectbox("Cabinet", ["All"] + cabinets, key="s_cab")
    with c3: drw = st.selectbox("Drawer", ["All"] + drawers, key="s_drw")
    with c4: qty = st.number_input("Qty", min_value=0, value=0, key="s_qty")

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
            st.write(f"**{len(df)} item(s)**")
            for _, r in df.iterrows():
                with st.expander(f"{r['item']} @ {r['location']} — Qty: {r['quantity']}"):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        notes = st.text_area("Notes", value=r['notes'] or "", key=f"n_{r['id']}")
                        if st.button("Save", key=f"sv_{r['id']}"):
                            cur.execute("UPDATE inventory SET notes=? WHERE rowid=?", (notes.strip(), r['id']))
                            conn.commit()
                            upload_db()  # ← MUST BE HERE
                            st.success("Saved")
                            st.rerun()
                    act = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"a_{r['id']}")
                    usr = st.text_input("User", key=f"u_{r['id']}")
                    q_val = st.number_input("Qty", min_value=1, value=1, key=f"q_{r['id']}")

                    if st.button("Submit", key=f"sub_{r['id']}") and act != "None" and usr.strip():
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cur.execute("INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?, ?, ?, ?, ?)",
                                    (r['item'], act, usr.strip(), ts, q_val))
                        new_qty = r['quantity'] - q_val if act == "Check Out" else r['quantity'] + q_val
                        cur.execute("UPDATE inventory SET quantity=? WHERE rowid=?", (max(0, new_qty), r['id']))
                        conn.commit()
                        upload_db()  # ← MUST BE HERE
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
        st.dataframe(df_tx[['timestamp', 'action', 'qty', 'item', 'user']], width="stretch")

# =============================================
# REPORTS TAB
# =============================================
with tab_rep:
    st.subheader("Full Report")
    df = pd.read_sql_query("SELECT location, item, quantity, notes FROM inventory ORDER BY location", conn)
    if df.empty:
        st.info("No items.")
    else:
        st.dataframe(df, width="stretch")
        csv = df.to_csv(index=False).encode()
        st.download_button("Download CSV", csv, f"report_{datetime.now():%Y%m%d}.csv", "text/csv")
