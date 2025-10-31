import streamlit as st
import pandas as pd
import re
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import socket
import time

# =============================================
# SUPABASE CONNECTION — IPv6 PRIMARY + IPv4 FALLBACK + RETRIES
# =============================================
@st.cache_resource(ttl=300)  # Cache 5 min
def get_connection():
    password = st.secrets["supabase"]["password"]
    primary_host = st.secrets["supabase"]["host"]  # IPv6: 2600:1f16:1cd0:333f:9551:240c:8a4d:f52d
    domain = "db.jpzhwolmzrxnkaxbvbqj.supabase.co"

    def try_connect(host, attempts=3):
        for i in range(attempts):
            try:
                st.info(f"🔄 Connecting to {host}:5432 (attempt {i+1}/{attempts})...")
                conn = psycopg2.connect(
                    host=host,
                    port=5432,
                    user="postgres",
                    password=password,
                    database="postgres",
                    sslmode="require",
                    connect_timeout=15,  # Increased timeout
                    keepalives=1,
                    keepalives_idle=30
                )
                # Quick test query
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                st.success(f"✅ SUPABASE CONNECTED! ({host})")
                st.balloons()
                return conn
            except Exception as e:
                st.warning(f"Attempt {i+1} failed: {e}")
                if i < attempts - 1:
                    time.sleep(2)  # Wait before retry
                continue
        return None

    # ATTEMPT 1: Primary (your IPv6)
    st.info("🚀 Primary: IPv6 Hardcoded")
    conn = try_connect(primary_host)
    if conn:
        return conn

    # ATTEMPT 2: Fallback to IPv4 resolution
    st.info("🔄 Fallback: Resolve IPv4 from DNS")
    try:
        resolved_ip = socket.getaddrinfo(domain, 5432, family=socket.AF_INET)[0][4][0]
        st.code(f"Resolved IPv4: {resolved_ip}")
        conn = try_connect(resolved_ip)
        if conn:
            return conn
    except Exception as e:
        st.warning(f"IPv4 resolution failed: {e}")

    # FINAL ERROR
    st.error("❌ ALL CONNECTIONS FAILED")
    st.warning("💡 IMMEDIATE FIXES:\n"
               "1. Verify password in Supabase Dashboard → Settings → Database.\n"
               "2. Check project status (not paused/billed).\n"
               "3. Run locally: `psql 'host=2600:1f16:1cd0:333f:9551:240c:8a4d:f52d port=5432 dbname=postgres user=postgres password=surgeprotection sslmode=require' -c 'SELECT 1;'`\n"
               "4. If IPv6 fails locally, reply with output — we'll switch to Supabase SDK.")
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
# ADD NEW ITEM
# =============================================
st.sidebar.header("Add New Item")
with st.sidebar.form("add_form", clear_on_submit=True):
    new_item = st.text_input("Item Name")
    new_loc = st.text_input("Location (e.g., 5A)").strip().upper()
    new_qty = st.number_input("Quantity", min_value=0, value=0, step=1)
    new_notes = st.text_area("Notes")
    add = st.form_submit_button("Add Item")

    if add:
        if not new_item or not new_loc:
            st.error("Item name and location required.")
        else:
            clean_loc = re.sub(r'[^0-9A-Z]', '', new_loc)
            if not re.match(r'^\d{1,3}[A-Z]$', clean_loc):
                st.error("Invalid location. Use: 1A, 12B, 999Z")
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
                    st.code(str(e))

# =============================================
# REFRESH
# =============================================
if st.sidebar.button("🔄 Refresh Connection & Data"):
    st.cache_resource.clear()
    st.rerun()

# =============================================
# TABS
# =============================================
tab_inv, tab_tx, tab_rep = st.tabs(["Inventory", "Transactions", "Reports"])

# ————————————————————————
# TAB 1: INVENTORY
# ————————————————————————
with tab_inv:
    st.subheader("Search Inventory")
    c1, c2 = st.columns(2)
    with c1: name_filter = st.text_input("Item Name", key="inv_name")
    with c2: loc_filter = st.text_input("Location", key="inv_loc")

    query = "SELECT * FROM inventory WHERE 1=1"
    params = []
    if name_filter:
        query += " AND item ILIKE %s"
        params.append(f"%{name_filter}%")
    if loc_filter:
        query += " AND location ILIKE %s"
        params.append(f"%{loc_filter}%")
    query += " ORDER BY location"

    try:
        df = pd.read_sql(query, conn, params=params)
    except Exception as e:
        st.error("Query failed")
        st.code(str(e))
        df = pd.DataFrame()

    if df.empty:
        st.info("No items found.")
    else:
        st.write(f"**{len(df)} item(s) found**")
        for _, row in df.iterrows():
            with st.expander(f"{row['item']} @ {row['location']} — Qty: {row['quantity']}"):
                col1, col2 = st.columns([3, 1])

                with col1:
                    notes = st.text_area("Notes", value=row['notes'] or "", key=f"notes_{row['id']}", height=100)
                    if st.button("Save Notes", key=f"save_{row['id']}"):
                        cur.execute("UPDATE inventory SET notes = %s WHERE id = %s", (notes, row['id']))
                        conn.commit()
                        st.success("Notes saved!")
                        st.rerun()

                with col2:
                    action = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"act_{row['id']}")
                    user = st.text_input("User", key=f"user_{row['id']}")
                    qty = st.number_input("Qty", min_value=1, value=1, key=f"qty_{row['id']}")

                    if st.button("Submit", key=f"submit_{row['id']}"):
                        if action == "None":
                            st.warning("Select an action.")
                        elif not user.strip():
                            st.warning("Enter your name.")
                        else:
                            try:
                                ts = datetime.now()
                                cur.execute(
                                    "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (%s, %s, %s, %s, %s)",
                                    (row['item'], action, user.strip(), ts, qty)
                                )
                                new_qty = row['quantity'] - qty if action == "Check Out" else row['quantity'] + qty
                                cur.execute("UPDATE inventory SET quantity = %s WHERE id = %s", (max(0, new_qty), row['id']))
                                conn.commit()
                                st.success(f"{action}: {qty} × {row['item']}")
                                st.rerun()
                            except Exception as e:
                                st.error("Transaction failed")
                                st.code(str(e))

# ————————————————————————
# TAB 2: TRANSACTIONS
# ————————————————————————
with tab_tx:
    st.subheader("Recent Transactions")
    try:
        df_tx = pd.read_sql("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 100", conn)
        if not df_tx.empty:
            df_display = df_tx[['timestamp', 'action', 'qty', 'item', 'user']].copy()
            df_display['timestamp'] = pd.to_datetime(df_display['timestamp']).dt.strftime('%Y-%m-%d %H:%M')
            st.dataframe(df_display, use_container_width=True)
        else:
            st.info("No transactions yet.")
    except Exception as e:
        st.error("Load failed")
        st.code(str(e))

# ————————————————————————
# TAB 3: REPORTS
# ————————————————————————
with tab_rep:
    st.subheader("Full Inventory Report")
    try:
        df_report = pd.read_sql("SELECT * FROM inventory ORDER BY location", conn)
        st.dataframe(df_report, use_container_width=True)
        csv = df_report.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download CSV Report",
            data=csv,
            file_name=f"tool_crib_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    except Exception as e:
        st.error("Report failed")
        st.code(str(e))
