import streamlit as st
import pandas as pd
import re
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import socket

# =============================================
# SUPABASE CONNECTION — FORCE IPv4
# =============================================
@st.cache_resource
def get_connection():
    try:
        st.info("Resolving IPv4 address...")
        host = st.secrets["supabase"]["host"]
        ipv4 = socket.getaddrinfo(host, 5432, family=socket.AF_INET)[0][4][0]
        st.code(f"Using IPv4: {ipv4}")

        st.info("Connecting to Supabase...")
        conn = psycopg2.connect(
            host=ipv4,
            port=5432,
            user="postgres",
            password=st.secrets["supabase"]["password"],
            database="postgres",
            sslmode="require"
        )
        st.success("SUPABASE CONNECTED!")
        st.balloons()
        return conn
    except Exception as e:
        st.error("Connection FAILED")
        st.code(f"Error: {e}")
        st.warning("Check password in Supabase → Settings → Database")
        st.stop()

# =============================================
# CONNECT
# =============================================
conn = get_connection()
cur = conn.cursor(cursor_factory=RealDictCursor)

# =============================================
# PAGE CONFIG
# =============================================
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory System")
st.sidebar.success("Supabase: LIVE")

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
            try:
                cur.execute(
                    "INSERT INTO inventory (location, item, notes, quantity) VALUES (%s, %s, %s, %s)",
                    (clean_loc, new_item.strip(), new_notes.strip(), int(new_qty))
                )
                conn.commit()
                st.success(f"Added: {new_item} @ {clean_loc}")
                st.rerun()
            except Exception as e:
                st.error("Add failed")
                st.code(e)

# =============================================
# REFRESH
# =============================================
if st.sidebar.button("Refresh Data"):
    st.cache_resource.clear()
    st.rerun()

# =============================================
# TABS
# =============================================
tab_inv, tab_tx, tab_rep = st.tabs(["Inventory", "Transactions", "Reports"])

with tab_inv:
    st.subheader("Search")
    c1, c2 = st.columns(2)
    with c1: name = st.text_input("Item")
    with c2: loc = st.text_input("Location")

    q = "SELECT * FROM inventory WHERE 1=1"
    p = []
    if name: q += " AND item ILIKE %s"; p.append(f"%{name}%")
    if loc: q += " AND location ILIKE %s"; p.append(f"%{loc}%")
    q += " ORDER BY location"

    try:
        df = pd.read_sql(q, conn, params=p)
    except Exception as e:
        st.error("Query failed")
        st.code(e)
        df = pd.DataFrame()

    if df.empty:
        st.info("No items.")
    else:
        st.write(f"**{len(df)} item(s)**")
        for _, r in df.iterrows():
            with st.expander(f"{r['item']} @ {r['location']} — Qty: {r['quantity']}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    notes = st.text_area("Notes", r['notes'] or "", key=f"n_{r['id']}")
                    if st.button("Save", key=f"s_{r['id']}"):
                        cur.execute("UPDATE inventory SET notes=%s WHERE id=%s", (notes, r['id']))
                        conn.commit()
                        st.rerun()
                with col2:
                    act = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"a_{r['id']}")
                    usr = st.text_input("User", key=f"u_{r['id']}")
                    qty = st.number_input("Qty", 1, key=f"q_{r['id']}")
                    if st.button("Submit", key=f"sub_{r['id']}") and act != "None" and usr:
                        ts = datetime.now()
                        cur.execute("INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (%s, %s, %s, %s, %s)",
                                    (r['item'], act, usr, ts, qty))
                        new_qty = r['quantity'] - qty if act == "Check Out" else r['quantity'] + qty
                        cur.execute("UPDATE inventory SET quantity=%s WHERE id=%s", (max(0, new_qty), r['id']))
                        conn.commit()
                        st.rerun()

with tab_tx:
    st.subheader("Transactions")
    try:
        df_tx = pd.read_sql("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 100", conn)
        st.dataframe(df_tx[['timestamp', 'action', 'qty', 'item', 'user']], width="stretch")
    except Exception as e:
        st.error("Load failed")
        st.code(e)

with tab_rep:
    st.subheader("Report")
    try:
        df = pd.read_sql("SELECT * FROM inventory ORDER BY location", conn)
        st.dataframe(df, width="stretch")
        csv = df.to_csv(index=False).encode()
        st.download_button("Download CSV", csv, "report.csv", "text/csv")
    except Exception as e:
        st.error("Report failed")
        st.code(e)
