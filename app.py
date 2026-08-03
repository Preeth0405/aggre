"""
aggregate.py
Huawei Smart Logger 5-minute -> 15-minute data aggregator

Usage:
    python aggregate.py "Historical Data.zip"

or:
    python aggregate.py "Historical Data"

Output:
    SmartLogger_15min_Aggregated.xlsx
"""

import os
import re
import sys
import csv
import shutil
import zipfile
import tempfile
from pathlib import Path

import pandas as pd


# ============================================================
# SETTINGS
# ============================================================

OUTPUT_FILE = "SmartLogger_15min_Aggregated.xlsx"
RESAMPLE_INTERVAL = "15min"

# Words used to identify measurement types.
POWER_KEYWORDS = [
    "active power",
    "ac power",
    "power",
    "p_ac",
]

ENERGY_KEYWORDS = [
    "energy",
    "yield",
    "generation",
]


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def extract_serial_number(filename):
    """
    Extract Huawei inverter serial number from filename.

    Examples:
        BN2441029366.csv -> BN2441029366
        GR2469021353_data.csv -> GR2469021353
    """

    match = re.search(
        r"\b(?:BN|GR)[A-Z0-9]+\b",
        Path(filename).stem,
        re.IGNORECASE,
    )

    if match:
        return match.group(0).upper()

    # Fallback to filename if serial pattern isn't found.
    return Path(filename).stem


def detect_encoding(filepath):
    """
    Try common encodings used by Huawei CSV exports.
    """

    encodings = [
        "utf-8-sig",
        "utf-8",
        "gb18030",
        "gbk",
        "cp1252",
        "latin1",
    ]

    for encoding in encodings:
        try:
            with open(filepath, "r", encoding=encoding) as f:
                f.read(5000)

            return encoding

        except UnicodeDecodeError:
            continue

    return "latin1"


def detect_delimiter(filepath, encoding):
    """
    Detect CSV delimiter.
    """

    try:
        with open(filepath, "r", encoding=encoding) as f:
            sample = f.read(10000)

        dialect = csv.Sniffer().sniff(
            sample,
            delimiters=",;\t|",
        )

        return dialect.delimiter

    except Exception:
        return ","


def read_csv_safely(filepath):
    """
    Read CSV while automatically detecting encoding and delimiter.
    """

    encoding = detect_encoding(filepath)
    delimiter = detect_delimiter(filepath, encoding)

    try:

        df = pd.read_csv(
            filepath,
            encoding=encoding,
            sep=delimiter,
            low_memory=False,
        )

        return df

    except Exception as e:

        raise RuntimeError(
            f"Unable to read {filepath}: {e}"
        )


# ============================================================
# TIMESTAMP DETECTION
# ============================================================

def detect_timestamp_column(df):
    """
    Attempt to identify timestamp column automatically.
    """

    preferred_names = [
        "timestamp",
        "date time",
        "datetime",
        "time",
        "date/time",
        "collect time",
        "collection time",
        "record time",
    ]

    columns_lower = {
        str(col).strip().lower(): col
        for col in df.columns
    }

    # --------------------------------------------------------
    # First try obvious names
    # --------------------------------------------------------

    for name in preferred_names:

        if name in columns_lower:
            return columns_lower[name]

    # --------------------------------------------------------
    # Then search partial matches
    # --------------------------------------------------------

    for col in df.columns:

        name = str(col).lower()

        if "time" in name and "zone" not in name:
            return col

    return None


