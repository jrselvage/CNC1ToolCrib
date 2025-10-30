import streamlit as st
import sqlite3
import pandas as pd
import fitz
from datetime import datetime, timedelta
import io
import re
import os
import subprocess

# ------------------- SECRETS (MUST BE IN STREAMLIT CLOUD) -------------------
# Settings → Secrets:
# GITHUB_TOKEN = "github_pat_..."
# REPO = "jrselvage/CNC1ToolCrib"
# BRANCH = "main"

# ------------------- GITHUB SYNC FUNCTIONS -------------------
def run_git(cmd):
    """Run git command with error handling"""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        st.toast(f"Git error: {result.stderr}")
    return result

def git_pull():
    """Pull latest DB from GitHub"""
    if not os.path.exists(".git"):
        return
    try:
        run_git(["git", "fetch", "origin"])
        run_git(["git", "reset", "--hard", f"origin/{st.secrets['BRANCH']}"])
        run_git(["git", "clean", "-fd"])
    except:
        pass

def git_push():
    """Push DB to GitHub"""
    try:
        # Configure
        run_git(["git", "config", "user.email", "streamlit@app.com"])
        run_git(["git", "config", "user.name", "Streamlit App"])

        # Remote
        token = st.secrets["GITHUB_TOKEN"]
        repo = st.secrets["REPO"]
        branch = st.secrets["BRANCH"]
        url = f"https://{token}@github.com/{repo}.git"
        run_git(["git", "remote", "set-url", "origin", url])

        # Add DB
        run_git(["git", "add", "inventory.db"])

        # Commit
        msg = f"Auto-save: {datetime.now():%Y-%m-%d %H:%M:%S}"
        result = run_git(["git", "commit", "-m", msg])
        if "nothing to commit" in result.stdout.lower():
            return

        # Push (force if needed)
        push = run_git(["git", "push", "origin", f"HEAD:{branch}", "--force"])
        if push.returncode == 0:
            st.toast("DB saved to GitHub")
        else:
            st.toast("Push failed")
    except Exception as e:
        st.toast(f"Git error: {e}")

# ------------------- PULL ON START -------------------
git_pull()

# ------------------- INIT GIT IF MISSING -------------------
if not os.path.exists(".git"):
    run_git(["git", "init"])
    run_git(["git", "checkout", "-b", st.secrets["BRANCH"]])

# ------------------- DATABASE -------------------
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
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='inventory'")
if not cursor.fetchone():
    cursor.execute("CREATE TABLE inventory (location TEXT, item TEXT, notes TEXT, quantity INTEGER)")
    cursor.execute("CREATE TABLE transactions (item TEXT, action TEXT, user TEXT, timestamp TEXT, qty INTEGER)")
    for idx in [
        "CREATE INDEX IF NOT EXISTS idx_location ON inventory(location)",
        "CREATE INDEX IF NOT EXISTS idx_item ON inventory(item)",
        "CREATE INDEX IF NOT EXISTS idx_tx_item ON transactions(item)",
        "CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)"
    ]:
        cursor.execute(idx)
    conn.commit()
    git_push()

# ------------------- UI -------------------
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory Management System")

# DEBUG
col1, col2 = st.columns(2)
with col1:
    if st.button("CHECK DB"):
        size = os.path.getsize(DB_PATH)
        items = pd.read_sql_query("SELECT COUNT(*) FROM inventory", conn).iloc[0,0]
        txs = pd.read_sql_query("SELECT COUNT(*) FROM transactions", conn).iloc[0,0]
        st.success(f"{size:,} bytes | {items} items | {txs} txs")
with col2:
    with open(DB_PATH, "rb") as f:
        st.download_button("DOWNLOAD DB", f, "inventory.db", "application/octet-stream")

# ------------------- ADD ITEM -------------------
st.sidebar.header("Add Item")
with st.sidebar.form("add_form", clear_on_submit=True):
    new_item = st.text_input("Item Name", key="add_name")
    new_loc = st.text_input("Location", key="add_loc").strip().upper()
    new_qty = st.number_input("Qty", min_value=0, step=1, value=0, key="add_qty")
    new_notes = st.text_area("Notes", key="add_notes")
    if st.form_submit_button("Add") and new_item and new_loc:
        cursor.execute("INSERT INTO inventory VALUES (?, ?, ?, ?)", (new_loc, new_item, new_notes, new_qty))
        conn.commit()
        git_push()
        st.cache_data.clear()
        st.success("Added")
        st.rerun()

# ------------------- TABS -------------------
tab1, tab2, tab3 = st.tabs(["Inventory", "Transactions", "Reports"])

