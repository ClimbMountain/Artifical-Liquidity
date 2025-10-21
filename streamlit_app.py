#!/usr/bin/env python3
"""Simple Streamlit dashboard for Polyfarm
- Shows Markets × Wallets matrix
- Sessions overview & chain sequence
- Wallet stats & trades
- App logs

Assumes the extra views exist in SQLite:
  v_wallet_market_pos, v_chain_sequence
"""
import sqlite3
import pandas as pd
import streamlit as st

DB_PATH = "polyfarm.db"

# ---------- Helpers ----------
@st.cache_data(ttl=15)
def q(sql: str, params=None) -> pd.DataFrame:
    """Run a read-only query and return a DataFrame."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return pd.read_sql(sql, conn, params=params or ())

st.set_page_config(page_title="Polyfarm Monitor", layout="wide")
st.title("Polyfarm Monitor")

# Optional: force refresh every 15s (comment out if annoying)
# st.autorefresh(interval=15_000, key="autoreload")

# ---------- Tabs ----------
tab1, tab2, tab3, tab4 = st.tabs(["Markets × Wallets", "Sessions", "Wallets", "Logs"])

# --- Markets × Wallets ---
with tab1:
    df = q("SELECT * FROM v_wallet_market_pos")
    if df.empty:
        st.info("No filled trades yet.")
    else:
        pivot = df.pivot_table(
            index=["condition_id", "title"],
            columns="nickname",
            values="filled_size",
            aggfunc="sum",
            fill_value=0,
        )
        st.dataframe(pivot, use_container_width=True)

        # Market inspector
        titles = sorted(df["title"].unique()) if not df.empty else []
        sel = st.selectbox("Inspect market", titles) if titles else None
        if sel:
            cond_id = df.loc[df["title"] == sel, "condition_id"].iloc[0]
            trades = q(
                """
                SELECT t.*, w.nickname
                FROM trades t
                JOIN wallets w ON w.id = t.wallet_id
                JOIN tokens tok ON tok.token_id = t.token_id
                WHERE tok.condition_id = ?
                ORDER BY t.timestamp DESC
                LIMIT 50
                """,
                (cond_id,),
            )
            st.subheader("Recent trades")
            st.dataframe(trades, use_container_width=True)

# --- Sessions ---
with tab2:
    sess = q("SELECT * FROM v_active_sessions ORDER BY start_time DESC")
    st.dataframe(sess, use_container_width=True)

    uuid = st.selectbox("Session UUID", sess["session_uuid"]) if not sess.empty else None
    if uuid:
        seq = q("SELECT * FROM v_chain_sequence WHERE session_uuid = ?", (uuid,))
        st.subheader("Chain sequence")
        st.dataframe(seq, use_container_width=True)

# --- Wallets ---
with tab3:
    wallets = q("SELECT * FROM v_wallet_summary ORDER BY wallet_index")
    st.dataframe(wallets, use_container_width=True)

    wid = st.selectbox("Wallet detail (id)", wallets["id"]) if not wallets.empty else None
    if wid:
        wtrades = q(
            """
            SELECT t.*, mc.title
            FROM trades t
            JOIN tokens tok ON tok.token_id = t.token_id
            JOIN market_conditions mc ON mc.condition_id = tok.condition_id
            WHERE wallet_id = ?
            ORDER BY timestamp DESC
            LIMIT 100
            """,
            (wid,),
        )
        st.subheader("Recent trades for wallet")
        st.dataframe(wtrades, use_container_width=True)

# --- Logs ---
with tab4:
    level = st.selectbox("Level", ["ALL", "INFO", "WARNING", "ERROR"], index=0)
    sql = "SELECT * FROM app_logs ORDER BY timestamp DESC LIMIT 200"
    params = ()
    if level != "ALL":
        sql = (
            "SELECT * FROM app_logs WHERE log_level = ? "
            "ORDER BY timestamp DESC LIMIT 200"
        )
        params = (level,)
    logs = q(sql, params)
    st.dataframe(logs, use_container_width=True)
