import streamlit as st
import pandas as pd
import re
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

# =============================================
# SUPABASE CONNECTION — HARDCODED IP (NO DNS)
# =============================================
@st.cache_resource
def get_connection():
    try:
        host = st.secrets["supabase"]["host"]  # Hardcoded IP from nslookup
        st.info(f"Connecting to Supabase IP: {host}:5432...")
        
        conn = psycopg2.connect(
            host=host,
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
        st.warning("Check your Supabase IP (from nslookup) and password.")
        st.stop()

# =============================================
# CONNECT TO DATABASE
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
# ADD NEW ITEM (SIDEBAR)
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
            st.error("Item name and location are required.")
        else:
            clean_loc = re.sub(r'[^0-9A-Z]', '', new_loc)
            if not re.match(r'^\d{1,3}[A-Z]$', clean_loc):
                st.error("Invalid location format. Use: 1A, 12B, 999Z")
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
# REFRESH BUTTON
# =============================================
if st.sidebar.button("Refresh Data"):
    st.cache_resource.clear()
    st.rerun()

# =============================================
# TABS: INVENTORY, TRANSACTIONS, REPORTS
# =============================================
tab_inv, tab_tx, tab_rep = st.tabs(["Inventory", "Transactions", "Reports"])

# ————————————————————————
# TAB 1: INVENTORY
# ————————————————————————
with tab_inv:
    st.subheader("Search Inventory")
    c1, c2 = st.columns(2)
    with c1:
        name_filter = st.text_input("Item Name", key="inv_name")
    with c2:
        loc_filter = st.text_input("Location", key="inv_loc")

    # Build query
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
        st.error("Failed to load inventory")
        st.code(e)
        df = pd.DataFrame()

    if df.empty:
        st.info("No items found.")
    else:
        st.write(f"**{len(df)} item(s) found**")
        for _, row in df.iterrows():
            with st.expander(f"{row['item']} @ {row['location']} — Qty: {row['quantity']}"):
                col1, col2 = st.columns([3, 1])

                with col1:
                    notes = st.text_area(
                        "Notes", 
                        value=row['notes'] or "", 
                        key=f"notes_{row['id']}",
                        height=100
                    )
                    if st.button("Save Notes", key=f"save_{row['id']}"):
                        cur.execute(
                            "UPDATE inventory SET notes = %s WHERE id = %s",
                            (notes, row['id'])
                        )
                        conn.commit()
                        st.success("Notes saved!")
                        st.rerun()

                with col2:
                    action = st.selectbox(
                        "Action", 
                        ["None", "Check Out", "Check In"], 
                        key=f"act_{row['id']}"
                    )
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
                                    """INSERT INTO transactions 
                                    (item, action, user, timestamp, qty) 
                                    VALUES (%s, %s, %s, %s, %s)""",
                                    (row['item'], action, user.strip(), ts, qty)
                                )
                                new_qty = row['quantity'] - qty if action == "Check Out" else row['quantity'] + qty
                                cur.execute(
                                    "UPDATE inventory SET quantity = %s WHERE id = %s",
                                    (max(0, new_qty), row['id'])
                                )
                                conn.commit()
                                st.success(f"{action}: {qty} × {row['item']}")
                                st.rerun()
                            except Exception as e:
                                st.error("Transaction failed")
                                st.code(e)

# ————————————————————————
# TAB 2: TRANSACTIONS
# ————————————————————————
with tab_tx:
    st.subheader("Recent Transactions")
    try:
        df_tx = pd.read_sql(
            "SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 100", 
            conn
        )
        if not df_tx.empty:
            df_display = df_tx[['timestamp', 'action', 'qty', 'item', 'user']].copy()
            df_display['timestamp'] = pd.to_datetime(df_display['timestamp']).dt.strftime('%Y-%m-%d %H:%M')
            st.dataframe(df_display, use_container_width=True)
        else:
            st.info("No transactions yet.")
    except Exception as e:
        st.error("Failed to load transactions")
        st.code(e)

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
            file_name=f"tool_crib_inventory_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    except Exception as e:
        st.error("Failed to generate report")
        st.code(e)
