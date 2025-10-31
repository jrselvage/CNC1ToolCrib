import streamlit as st
import pandas as pd
import re
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

# =============================================
# SUPABASE CONNECTION
# =============================================
@st.cache_resource
def get_connection():
    conn = psycopg2.connect(st.secrets["supabase"]["url"])
    return conn

conn = get_connection()
cur = conn.cursor(cursor_factory=RealDictCursor)

# =============================================
# UI
# =============================================
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory System")
st.sidebar.success("Supabase: ACTIVE")

# Add Item
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
                "INSERT INTO inventory (location, item, notes, quantity) VALUES (%s, %s, %s, %s)",
                (clean_loc, new_item.strip(), new_notes.strip(), int(new_qty))
            )
            conn.commit()
            st.success(f"Added {new_item}")
            st.rerun()

# Force Sync (not needed with Supabase)
st.sidebar.button("Force Sync", disabled=True, help="Not needed with Supabase")

# Download Report
st.sidebar.markdown("---")
st.sidebar.subheader("Reports")
if st.sidebar.button("Download Full CSV"):
    df = pd.read_sql("SELECT * FROM inventory ORDER BY location", conn)
    csv = df.to_csv(index=False).encode()
    st.sidebar.download_button("Download CSV", csv, "inventory.csv", "text/csv")

# Tabs
tab_inv, tab_tx, tab_rep = st.tabs(["Inventory", "Transactions", "Reports"])

with tab_inv:
    st.subheader("Search Inventory")
    c1, c2 = st.columns(2)
    with c1: name = st.text_input("Item Name")
    with c2: loc = st.text_input("Location")

    q = "SELECT * FROM inventory WHERE 1=1"
    params = []
    if name: q += " AND item ILIKE %s"; params.append(f"%{name}%")
    if loc: q += " AND location ILIKE %s"; params.append(f"%{loc}%")
    q += " ORDER BY location, item"

    df = pd.read_sql(q, conn, params=params)
    if df.empty:
        st.info("No items found.")
    else:
        st.write(f"**{len(df)} item(s) found**")
        for _, r in df.iterrows():
            with st.expander(f"{r['item']} @ {r['location']} — Qty: {r['quantity']}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    notes = st.text_area("Notes", value=r['notes'] or "", key=f"notes_{r['id']}")
                    if st.button("Save Notes", key=f"save_{r['id']}"):
                        cur.execute("UPDATE inventory SET notes = %s WHERE id = %s", (notes.strip(), r['id']))
                        conn.commit()
                        st.success("Notes saved")
                        st.rerun()
                with col2:
                    act = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"act_{r['id']}")
                    usr = st.text_input("User", key=f"user_{r['id']}")
                    qty = st.number_input("Qty", min_value=1, value=1, key=f"qty_{r['id']}")
                    if st.button("Submit", key=f"submit_{r['id']}") and act != "None" and usr.strip():
                        ts = datetime.now()
                        cur.execute(
                            "INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (%s, %s, %s, %s, %s)",
                            (r['item'], act, usr.strip(), ts, qty)
                        )
                        new_qty = r['quantity'] - qty if act == "Check Out" else r['quantity'] + qty
                        cur.execute("UPDATE inventory SET quantity = %s WHERE id = %s", (max(0, new_qty), r['id']))
                        conn.commit()
                        st.success(f"{act}: {qty}")
                        st.rerun()

with tab_tx:
    st.subheader("Recent Transactions")
    df_tx = pd.read_sql("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 100", conn)
    if df_tx.empty:
        st.info("No transactions yet.")
    else:
        st.dataframe(df_tx, width="stretch")

with tab_rep:
    st.subheader("Full Report")
    df = pd.read_sql("SELECT * FROM inventory ORDER BY location", conn)
    if df.empty:
        st.info("No items.")
    else:
        st.dataframe(df, width="stretch")
        csv = df.to_csv(index=False).encode()
        st.download_button("Download CSV", csv, f"report_{datetime.now():%Y%m%d}.csv", "text/csv")