# ------------------- INVENTORY TAB -------------------
with tab1:
    st.subheader("Search")
    c1, c2, c3, c4 = st.columns(4)
    with c1: name = st.text_input("Item", key="s_name")
    with c2: cab = st.selectbox("Cabinet", ["All"] + [str(i) for i in range(1, 200)], key="s_cab")
    with c3: drw = st.selectbox("Drawer", ["All"] + ["A","B","C","D"], key="s_drw")
    with c4: qty = st.number_input("Qty", min_value=0, value=0, key="s_qty")

    @st.cache_data(ttl=60)
    def load_inv(n="", c="All", d="All", q=0):
        qy = "SELECT rowid AS id, * FROM inventory WHERE 1=1"
        p = []
        if n: qy += " AND item LIKE ?"; p.append(f"%{n}%")
        if c != "All" and d != "All": qy += " AND location = ?"; p.append(f"{c}{d}")
        elif c != "All": qy += " AND location LIKE ?"; p.append(f"{c}%")
        elif d != "All": qy += " AND location LIKE ?"; p.append(f"%{d}")
        if q > 0: qy += " AND quantity = ?"; p.append(q)
        return pd.read_sql_query(qy, conn, params=p)

    df = load_inv(name, cab, drw, qty)
    if df.empty:
        st.info("No items")
    else:
        for _, r in df.iterrows():
            with st.expander(f"{r['item']} @ {r['location']} — {r['quantity']}"):
                n = st.text_area("Notes", r['notes'] or "", key=f"n_{r['id']}", height=70)
                if st.button("Save", key=f"s_{r['id']}"):
                    cursor.execute("UPDATE inventory SET notes=? WHERE rowid=?", (n, r['id']))
                    conn.commit()
                    git_push()
                    st.cache_data.clear()
                    st.rerun()

                a = st.selectbox("Action", ["None", "Out", "In"], key=f"a_{r['id']}")
                u = st.text_input("Name", key=f"u_{r['id']}")
                q = st.number_input("Qty", min_value=1, value=1, key=f"q_{r['id']}")

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Go", key=f"go_{r['id']}") and a != "None" and u:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cursor.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?)", (r['item'], a, u, ts, q))
                        new_q = r['quantity'] - q if a == "Out" else r['quantity'] + q
                        cursor.execute("UPDATE inventory SET quantity=? WHERE rowid=?", (max(0, new_q), r['id']))
                        conn.commit()
                        git_push()
                        st.cache_data.clear()
                        st.rerun()
                with c2:
                    if st.button("Delete", key=f"del_{r['id']}") and u:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cursor.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?)", (r['item'], "Deleted", u, ts, r['quantity']))
                        cursor.execute("DELETE FROM inventory WHERE rowid=?", (r['id'],))
                        conn.commit()
                        git_push()
                        st.cache_data.clear()
                        st.rerun()

# ------------------- TRANSACTIONS TAB -------------------
with tab2:
    st.subheader("History")
    c1, c2, c3, c4 = st.columns(4)
    with c1: ti = st.text_input("Item", key="t_item")
    with c2: tu = st.text_input("User", key="t_user")
    with c3: ta = st.selectbox("Action", ["All", "Out", "In", "Deleted"], key="t_act")
    with c4: tq = st.number_input("Qty", min_value=0, value=0, key="t_qty")

    start = st.date_input("From", value=datetime(2020,1,1), key="t_start")
    end = st.date_input("To", value=datetime.today().date(), key="t_end")
    s_str = start.strftime("%Y-%m-%d 00:00:00")
    e_str = (end + timedelta(days=1) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

    @st.cache_data(ttl=60)
    def load_tx(i="", u="", a="All", q=0, s="", e=""):
        qy = "SELECT * FROM transactions WHERE timestamp BETWEEN ? AND ?"
        p = [s, e]
        if i: qy += " AND item LIKE ?"; p.append(f"%{i}%")
        if u: qy += " AND user LIKE ?"; p.append(f"%{u}%")
        if a != "All": qy += " AND action = ?"; p.append(a)
        if q > 0: qy += " AND qty = ?"; p.append(q)
        qy += " ORDER BY timestamp DESC LIMIT 1000"
        return pd.read_sql_query(qy, conn, params=p)

    df_tx = load_tx(ti, tu, ta, tq, s_str, e_str)
    if df_tx.empty:
        st.info("No transactions")
    else:
        st.dataframe(df_tx[['timestamp', 'action', 'qty', 'item', 'user']], use_container_width=True, hide_index=True)

# ------------------- REPORTS TAB -------------------
with tab3:
    st.subheader("Report")
    with st.form("report"):
        prefix = st.selectbox("Prefix", ["All"] + [f"{i:02d}" for i in range(1, 20)], key="r_prefix")
        zero = st.checkbox("Zero only", key="r_zero")
        r_start = st.date_input("Start", value=datetime(2020,1,1), key="r_start")
        r_end = st.date_input("End", value=datetime.today().date(), key="r_end")
        if st.form_submit_button("Generate"):
            s = r_start.strftime("%Y-%m-%d 00:00:00")
            e = (r_end + timedelta(days=1) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
            q = "SELECT * FROM inventory WHERE 1=1"
            p = []
            if prefix != "All": q += " AND location LIKE ?"; p.append(f"{prefix}%")
            if zero: q += " AND quantity = 0"
            df = pd.read_sql_query(q, conn, params=p)
            if df.empty:
                st.warning("No data")
            else:
                st.dataframe(df)
                buf = io.BytesIO()
                doc = fitz.open()
                page = doc.new_page()
                page.insert_text((50,50), df.to_string(index=False), fontsize=9)
                doc.save(buf)
                doc.close()
                st.download_button("PDF", buf.getvalue(), f"report_{datetime.now():%Y%m%d}.pdf", "application/pdf")
