import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
import io
import fitz  # PyMuPDF – for PDF reports

# ------------------- CONFIG -------------------
INVENTORY_CSV = "inventory.csv"
TRANSACTIONS_CSV = "transactions.csv"

# ------------------- HELPER: Load / Save CSV -------------------
def load_inventory() -> pd.DataFrame:
    if os.path.exists(INVENTORY_CSV):
        return pd.read_csv(INVENTORY_CSV, dtype=str).fillna("")
    else:
        empty = pd.DataFrame(columns=["location", "item", "notes", "quantity"])
        empty.to_csv(INVENTORY_CSV, index=False)
        return empty

def save_inventory(df: pd.DataFrame):
    df.to_csv(INVENTORY_CSV, index=False)

def load_transactions() -> pd.DataFrame:
    if os.path.exists(TRANSACTIONS_CSV):
        return pd.read_csv(TRANSACTIONS_CSV, dtype=str).fillna("")
    else:
        empty = pd.DataFrame(columns=["item", "action", "user", "timestamp", "qty"])
        empty.to_csv(TRANSACTIONS_CSV, index=False)
        return empty

def save_transactions(df: pd.DataFrame):
    df.to_csv(TRANSACTIONS_CSV, index=False)

# ------------------- LOAD DATA -------------------
inventory_df = load_inventory()
transactions_df = load_transactions()

# ------------------- PAGE -------------------
st.set_page_config(page_title="CNC1 Tool Crib", layout="wide")
st.title("CNC1 Tool Crib Inventory System")

# ------------------- DEBUG + EXCEL BACKUP / RESTORE -------------------
col1, col2 = st.columns(2)

with col1:
    if st.button("CHECK DATA"):
        inv = len(inventory_df)
        tx = len(transactions_df)
        st.success(f"Inventory: {inv:,} rows | Transactions: {tx:,} rows")

