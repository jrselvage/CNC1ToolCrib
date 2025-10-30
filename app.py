import streamlit as st
import sqlite3
import pandas as pd
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
#  HELPERS – cabinets / drawers
# -------------------------------------------------
@st.cache_data(ttl=300)
def get_cabinets():
    df = pd.read_sql_query("""SELECT DISTINCT SUBSTR(location,1,3) AS cab
                               FROM inventory WHERE location GLOB '[0-9][0-9][0-9]*'""", conn)
    return sorted(df['cab'].dropna().unique(), key=int)

@st.cache_data(ttl=300)
def get_drawers():
    df = pd.read_sql_query("""SELECT DISTINCT UPPER(SUBSTR(location,4)) AS drw
                               FROM inventory WHERE location GLOB '*[A-Za-z]'""", conn)
    return sorted(df['drw'].dropna().unique().tolist())

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
        cur.execute("INSERT INTO inventory (location, item, notes, quantity) VALUES (?,?,?,?)",
                    (new_loc, new_item.strip(), new_notes.strip(), int(new_qty)))
        conn.commit()
        st.success(f"Added {new_item}")
        st.rerun()

# -------------------------------------------------
#  SIDEBAR – RESTORE FROM CSV (FIXED COLUMN COUNT)
# -------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Restore from CSV")
st.sidebar.caption("Save **Inventory** and **Transactions** as **CSV UTF-8** from Excel. Extra columns are ignored.")

inv_csv = st.sidebar.file_uploader("Inventory CSV", type=["csv"], key="inv_csv")
tx_csv  = st.sidebar.file_uploader("Transactions CSV", type=["csv"], key="tx_csv")

if inv_csv and tx_csv:
    if st.sidebar.button("Restore Database from CSV", type="primary"):
        with st.spinner("Restoring..."):
            try:
                # Read CSVs
                inv = pd.read_csv(inv_csv).fillna("")
                tx  = pd.read_csv(tx_csv).fillna("")

                # Expected columns
                inv_cols = ["location", "item", "notes", "quantity"]
                tx_cols  = ["item", "action", "user", "timestamp", "qty"]

                # Keep only known columns (ignore extras like 'id')
                inv = inv[[c for c in inv_cols if c in inv.columns]]
                tx  = tx[[c for c in tx_cols if c in tx.columns]]

                # Validate minimum required
                if len(inv.columns) < 4:
                    st.error("Inventory CSV must have: location, item, notes, quantity")
                    st.stop()
                if len(tx.columns) < 5:
                    st.error("Transactions CSV must have: item, action, user, timestamp, qty")
                    st.stop()

                # Clear DB
                cur.execute("DELETE FROM inventory")
                cur.execute("DELETE FROM transactions")

                # Insert inventory – explicit columns
                for _, r in inv.iterrows():
                    cur.execute(
                        "INSERT INTO inventory (location, item, notes, quantity) VALUES (?,?,?,?)",
                        (r['location'], r['item'], r['notes'], int(r['quantity']))
                    )

                # Insert transactions – explicit columns
                for _, r in tx.iterrows():
                    cur.execute(
                        "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?,?,?,?,?)",
                        (r['item'], r['action'], r['user'], r['timestamp'], int(r['qty']))
                    )

                conn.commit()
                st.success("Database restored from CSV!")
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
#  INVENTORY TAB
# -------------------------------------------------
with tab_inv:
    st.subheader("Search Inventory")
    cabs = get_cabinets()
    drws = get_drawers()

    c1,c2,c3,c4 = st.columns(4)
    with c1: name = st.text_input("Item Name",key="s_name")
    with c2: cab  = st.selectbox("Cabinet #",["All"]+cabs,key="s_cab")
    with c3: drw  = st.selectbox("Drawer",["All"]+drws,key="s_drw")
    with c4: qty  = st.number_input("Exact Qty",min_value=0,value=0,key="s_qty")

    has_filter = name or (cab!="All") or (drw!="All") or (qty>0)

    if not has_filter:
        st.info("Pick a filter to start.")
    else:
        @st.cache_data(ttl=60)
        def search(name="",cab="All",drw="All",qty=0):
            q = "SELECT rowid AS id, location, item, notes, quantity FROM inventory WHERE 1=1"
            p = []
            if name: q += " AND item LIKE ?"; p.append(f"%{name}%")
            if cab!="All" and drw!="All": q += " AND location = ?"; p.append(f"{cab}{drw}")
            elif cab!="All": q += " AND location LIKE ?"; p.append(f"{cab}%")
            elif drw!="All": q += " AND location LIKE ?"; p.append(f"%{drw}")
            if qty>0: q += " AND quantity = ?"; p.append(qty)
            q += " ORDER BY location, item"
            return pd.read_sql_query(q, conn, params=p)

        df = search(name, cab, drw, qty)

        if df.empty:
            st.warning("No items.")
        else:
            st.write(f"**{len(df)} item(s) found**")
            for _,r in df.iterrows():
                with st.expander(f"{r['item']} @ {r['location']} — Qty: {r['quantity']}"):
                    col1,col2 = st.columns([3,1])
                    with col1:
                        notes = st.text_area("Notes",value=r['notes'] or "",key=f"n_{r['id']}",height=70)
                        if st.button("Save Notes",key=f"sv_{r['id']}"):
                            cur.execute("UPDATE inventory SET notes=? WHERE rowid=?",(notes.strip(),r['id']))
                            conn.commit()
                            st.success("Saved")
                            st.rerun()
                    act = st.selectbox("Action",["None","Check Out","Check In"],key=f"a_{r['id']}")
                    usr = st.text_input("Your Name",key=f"u_{r['id']}")
                    q   = st.number_input("Qty",min_value=1,value=1,key=f"q_{r['id']}")

                    bc1,bc2 = st.columns(2)
                    with bc1:
                        if st.button("Submit",key=f"sub_{r['id']}") and act!="None" and usr.strip():
                            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            cur.execute("INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?,?,?,?,?)",
                                        (r['item'],act,usr.strip(),ts,q))
                            new_q = r['quantity']-q if act=="Check Out" else r['quantity']+q
                            cur.execute("UPDATE inventory SET quantity=? WHERE rowid=?",(max(0,new_q),r['id']))
                            conn.commit()
                            st.success(f"{act}: {q}")
                            st.rerun()
                    with bc2:
                        if st.button("Delete",key=f"del_{r['id']}") and usr.strip():
                            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            cur.execute("INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?,?,?,?,?)",
                                        (r['item'],"Deleted",usr.strip(),ts,r['quantity']))
                            cur.execute("DELETE FROM inventory WHERE rowid=?",(r['id'],))
                            conn.commit()
                            st.warning("Deleted")
                            st.rerun()

