import streamlit as st
import pandas as pd
from io import BytesIO
import re

st.set_page_config(page_title="Huawei Aggregator", layout="wide")

st.title("Huawei Smart Logger 5-Min → 15-Min Aggregator")

uploaded = st.file_uploader("Upload Huawei CSV", type="csv")

if uploaded:

    # -----------------------------
    # Read serial number
    # -----------------------------
    uploaded.seek(0)

    header1 = uploaded.readline().decode("utf-8").strip()
    header2 = uploaded.readline().decode("utf-8").strip()

    serial = ""

    m = re.search(r"INV SN:\s*(.*)", header2)

    if m:
        serial = m.group(1).strip()

    uploaded.seek(0)

    # -----------------------------
    # Read CSV
    # -----------------------------
    df = pd.read_csv(
        uploaded,
        skiprows=2
    )

    df.columns = (
        df.columns
        .str.replace('"',"")
        .str.strip()
    )

    # -----------------------------
    # Timestamp
    # -----------------------------
    df["#Time"] = pd.to_datetime(df["#Time"])

    df = df.set_index("#Time")

    # -----------------------------
    # Convert numeric
    # -----------------------------
    for c in df.columns:
        if c == "#Time":
           continue

        try:
           df[c] = pd.to_numeric(df[c])
        except Exception:
           pass
    # -----------------------------
    # Build aggregation dictionary
    # -----------------------------
    agg = {}

    for c in df.columns:

        if not pd.api.types.is_numeric_dtype(df[c]):
            continue

        name = c.lower()

        if "total" in name:

            agg[c] = "last"

        elif "energy" in name:

            agg[c] = "sum"

        elif "eac(" in name:

            agg[c] = "sum"

        else:

            agg[c] = "mean"

    # -----------------------------
    # Aggregate
    # -----------------------------
    result = df.resample("15min").agg(agg)

    result.insert(
        0,
        "Inverter Serial Number",
        serial
    )

    result = result.reset_index()

    # -----------------------------
    # Display
    # -----------------------------
    st.subheader("15 Minute Data")

    st.dataframe(result)

    # -----------------------------
    # Download
    # -----------------------------
    output = BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        result.to_excel(
            writer,
            sheet_name="15 Minute",
            index=False
        )

    st.download_button(
        "Download Excel",
        output.getvalue(),
        "15min_" + serial + ".xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
