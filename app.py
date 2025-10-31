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
# LOGGING
# =============================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
# CONFIG
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
        logger.error(f"[SYNC] Auth failed: {e}")
        st.error("Google Drive auth failed.")
        return None

# =============================================
# FORCE DOWNLOAD ON START
# =============================================
def download_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        st.sidebar.warning("Local DB deleted — pulling from Drive")
    try:
        service = get_drive_service()
        if not service:
            return False
        logger.info("[SYNC] Downloading DB...")
        request = service.files().get_media(fileId=DRIVE_FILE_ID)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        with st.spinner("Pulling latest DB..."):
            while not done:
                status, done = downloader.next_chunk()
        fh.seek(0)
        with open(DB_PATH, "wb") as f:
            f.write(fh.read())
        st.success("Database pulled from Google Drive")
        return True
    except Exception as e:
        logger.error(f"[SYNC] Download failed: {e}")
        st.error(f"Download failed: {e}")
        open(DB_PATH, "a").close()
        return False

# =============================================
# UPLOAD
# =============================================
def upload_db():
    st.sidebar.warning("DEBUG: upload_db() CALLED")
    try:
        service = get_drive_service()
        if not service:
            return
        media = MediaFileUpload(DB_PATH, mimetype="application/octet-stream")
        service.files().update(fileId=DRIVE_FILE_ID, media_body=media).execute()
        msg = f"Saved to Drive @ {datetime.now().strftime('%H:%M:%S')}"
        st.sidebar.success(msg)
        logger.info(f"[SYNC] {msg}")
    except Exception as e:
        st.sidebar.error(f"Upload failed: {e}")

# =============================================
# AUTO BACKUP
# =============================================
def run_auto_backup():
    schedule.every(BACKUP_INTERVAL_MINUTES).minutes.do(upload_db)
    while True:
        schedule.run_pending()
        time.sleep(30)

# =============================================
# STARTUP
# =============================================
if 'sync_started' not in st.session_state:
    download_db()
    thread = threading.Thread(target=run_auto_backup, daemon=True)
    thread.start()
    st.session_state.sync_started = True

# =============================================
# DB SETUP
# =============================================
@st.cache_resource
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

conn = get_connection()
cur = conn.cursor()

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
# UI
# =============================================
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory System")
st.sidebar.success("Cloud Sync: ACTIVE")

# =============================================
# ADD ITEM
# =============================================
st.sidebar.header("Add New Item")
with st.sidebar.form("add_form", clear_on_submit=True):
    new_item = st.text_input("Item Name")
    new_loc = st.text_input("Location (e.g., 5A)").strip().upper()
    new_qty = st.number_input("Quantity", min_value=0, value=0)
    new_notes = st.text_area("Notes")
    add = st.form_submit_button("Add Item")

    if add and new_item and new_loc:
        clean_loc = re.sub(r'[^0-9A-Z]', '', new_loc)
        if not re.match(r'^\d{1,3}[A-Z]$', clean_loc):
            st.error("Invalid location")
        else:
            cur.execute(
                "INSERT INTO inventory (location, item, notes, quantity) VALUES (?, ?, ?, ?)",
                (clean_loc, new_item.strip(), new_notes.strip(), int(new_qty))
            )
            conn.commit()
            st.success(f"Added {new_item}")
            upload_db()
            st.rerun()

# =============================================
# FORCE BACKUP
# =============================================
if st.sidebar.button("Force Backup Now"):
    upload_db()

# =============================================
# DOWNLOAD DB
# =============================================
with open(DB_PATH, "rb") as f:
    st.sidebar.download_button("Download DB", f.read(), f"inventory_{datetime.now():%Y%m%d}.db")

# =============================================
# TABS
# =============================================
tab_inv, tab_tx, tab_rep = st.tabs(["Inventory", "Transactions", "Reports"])

with tab_inv:
    st.subheader("Search")
    c1, c2 = st.columns(2)
    with c1: name = st.text_input("Item")
    with c2: loc = st.text_input("Location")

    q = "SELECT rowid AS id, location, item, notes, quantity FROM inventory WHERE 1=1"
    p = []
    if name: q += " AND item LIKE ?"; p.append(f"%{name}%")
    if loc: q += " AND location LIKE ?"; p.append(f"%{loc}%")
    q += " ORDER BY location"

    df = pd.read_sql_query(q, conn, params=p)
    if df.empty:
        st.info("No items.")
    else:
        for _, r in df.iterrows():
            with st.expander(f"{r['item']} @ {r['location']} — Qty: {r['quantity']}"):
                notes = st.text_area("Notes", r['notes'] or "", key=f"n_{r['id']}")
                if st.button("Save", key=f"s_{r['id']}"):
                    cur.execute("UPDATE inventory SET notes=? WHERE rowid=?", (notes, r['id']))
                    conn.commit()
                    upload_db()
                    st.rerun()
                act = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"a_{r['id']}")
                usr = st.text_input("User", key=f"u_{r['id']}")
                qty = st.number_input("Qty", 1, key=f"q_{r['id']}")
                if st.button("Submit", key=f"sub_{r['id']}") and act != "None" and usr:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                    cur.execute(
                        "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?, ?, ?, ?, ?)",
                        (r['item'], act, usr.strip(), ts, qty)
                    )
                    new_qty = r['quantity'] - qty if act == "Check Out" else r['quantity'] + qty
                    cur.execute("UPDATE inventory SET quantity=? WHERE rowid=?", (max(0, new_qty), r['id']))
                    conn.commit()
                    upload_db()
                    st.rerun()

with tab_tx:
    st.subheader("Transactions")
    df_tx = pd.read_sql_query("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 100", conn)
    st.dataframe(df_tx[['timestamp', 'action', 'qty', 'item', 'user']], width="stretch")

with tab_rep:
    st.subheader("Full Report")
    df = pd.read_sql_query("SELECT * FROM inventory ORDER BY location", conn)
    st.dataframe(df, width="stretch")
    csv = df.to_csv(index=False).encode()
    st.download_button("Download CSV", csv, "report.csv", "text/csv")
