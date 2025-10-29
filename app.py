import streamlit as st
import sqlite3
from datetime import datetime
from thefuzz import fuzz
import pandas as pd
import fitz  # PyMuPDF
import re
import os

os.system("streamlit run_app.py")

# Try using a network drive path first
network_db_path = r"Z:\Shared\CNC1 Tool Crib Inventory Database\inventory.db"  # UNC path
local_db_path = "inventory.db"

# Use network path if it exists, otherwise fallback to local
db_path = network_db_path if os.path.exists(network_db_path) else local_db_path

# Connect to the database

@st.cache_resource
def get_connection():
    return sqlite3.connect("inventory.db", check_same_thread=False)

conn = get_connection()
cursor = conn.cursor()


# Page configuration
st.set_page_config(page_title="CNC1 Tool Crib Inventory Manager", layout="wide")
st.title("📦 CNC1 Tool Crib Inventory Management System")
# ---------------- Sidebar: Add New Item ----------------
st.sidebar.header("➕ Add New Inventory Item")
with st.sidebar.form("add_item_form"):
    new_item = st.text_input("Item Name", key="add_item_name")
    new_location = st.text_input("Location (e.g., 105A)", key="add_item_location")
    new_quantity = st.number_input("Quantity", min_value=0, step=1, key="add_item_qty")
    new_notes = st.text_area("Notes", key="add_item_notes")
    submitted = st.form_submit_button("Add Item", key="add_item_submit")
    if submitted and new_item and new_location:
        cursor.execute("INSERT INTO inventory (location, item, notes, quantity) VALUES (?, ?, ?, ?)",
                       (new_location.strip().upper(), new_item.strip(), new_notes.strip(), int(new_quantity)))
        conn.commit()
        st.sidebar.success(f"Item '{new_item}' added to inventory.")

# ---------------- Tabs ----------------
tab_inventory, tab_transactions, tab_reports = st.tabs(["📋 Inventory", "📜 Transactions", "📊 Reports"])

# ---------------- Inventory Tab ----------------
with tab_inventory:
    st.subheader("Inventory Search & Actions")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        search_name = st.text_input("Item Name", key="inv_search_name")
    with col2:
        cabinet_filter = st.number_input("Cabinet Number", min_value=0, step=1, key="cabinet_filter")
    with col3:
        drawer_filter = st.text_input("Drawer Letter", key="drawer_filter")
    with col4:
        search_quantity = st.number_input("Quantity", min_value=0, step=1, key="inv_search_qty")

    # Build query dynamically
    query = "SELECT * FROM inventory"
    conditions = []
    params = []

    if search_name:
        conditions.append("item LIKE ?")
        params.append(f"%{search_name}%")
    if cabinet_filter > 0:
        conditions.append("location LIKE ?")
        params.append(f"{cabinet_filter}%")
    if drawer_filter.strip():
        conditions.append("location LIKE ?")
        params.append(f"%{drawer_filter.strip().upper()}")
    if search_quantity > 0:
        conditions.append("quantity = ?")
        params.append(search_quantity)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    cursor.execute(query, params)
    items = cursor.fetchall()

    st.write(f"Found {len(items)} items")
    for item_id, location, name, notes, quantity in items:
        with st.expander(f"{name} ({location})"):
            st.write(f"**Location:** {location}")
            st.write(f"**Quantity:** {quantity}")
            st.write(f"**Notes:** {notes if notes else 'No notes'}")

            
            # Editable Notes
            edited_notes = st.text_area("Edit Notes", value=notes if notes else "", key=f"edit_notes_{item_id}")
            if st.button("Save Notes", key=f"save_notes_{item_id}"):
                cursor.execute("UPDATE inventory SET notes = ? WHERE rowid = ?", (edited_notes.strip(), item_id))
                conn.commit()
                st.success("Notes updated successfully.")

            # Actions: Check In/Out
            action = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"action_{item_id}")
            user = st.text_input("User Name", key=f"user_{item_id}")
            qty_action = st.number_input("Quantity to Check Out/In", min_value=1, step=1, key=f"qty_{item_id}")

            # Delete button
            delete_item = st.button("❌ Delete Item", key=f"delete_{item_id}")

            if st.button("Submit", key=f"submit_{item_id}"):
                if action != "None" and user.strip():
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?, ?, ?, ?, ?)",
                                   (name, action, user.strip(), timestamp, qty_action))
                    # Update quantity
                    if action == "Check Out":
                        new_qty = max(0, quantity - qty_action)
                    else:
                        new_qty = quantity + qty_action
                    cursor.execute("UPDATE inventory SET quantity = ? WHERE rowid = ?", (new_qty, item_id))
                    conn.commit()
                    st.success(f"{action} of {qty_action} recorded for '{name}' by {user} at {timestamp}")
                else:
                    st.error("Please select an action and enter a user name.")

            # Handle deletion
            if delete_item:
                if user.strip():
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("INSERT INTO transactions (item, action, user, timestamp, qty) VALUES (?, ?, ?, ?, ?)",
                                   (name, "Deleted", user.strip(), timestamp, quantity))
                    cursor.execute("DELETE FROM inventory WHERE rowid = ?", (item_id,))
                    conn.commit()
                    st.warning(f"Item '{name}' deleted and logged by {user}.")
                else:
                    st.error("Enter a user name before deleting.")

