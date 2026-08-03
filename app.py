import streamlit as st
import pandas as pd
import io
import zipfile

# Set up the page
st.set_page_config(page_title="Inverter Data Aggregator", layout="wide")
st.title("⚡ Solar Inverter 15-Min Energy Aggregator")
st.write("Upload raw 5-minute inverter CSV files to calculate the true 15-minute integrated AC Power.")

def process_inverter_csv(file_buffer):
    """Parses the raw inverter CSV and applies the 15-minute integration logic."""
    # Decode the uploaded file bytes to string and split into lines
    lines = file_buffer.getvalue().decode('utf-8', errors='ignore').splitlines()
    
    data_rows = []
    header = None
    
    for i, line in enumerate(lines):
        if i < 2:  # Skip the two metadata lines
            continue
        if i == 2:  # Extract header
            header = [c.strip() for c in line.strip().split(',')]
            header = [c for c in header if c]
            continue
            
        parts = [p.strip() for p in line.strip().split(',')]
        if len(parts) > 0 and parts[0]: 
            parts = parts[:len(header)]
            if len(parts) < len(header):
                parts += [''] * (len(header) - len(parts))
            data_rows.append(parts)
            
    if not header or not data_rows:
        return None

    # Build the DataFrame
    df = pd.DataFrame(data_rows, columns=header)
    df['datetime'] = pd.to_datetime(df['#Time'])
    df = df.sort_values('datetime')
    df.set_index('datetime', inplace=True)
    df.drop(columns=['#Time'], inplace=True)

    # Convert all columns to numeric
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Resample backwards (closed='right', label='right')
    df_mean = df.resample('15min', closed='right', label='right').mean()
    df_last = df.resample('15min', closed='right', label='right').last()
    
    df_15min = df_mean.copy()

    # Overwrite cumulative columns with their closing values
    for col in df.columns:
        if 'Total' in col or 'Eac(kWh)' in col or 'Edc' in col:
            df_15min[col] = df_last[col]

    # Calculate True Energy Integration for AC Power
    if 'Eac Total(kWh)' in df_last.columns:
        df_15min['Pac(kW)'] = df_last['Eac Total(kWh)'].diff() * 4

    # Clean up empty intervals
    df_15min.dropna(how='all', subset=[c for c in df_15min.columns if c not in ['Pac(kW)', 'Eac Total(kWh)']], inplace=True)

    # Reformat timestamp for output
    df_15min.reset_index(inplace=True)
    df_15min.rename(columns={'datetime': '#Time'}, inplace=True)
    df_15min['#Time'] = df_15min['#Time'].dt.strftime('%Y-%m-%d %H:%M:%S')

    return df_15min

# File Uploader
uploaded_files = st.file_uploader(
    "Upload Inverter CSV Files", 
    type=['csv'], 
    accept_multiple_files=True
)

if uploaded_files:
    st.info(f"Loaded {len(uploaded_files)} files. Ready to process.")
    
    if st.button("Process & Aggregate Files"):
        progress_bar = st.progress(0)
        
        # Create an in-memory zip file
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for i, uploaded_file in enumerate(uploaded_files):
                try:
                    # Process the individual file
                    processed_df = process_inverter_csv(uploaded_file)
                    
                    if processed_df is not None:
                        # Convert processed dataframe to CSV string
                        csv_string = processed_df.to_csv(index=False)
                        
                        # Generate the new filename and write to the zip archive
                        new_filename = f"{uploaded_file.name.replace('.csv', '')}_15min_aligned.csv"
                        zip_file.writestr(new_filename, csv_string)
                        
                except Exception as e:
                    st.error(f"Error processing {uploaded_file.name}: {e}")
                
                # Update progress
                progress_bar.progress((i + 1) / len(uploaded_files))
                
        zip_buffer.seek(0)
        
        st.success("All files processed successfully!")
        
        # Provide the download button for the ZIP file
        st.download_button(
            label="📦 Download All Processed Files (ZIP)",
            data=zip_buffer,
            file_name="Processed_Inverter_Data.zip",
            mime="application/zip"
        )
