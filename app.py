import streamlit as st
import pandas as pd
from io import BytesIO

st.set_page_config(
    page_title="Huawei 5-Min to 15-Min Aggregator",
    layout="wide"
)

st.title("Huawei Smart Logger 5-Min → 15-Min Aggregator")

uploaded = st.file_uploader(
    "Upload Huawei CSV",
    type=["csv"]
)

if uploaded:

    try:

        # ---------------------------------------------------
        # Read Huawei CSV
        # ---------------------------------------------------

        df = pd.read_csv(
            uploaded,
            skiprows=2,
            encoding="utf-8"
        )

        # Clean column names
        df.columns = (
            df.columns
            .str.replace('"', '', regex=False)
            .str.strip()
        )

        st.success("CSV Loaded Successfully")

        st.subheader("Original Data")

        st.dataframe(df)

        # ---------------------------------------------------
        # Timestamp
        # ---------------------------------------------------

        if "#Time" not in df.columns:
            st.error("Column '#Time' not found.")
            st.stop()

        df["#Time"] = pd.to_datetime(df["#Time"])

        df = df.set_index("#Time")

        # ---------------------------------------------------
        # Check required columns
        # ---------------------------------------------------

        required = [
            "Pac(kW)",
            "Eac(kWh)",
            "Eac Total(kWh)"
        ]

        for col in required:

            if col not in df.columns:

                st.error(f"{col} not found.")

                st.stop()

        # ---------------------------------------------------
        # Convert to numeric
        # ---------------------------------------------------

        for col in required:

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        # ---------------------------------------------------
        # Aggregate
        # ---------------------------------------------------

        result = pd.DataFrame()

        result["Pac(kW)"] = (
            df["Pac(kW)"]
            .resample("15min")
            .mean()
        )

        result["Eac(kWh)"] = (
            df["Eac(kWh)"]
            .resample("15min")
            .sum()
        )

        result["Eac Total(kWh)"] = (
            df["Eac Total(kWh)"]
            .resample("15min")
            .last()
        )

        result = result.reset_index()

        st.subheader("15-Minute Aggregated Data")

        st.dataframe(result)

        # ---------------------------------------------------
        # Download Excel
        # ---------------------------------------------------

        output = BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl"
        ) as writer:

            result.to_excel(
                writer,
                sheet_name="15_Min_Data",
                index=False
            )

        st.download_button(
            "Download Excel",
            output.getvalue(),
            file_name="Aggregated_15min.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:

        st.error(str(e))