# ---------------- Transactions Tab ----------------
with tab_transactions:
    st.subheader("Search Transactions")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        trans_item = st.text_input("Item Name", key="trans_item")
    with col2:
        trans_user = st.text_input("User Name", key="trans_user")
    with col3:
        trans_action = st.selectbox("Action", ["All", "Check Out", "Check In", "Deleted"], key="trans_action")
    with col4:
        trans_qty = st.number_input("Quantity", min_value=0, step=1, key="trans_qty")

    start_date = st.date_input("Start Date", value=datetime(2020, 1, 1), key="trans_start_date")
    end_date = st.date_input("End Date", value=datetime.today(), key="trans_end_date")

    # Build transaction query
    query_tx = "SELECT * FROM transactions"
    conditions_tx = []
    params_tx = []

    if trans_item:
        conditions_tx.append("item LIKE ?")
        params_tx.append(f"%{trans_item}%")
    if trans_user:
        conditions_tx.append("user LIKE ?")
        params_tx.append(f"%{trans_user}%")
    if trans_action != "All":
        conditions_tx.append("action = ?")
        params_tx.append(trans_action)
    if trans_qty > 0:
        conditions_tx.append("qty = ?")
        params_tx.append(trans_qty)

    conditions_tx.append("timestamp BETWEEN ? AND ?")
    params_tx.append(start_date.strftime("%Y-%m-%d"))
    params_tx.append(end_date.strftime("%Y-%m-%d"))

    if conditions_tx:
        query_tx += " WHERE " + " AND ".join(conditions_tx)

    cursor.execute(query_tx, params_tx)
    logs = cursor.fetchall()

    st.write(f"Found {len(logs)} transactions")
    for log in logs:
        _, item_name, action, user_name, timestamp, qty = log
        st.write(f"🕒 {timestamp} — **{action}** {qty} of '{item_name}' by {user_name}")

# ---------------- Reports Tab ----------------
with tab_reports:
    st.subheader("Generate Inventory Report")
    with st.form("report_form"):
        
@st.cache_data
def get_locations():
    cursor.execute("SELECT DISTINCT location FROM inventory")
    return sorted(set([loc[0] for loc in cursor.fetchall()]))

locations = get_locations()

        prefixes = sorted(set([loc[:2] for loc in locations if len(loc) >= 2]))
        selected_prefix = st.selectbox("Select location prefix", ["All"] + prefixes, key="report_prefix")
        custom_filter = st.text_input("Or enter custom location text", key="report_custom_filter")
        quantity_filter = st.checkbox("Show only items with 0 quantity", key="report_quantity_filter")
        start_date = st.date_input("Start date", value=datetime(2020, 1, 1), key="report_start_date")
        end_date = st.date_input("End date", value=datetime.today(), key="report_end_date")
        generate_report = st.form_submit_button("Generate Report", key="report_generate_btn")

    if generate_report:
        query = "SELECT * FROM inventory"
        conditions = []
        params = []

        if selected_prefix != "All":
            conditions.append("location LIKE ?")
            params.append(f"{selected_prefix}%")
        if custom_filter:
            conditions.append("location LIKE ?")
            params.append(f"%{custom_filter}%")
        if quantity_filter:
            conditions.append("quantity = 0")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        df_report = pd.read_sql_query(query, conn, params=params)
        last_tx = pd.read_sql_query("SELECT item, MAX(timestamp) as last_tx FROM transactions GROUP BY item", conn)
        df_report = df_report.merge(last_tx, on='item', how='left')
        df_report['last_tx'] = pd.to_datetime(df_report['last_tx'], errors='coerce')
        df_report = df_report[(df_report['last_tx'].isna()) | ((df_report['last_tx'] >= pd.to_datetime(start_date)) & (df_report['last_tx'] <= pd.to_datetime(end_date)))]

        if df_report.empty:
            st.warning("No data found for the selected filters.")
        else:
            st.write("### Report Preview")
            st.dataframe(df_report)

            excel_path = "inventory_report.xlsx"
            df_report.to_excel(excel_path, index=False)

            pdf_path = "inventory_report.pdf"
            doc = fitz.open()
            text = "Inventory Report\n\n" + df_report.to_string(index=False)
            page = doc.new_page()
            page.insert_text((72, 72), text, fontsize=10)
            doc.save(pdf_path)
            doc.close()

            st.subheader("📥 Download Report")
            with open(excel_path, "rb") as f:
                st.download_button("Download Excel Report", f, file_name=excel_path)
            with open(pdf_path, "rb") as f:
                st.download_button("Download PDF Report", f, file_name=pdf_path)

# Close connection
conn.close()
