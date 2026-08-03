import streamlit as st
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="5-Min to 15-Min Aggregator", layout="wide")

st.title("Smart Logger 5-Min → 15-Min Aggregator")

uploaded = st.file_uploader(
    "Upload one Smart Logger CSV",
    type="csv"
)

if uploaded:

    # -----------------------
    # Read CSV
    # -----------------------
    df = pd.read_csv(uploaded)

    st.subheader("Original Data")
    st.dataframe(df)

    # -----------------------
    # Find timestamp column
    # -----------------------
    timestamp_col = None

    for c in df.columns:
        name = c.lower()

        if "time" in name:
            timestamp_col = c
            break

    if timestamp_col is None:
        st.error("No timestamp column found.")
        st.stop()

    df[timestamp_col] = pd.to_datetime(
        df[timestamp_col],
        dayfirst=True,
        errors="coerce"
    )

    df = df.dropna(subset=[timestamp_col])

    df = df.set_index(timestamp_col)

    # -----------------------
    # Numeric columns
    # -----------------------
    numeric = df.select_dtypes(include="number").columns

    agg = {}

    for col in numeric:

        name = col.lower()

        if "energy" in name:
            agg[col] = "sum"

        elif "power" in name:
            agg[col] = "mean"

        else:
            agg[col] = "mean"

    result = df.resample("15min").agg(agg)

    result = result.reset_index()

    st.subheader("15-Minute Data")

    st.dataframe(result)

    # -----------------------
    # Download Excel
    # -----------------------
    output = BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        result.to_excel(
            writer,
            index=False,
            sheet_name="15_Min_Data"
        )

    st.download_button(
        "Download Excel",
        output.getvalue(),
        "Aggregated_15min.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