with col2:
    # ---- Build Excel in memory (xlsxwriter – no openpyxl needed) ----
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        inventory_df.to_excel(writer, sheet_name="Inventory", index=False)
        transactions_df.to_excel(writer, sheet_name="Transactions", index=False)
    output.seek(0)

    st.download_button(
        label="DOWNLOAD EXCEL BACKUP",
        data=output.getvalue(),
        file_name=f"tool_crib_backup_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# ---- Restore from uploaded Excel ----
uploaded = st.file_uploader("Restore from Excel backup", type=["xlsx"])
if uploaded:
    try:
        # pandas can read xlsx without openpyxl if xlsxwriter is present
        dfs = pd.read_excel(uploaded, sheet_name=None, engine="openpyxl" if "openpyxl" in pd.__dict__ else "xlsxwriter")
        new_inv = dfs.get("Inventory", pd.DataFrame())
        new_tx  = dfs.get("Transactions", pd.DataFrame())

        inv_cols = ["location", "item", "notes", "quantity"]
        tx_cols  = ["item", "action", "user", "timestamp", "qty"]
        new_inv = new_inv[inv_cols].fillna("")
        new_tx  = new_tx[tx_cols].fillna("")

        new_inv.to_csv(INVENTORY_CSV, index=False)
        new_tx.to_csv(TRANSACTIONS_CSV, index=False)

        st.success("Backup restored! Refreshing data...")
        st.experimental_rerun()
    except Exception as e:
        st.error(f"Restore failed: {e}")

# ------------------- ADD ITEM -------------------
st.sidebar.header("Add New Item")
with st.sidebar.form("add_form", clear_on_submit=True):
    new_item = st.text_input("Item Name", key="add_name")
    new_loc  = st.text_input("Location (e.g., 105A)", key="add_loc").strip().upper()
    new_qty  = st.number_input("Quantity", min_value=0, step=1, value=0, key="add_qty")
    new_notes= st.text_area("Notes", key="add_notes")
    submitted = st.form_submit_button("Add Item")

    if submitted and new_item and new_loc:
        new_row = pd.DataFrame([{
            "location": new_loc,
            "item": new_item.strip(),
            "notes": new_notes.strip(),
            "quantity": int(new_qty)
        }])
        inventory_df = pd.concat([inventory_df, new_row], ignore_index=True)
        save_inventory(inventory_df)
        st.success(f"Added: {new_item}")
        st.experimental_rerun()

# ------------------- TABS -------------------
tab_inventory, tab_transactions, tab_reports = st.tabs(["Inventory", "Transactions", "Reports"])

# ------------------- INVENTORY TAB -------------------
with tab_inventory:
    st.subheader("Search Inventory")
    c1, c2, c3, c4 = st.columns(4)
    with c1: search_name = st.text_input("Item Name", key="inv_name")
    with c2: cabinet = st.selectbox("Cabinet", ["All"] + [str(i) for i in range(1, 200)], key="inv_cab")
    with c3: drawer  = st.selectbox("Drawer",  ["All"] + ["A","B","C","D","E","F"], key="inv_drawer")
    with c4: qty_f   = st.number_input("Exact Qty", min_value=0, value=0, key="inv_qty")

    df = inventory_df.copy()
    if search_name:
        df = df[df["item"].str.contains(search_name, case=False, na=False)]
    if cabinet != "All":
        df = df[df["location"].str.startswith(str(cabinet))]
    if drawer != "All":
        df = df[df["location"].str.endswith(drawer)]
    if qty_f > 0:
        df = df[df["quantity"].astype(int) == qty_f]

    if df.empty:
        st.warning("No items found.")
    else:
        st.write(f"**{len(df)} item(s) found**")
        for idx, row in df.iterrows():
            with st.expander(f"{row['item']} @ {row['location']} — Qty: {row['quantity']}"):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    notes = st.text_area("Notes", value=row.get('notes', ''), key=f"n_{idx}", height=70)
                    if st.button("Save Notes", key=f"s_{idx}"):
                        inventory_df.loc[idx, "notes"] = notes.strip()
                        save_inventory(inventory_df)
                        st.success("Saved")
                        st.experimental_rerun()

                action = st.selectbox("Action", ["None", "Check Out", "Check In"], key=f"a_{idx}")
                user   = st.text_input("Your Name", key=f"u_{idx}")
                qty    = st.number_input("Qty", min_value=1, step=1, value=1, key=f"q_{idx}")

                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("Submit", key=f"sub_{idx}") and action != "None" and user.strip():
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        new_tx = pd.DataFrame([{
                            "item": row["item"],
                            "action": action,
                            "user": user.strip(),
                            "timestamp": ts,
                            "qty": qty
                        }])
                        transactions_df = pd.concat([transactions_df, new_tx], ignore_index=True)
                        save_transactions(transactions_df)

                        cur_qty = int(row["quantity"])
                        new_qty = cur_qty - qty if action == "Check Out" else cur_qty + qty
                        inventory_df.loc[idx, "quantity"] = max(0, new_qty)
                        save_inventory(inventory_df)
                        st.success(f"{action}: {qty}")
                        st.experimental_rerun()

                with bc2:
                    if st.button("Delete", key=f"del_{idx}") and user.strip():
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        del_tx = pd.DataFrame([{
                            "item": row["item"],
                            "action": "Deleted",
                            "user": user.strip(),
                            "timestamp": ts,
                            "qty": row["quantity"]
                        }])
                        transactions_df = pd.concat([transactions_df, del_tx], ignore_index=True)
                        save_transactions(transactions_df)

                        inventory_df = inventory_df.drop(idx).reset_index(drop=True)
                        save_inventory(inventory_df)
                        st.warning("Deleted")
                        st.experimental_rerun()

# ------------------- TRANSACTIONS TAB -------------------
with tab_transactions:
    st.subheader("Transaction History")
    c1, c2, c3, c4 = st.columns(4)
    with c1: t_item = st.text_input("Item", key="t_item")
    with c2: t_user = st.text_input("User", key="t_user")
    with c3: t_act  = st.selectbox("Action", ["All","Check Out","Check In","Deleted"], key="t_act")
    with c4: t_qty  = st.number_input("Qty", min_value=0, value=0, key="t_qty")

    start = st.date_input("From", value=datetime(2020,1,1), key="t_start")
    end   = st.date_input("To",   value=datetime.today().date(), key="t_end")
    s_str = start.strftime("%Y-%m-%d 00:00:00")
    e_str = (end + timedelta(days=1) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

    df_tx = transactions_df.copy()
    df_tx = df_tx[(df_tx["timestamp"] >= s_str) & (df_tx["timestamp"] <= e_str)]
    if t_item: df_tx = df_tx[df_tx["item"].str.contains(t_item, case=False, na=False)]
    if t_user: df_tx = df_tx[df_tx["user"].str.contains(t_user, case=False, na=False)]
    if t_act != "All": df_tx = df_tx[df_tx["action"] == t_act]
    if t_qty > 0: df_tx = df_tx[df_tx["qty"].astype(int) == t_qty]

    if df_tx.empty:
        st.info("No transactions found.")
    else:
        st.dataframe(df_tx[["timestamp","action","qty","item","user"]], use_container_width=True, hide_index=True)

# ------------------- REPORTS TAB -------------------
with tab_reports:
    st.subheader("Generate Report")
    prefixes = sorted({loc[:2] for loc in inventory_df["location"] if len(loc) >= 2 and loc[:2].isdigit()})

    with st.form("report_form"):
        prefix = st.selectbox("Location Prefix", ["All"] + prefixes, key="r_prefix")
        custom = st.text_input("Custom Location Filter", key="r_custom")
        zero   = st.checkbox("Show only zero-quantity items", key="r_zero")
        r_start = st.date_input("Start Date", value=datetime(2020,1,1), key="r_start")
        r_end   = st.date_input("End Date", value=datetime.today().date(), key="r_end")
        gen = st.form_submit_button("Generate Report")

    if gen:
        r_start_str = r_start.strftime("%Y-%m-%d 00:00:00")
        r_end_str   = (r_end + timedelta(days=1) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

        df = inventory_df.copy()
        if prefix != "All": df = df[df["location"].str.startswith(prefix)]
        if custom: df = df[df["location"].str.contains(custom, case=False, na=False)]
        if zero: df = df[df["quantity"].astype(int) == 0]

        tx = transactions_df[(transactions_df["timestamp"] >= r_start_str) &
                            (transactions_df["timestamp"] <= r_end_str)]
        if not tx.empty:
            last = tx.loc[tx.groupby("item")["timestamp"].idxmax()][["item","timestamp"]]
            last.rename(columns={"timestamp":"last_tx"}, inplace=True)
            df = df.merge(last, on="item", how="left")
        else:
            df["last_tx"] = pd.NA

        if df.empty:
            st.warning("No data matches the filters.")
        else:
            st.write("### Report Preview")
            st.dataframe(df, use_container_width=True)

            buffer = io.BytesIO()
            doc = fitz.open()
            page = doc.new_page(width=800, height=1100)
            txt = "CNC1 Tool Crib Report\n\n" + df[["location","item","quantity","last_tx"]].to_string(index=False)
            page.insert_text((50,50), txt, fontsize=9)
            doc.save(buffer)
            doc.close()
            buffer.seek(0)

            st.download_button(
                "Download PDF Report",
                buffer.getvalue(),
                f"report_{datetime.now():%Y%m%d}.pdf",
                "application/pdf"
            )