# -------------------------------------------------
#  TRANSACTIONS TAB + CSV EXPORT
# -------------------------------------------------
with tab_tx:
    st.subheader("Transaction History")
    c1,c2,c3,c4 = st.columns(4)
    with c1: t_item = st.text_input("Item",key="t_item")
    with c2: t_user = st.text_input("User",key="t_user")
    with c3: t_act  = st.selectbox("Action",["All","Check Out","Check In","Deleted"],key="t_act")
    with c4: t_qty  = st.number_input("Qty",min_value=0,value=0,key="t_qty")

    s_date = st.date_input("From",value=datetime(2020,1,1),key="t_start")
    e_date = st.date_input("To",value=datetime.today(),key="t_end")
    s_str = s_date.strftime("%Y-%m-%d 00:00:00")
    e_str = (e_date + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

    @st.cache_data(ttl=60)
    def load_tx(item="",user="",action="All",qty=0,s="",e=""):
        q = "SELECT * FROM transactions WHERE timestamp BETWEEN ? AND ?"
        p = [s,e]
        if item: q += " AND item LIKE ?"; p.append(f"%{item}%")
        if user: q += " AND user LIKE ?"; p.append(f"%{user}%")
        if action!="All": q += " AND action = ?"; p.append(action)
        if qty>0: q += " AND qty = ?"; p.append(qty)
        q += " ORDER BY timestamp DESC LIMIT 1000"
        return pd.read_sql_query(q, conn, params=p)

    df_tx = load_tx(t_item, t_user, t_act, t_qty, s_str, e_str)

    if df_tx.empty:
        st.info("No transactions.")
    else:
        st.dataframe(df_tx[['timestamp','action','qty','item','user']],
                     use_container_width=True, hide_index=True)

        csv = df_tx.to_csv(index=False).encode()
        st.download_button(
            "Download Transactions (CSV)",
            csv,
            file_name=f"transactions_{datetime.now():%Y%m%d}.csv",
            mime="text/csv"
        )

# -------------------------------------------------
#  REPORTS TAB + CSV EXPORT
# -------------------------------------------------
with tab_rep:
    st.subheader("Generate Report")
    cabs_rep = get_cabinets()

    with st.form("rep_form"):
        pref = st.selectbox("Cabinet #",["All"]+cabs_rep,key="r_pref")
        cust = st.text_input("Custom Location Filter",key="r_cust")
        zero = st.checkbox("Zero quantity only",key="r_zero")
        r_start = st.date_input("Start Date",value=datetime(2020,1,1),key="r_start")
        r_end   = st.date_input("End Date",value=datetime.today(),key="r_end")
        gen = st.form_submit_button("Generate")

    if gen:
        @st.cache_data
        def build_report(pfx,cust,zero,s,e):
            q = "SELECT location, item, quantity, notes FROM inventory WHERE 1=1"
            p = []
            if pfx!="All": q += " AND location LIKE ?"; p.append(f"{pfx}%")
            if cust:       q += " AND location LIKE ?"; p.append(f"%{cust}%")
            if zero:       q += " AND quantity = 0"
            df = pd.read_sql_query(q, conn, params=p)

            tx_q = """SELECT item, MAX(timestamp) as last_tx
                      FROM transactions
                      WHERE timestamp BETWEEN ? AND ?
                      GROUP BY item"""
            s_str = s.strftime("%Y-%m-%d 00:00:00")
            e_str = e.strftime("%Y-%m-%d 23:59:59")
            last = pd.read_sql_query(tx_q, conn, params=[s_str,e_str])
            df = df.merge(last, on='item', how='left')
            return df

        df_r = build_report(pref, cust, zero, r_start, r_end)

        if df_r.empty:
            st.warning("No data.")
        else:
            st.write("### Preview")
            st.dataframe(df_r, use_container_width=True)

            csv = df_r.to_csv(index=False).encode()
            st.download_button(
                "Download Report (CSV)",
                csv,
                file_name=f"report_{datetime.now():%Y%m%d}.csv",
                mime="text/csv"
            )