def build_timestamp(df):
    """
    Build pandas datetime index.

    Handles:
        single datetime column

    or:
        separate Date + Time columns
    """

    timestamp_col = detect_timestamp_column(df)

    if timestamp_col:

        timestamps = pd.to_datetime(
            df[timestamp_col],
            errors="coerce",
            dayfirst=True,
        )

        if timestamps.notna().sum() > 0:
            return timestamps, [timestamp_col]

    # --------------------------------------------------------
    # Try separate Date + Time columns
    # --------------------------------------------------------

    date_col = None
    time_col = None

    for col in df.columns:

        name = str(col).strip().lower()

        if name == "date":
            date_col = col

        if name == "time":
            time_col = col

    if date_col and time_col:

        combined = (
            df[date_col].astype(str)
            + " "
            + df[time_col].astype(str)
        )

        timestamps = pd.to_datetime(
            combined,
            errors="coerce",
            dayfirst=True,
        )

        return timestamps, [date_col, time_col]

    raise ValueError(
        "Could not identify timestamp column."
    )


# ============================================================
# NUMERIC DATA
# ============================================================

def convert_numeric_columns(df, exclude_columns):
    """
    Convert measurement columns to numeric where possible.
    """

    output = df.copy()

    for col in output.columns:

        if col in exclude_columns:
            continue

        if pd.api.types.is_numeric_dtype(output[col]):
            continue

        converted = pd.to_numeric(
            output[col]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.replace(" ", "", regex=False),
            errors="coerce",
        )

        # Only replace if meaningful numeric data exists.
        if converted.notna().sum() > 0:
            output[col] = converted

    return output


# ============================================================
# AGGREGATION LOGIC
# ============================================================

def determine_aggregation(column_name):
    """
    Determine how a measurement should be aggregated.

    POWER:
        Average

    ENERGY:
        Default = sum

    Other numeric measurements:
        Average

    IMPORTANT:
    If Huawei Energy is cumulative rather than interval energy,
    it should NOT be summed. The script handles cumulative-looking
    energy separately below.
    """

    name = str(column_name).lower()

    for keyword in ENERGY_KEYWORDS:

        if keyword in name:
            return "energy"

    for keyword in POWER_KEYWORDS:

        if keyword in name:
            return "mean"

    return "mean"


def looks_cumulative(series):
    """
    Simple check for cumulative energy counters.

    If most consecutive differences are >= 0,
    treat it as a cumulative counter.
    """

    values = series.dropna()

    if len(values) < 10:
        return False

    diff = values.diff().dropna()

    if len(diff) == 0:
        return False

    non_decreasing_ratio = (
        (diff >= 0).sum() / len(diff)
    )

    return non_decreasing_ratio >= 0.90


def aggregate_dataframe(df, serial_number):
    """
    Convert one Smart Logger CSV from 5-minute data
    into 15-minute data.
    """

    timestamps, timestamp_columns = build_timestamp(df)

    work = df.copy()

    work["__timestamp__"] = timestamps

    # Remove rows where timestamp could not be parsed.
    work = work.dropna(
        subset=["__timestamp__"]
    )

    # Sort chronologically.
    work = work.sort_values(
        "__timestamp__"
    )

    # Remove duplicate timestamps.
    work = work.drop_duplicates(
        subset=["__timestamp__"],
        keep="last",
    )

    # Convert measurements to numeric.
    work = convert_numeric_columns(
        work,
        timestamp_columns + ["__timestamp__"],
    )

    work = work.set_index(
        "__timestamp__"
    )

    numeric_columns = work.select_dtypes(
        include="number"
    ).columns.tolist()

    if not numeric_columns:

        raise ValueError(
            "No numeric measurement columns detected."
        )

    result = pd.DataFrame()

    # ========================================================
    # AGGREGATE EACH MEASUREMENT
    # ========================================================

    for col in numeric_columns:

        mode = determine_aggregation(col)

        # ----------------------------------------------------
        # ENERGY
        # ----------------------------------------------------

        if mode == "energy":

            if looks_cumulative(work[col]):

                # For cumulative meter:
                # take last reading in each 15-minute interval.
                aggregated = (
                    work[col]
                    .resample(RESAMPLE_INTERVAL)
                    .last()
                )

            else:

                # Interval energy:
                # sum three 5-minute energy values.
                aggregated = (
                    work[col]
                    .resample(RESAMPLE_INTERVAL)
                    .sum(min_count=1)
                )

        # ----------------------------------------------------
        # POWER / OTHER
        # ----------------------------------------------------

        else:

            aggregated = (
                work[col]
                .resample(RESAMPLE_INTERVAL)
                .mean()
            )

        result[col] = aggregated

    # ========================================================
    # QUALITY INFORMATION
    # ========================================================

    # Count how many original records contributed
    # to each 15-minute interval.
    record_count = (
        work
        .resample(RESAMPLE_INTERVAL)
        .size()
    )

    result.insert(
        0,
        "5_Min_Record_Count",
        record_count,
    )

    result.insert(
        0,
        "Serial_Number",
        serial_number,
    )

    result.index.name = "Timestamp"

    result = result.reset_index()

    return result


# ============================================================
# ZIP / DIRECTORY HANDLING
# ============================================================

def prepare_input(input_path):
    """
    Accept either:
        ZIP file
        folder containing CSV files

    Returns:
        working folder
        temporary folder (if used)
    """

    path = Path(input_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Input does not exist: {input_path}"
        )

    if path.is_dir():
        return path, None

    if path.suffix.lower() == ".zip":

        temp_dir = tempfile.mkdtemp(
            prefix="smartlogger_"
        )

        with zipfile.ZipFile(
            path,
            "r",
        ) as archive:

            archive.extractall(
                temp_dir
            )

        return Path(temp_dir), temp_dir

    raise ValueError(
        "Input must be a ZIP file or folder."
    )


def find_csv_files(folder):
    """
    Recursively locate CSV files.
    """

    return sorted(
        folder.rglob("*.csv")
    )


# ============================================================
# MISSING INTERVAL CHECK
# ============================================================

def find_missing_intervals(df):
    """
    Identify 15-minute intervals where fewer than
    three 5-minute records were available.
    """

    if "5_Min_Record_Count" not in df.columns:
        return pd.DataFrame()

    missing = df[
        df["5_Min_Record_Count"] < 3
    ].copy()

    return missing


# ============================================================
# EXCEL EXPORT
# ============================================================

def safe_sheet_name(name):
    """
    Excel sheet names cannot exceed 31 characters.
    """

    invalid = r'[]:*?/\\'

    for char in invalid:
        name = name.replace(char, "_")

    return name[:31]


def export_excel(
    combined,
    individual_data,
    summary,
    missing,
    output_file,
):
    """
    Export final workbook.
    """

    with pd.ExcelWriter(
        output_file,
        engine="openpyxl",
    ) as writer:

        # ----------------------------------------------------
        # Combined dataset
        # ----------------------------------------------------

        combined.to_excel(
            writer,
            sheet_name="Combined_15min",
            index=False,
        )

        # ----------------------------------------------------
        # Summary
        # ----------------------------------------------------

        summary.to_excel(
            writer,
            sheet_name="Summary",
            index=False,
        )

        # ----------------------------------------------------
        # Missing intervals
        # ----------------------------------------------------

        if not missing.empty:

            missing.to_excel(
                writer,
                sheet_name="Missing_Intervals",
                index=False,
            )

        # ----------------------------------------------------
        # Individual inverter sheets
        # ----------------------------------------------------

        for serial, df in individual_data.items():

            sheet = safe_sheet_name(
                serial
            )

            df.to_excel(
                writer,
                sheet_name=sheet,
                index=False,
            )

        # ----------------------------------------------------
        # Formatting
        # ----------------------------------------------------

        workbook = writer.book

        for worksheet in workbook.worksheets:

            worksheet.freeze_panes = "A2"

            worksheet.auto_filter.ref = (
                worksheet.dimensions
            )

            for column in worksheet.columns:

                max_length = 0

                column_letter = (
                    column[0].column_letter
                )

                for cell in column[:200]:

                    value = cell.value

                    if value is None:
                        continue

                    max_length = max(
                        max_length,
                        len(str(value)),
                    )

                worksheet.column_dimensions[
                    column_letter
                ].width = min(
                    max(max_length + 2, 12),
                    35,
                )


# ============================================================
# MAIN PROCESS
# ============================================================

def process(input_path, output_file=OUTPUT_FILE):

    folder, temp_dir = prepare_input(
        input_path
    )

    try:

        csv_files = find_csv_files(
            folder
        )

        if not csv_files:

            raise RuntimeError(
                "No CSV files found."
            )

        print()
        print("=" * 60)
        print("SMART LOGGER 5-MIN -> 15-MIN AGGREGATOR")
        print("=" * 60)

        print(
            f"\nCSV files found: {len(csv_files)}"
        )

        individual_data = {}

        summary_rows = []

        missing_frames = []

        combined_frames = []

        # ====================================================
        # PROCESS EACH INVERTER
        # ====================================================

        for number, filepath in enumerate(
            csv_files,
            start=1,
        ):

            serial = extract_serial_number(
                filepath.name
            )

            print(
                f"[{number}/{len(csv_files)}] "
                f"{serial}"
            )

            try:

                original = read_csv_safely(
                    filepath
                )

                original_rows = len(
                    original
                )

                aggregated = (
                    aggregate_dataframe(
                        original,
                        serial,
                    )
                )

                aggregated_rows = len(
                    aggregated
                )

                individual_data[
                    serial
                ] = aggregated

                combined_frames.append(
                    aggregated
                )

                missing = (
                    find_missing_intervals(
                        aggregated
                    )
                )

                if not missing.empty:

                    missing_frames.append(
                        missing
                    )

                summary_rows.append(
                    {
                        "Serial_Number":
                            serial,

                        "Source_File":
                            filepath.name,

                        "5_Min_Records":
                            original_rows,

                        "15_Min_Records":
                            aggregated_rows,

                        "Incomplete_15_Min_Intervals":
                            len(missing),

                        "Status":
                            "OK",
                    }
                )

            except Exception as e:

                print(
                    f"   ERROR: {e}"
                )

                summary_rows.append(
                    {
                        "Serial_Number":
                            serial,

                        "Source_File":
                            filepath.name,

                        "5_Min_Records":
                            None,

                        "15_Min_Records":
                            None,

                        "Incomplete_15_Min_Intervals":
                            None,

                        "Status":
                            f"ERROR: {e}",
                    }
                )

        # ====================================================
        # COMBINE
        # ====================================================

        if not combined_frames:

            raise RuntimeError(
                "No CSV files were successfully processed."
            )

        combined = pd.concat(
            combined_frames,
            ignore_index=True,
        )

        combined = combined.sort_values(
            [
                "Timestamp",
                "Serial_Number",
            ]
        )

        summary = pd.DataFrame(
            summary_rows
        )

        if missing_frames:

            missing = pd.concat(
                missing_frames,
                ignore_index=True,
            )

        else:

            missing = pd.DataFrame()

        # ====================================================
        # EXPORT
        # ====================================================

        export_excel(
            combined,
            individual_data,
            summary,
            missing,
            output_file,
        )

        print()
        print("=" * 60)
        print("COMPLETE")
        print("=" * 60)

        print(
            f"\nOutput: {output_file}"
        )

        print(
            f"Inverters processed: "
            f"{len(individual_data)}"
        )

        print(
            f"Combined 15-minute rows: "
            f"{len(combined):,}"
        )

        if not missing.empty:

            print(
                f"Incomplete intervals: "
                f"{len(missing):,}"
            )

        print()

    finally:

        if temp_dir:

            shutil.rmtree(
                temp_dir,
                ignore_errors=True,
            )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) < 2:

        print(
            '\nUsage:\n'
            'python aggregate.py "Historical Data.zip"\n'
        )

        sys.exit(1)

    input_path = sys.argv[1]

    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        output_file = OUTPUT_FILE

    process(
        input_path,
        output_file,
    )
