# tabular.py
# Common functions for CSV and Excel files (used by the agents and by the MCP table tools)

import os

import pandas as pd

from config import ROWS_PER_CHUNK, MAX_ROWS_TO_INDEX

# simple cache so we don't read the same file again and again
table_cache = {}


def read_csv_file(file_path):
    # try different encodings because some csv files are not utf-8
    for encoding in ["utf-8", "utf-8-sig", "latin-1"]:
        try:
            # sep=None means pandas will find out if it is , or ; or tab
            return pd.read_csv(file_path, sep=None, engine="python", encoding=encoding)
        except UnicodeDecodeError:
            continue
        except pd.errors.ParserError:
            return pd.read_csv(file_path, encoding=encoding, on_bad_lines="skip")
    raise Exception("Could not read the CSV file (unknown encoding)")


def load_tables(file_path):
    # returns a dict like {"sheet name": dataframe}
    # for csv there is only one sheet called "data"
    cache_key = file_path + str(os.path.getmtime(file_path))
    if cache_key in table_cache:
        return table_cache[cache_key]

    tables = {}
    if file_path.lower().endswith(".csv"):
        tables["data"] = read_csv_file(file_path)
    else:
        sheets = pd.read_excel(file_path, sheet_name=None)
        for sheet_name in sheets:
            df = sheets[sheet_name]
            # remove empty rows and empty columns
            df = df.dropna(how="all")
            df = df.dropna(axis=1, how="all")
            tables[str(sheet_name)] = df

    table_cache[cache_key] = tables
    return tables


def make_profile(df):
    columns = []
    data_types = {}
    missing = {}
    for col in df.columns:
        columns.append(str(col))
        data_types[str(col)] = str(df[col].dtype)
        missing_count = int(df[col].isna().sum())
        if missing_count > 0:
            missing[str(col)] = missing_count

    numbers = df.select_dtypes("number")
    numeric_summary = {}
    if not numbers.empty:
        numeric_summary = numbers.describe().round(3).to_dict()

    return {
        "rows": len(df),
        "columns": columns,
        "dtypes": data_types,
        "missing_values": missing,
        "numeric_summary": numeric_summary,
    }


def value_to_text(value):
    if pd.isna(value):
        return ""
    # show 5.0 as 5
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def make_sections(df, table_name, sheet_name):
    # turns a table into text sections for RAG
    # first section = summary of the table, then one section for every 20 rows
    warnings = []
    profile = make_profile(df)

    # summary section
    lines = []
    lines.append(f"Table '{table_name}' has {profile['rows']} rows and {len(profile['columns'])} columns.")
    column_text = []
    for col in profile["columns"]:
        column_text.append(col + " (" + profile["dtypes"][col] + ")")
    lines.append("Columns: " + ", ".join(column_text))

    for col in profile["numeric_summary"]:
        stats = profile["numeric_summary"][col]
        lines.append(f"Column '{col}': min={stats.get('min')}, max={stats.get('max')}, "
                     f"mean={stats.get('mean')}, count={stats.get('count')}")

    for col in df.columns:
        if df[col].dtype == "object":
            top_values = df[col].dropna().astype(str).value_counts().head(5)
            if len(top_values) > 0:
                values_text = []
                for value, count in top_values.items():
                    values_text.append(f"{value} ({count})")
                lines.append(f"Column '{col}' most common values: " + ", ".join(values_text))

    sections = [{"text": "\n".join(lines), "info": {"sheet": sheet_name, "section": "schema overview"}}]

    # if the table is very big only index first rows (the table tools still use all rows)
    if len(df) > MAX_ROWS_TO_INDEX:
        warnings.append(f"'{table_name}' has {len(df)} rows. Only the first {MAX_ROWS_TO_INDEX} rows were "
                        f"indexed for search, but calculations still use all rows.")
        df = df.head(MAX_ROWS_TO_INDEX)

    # row sections
    column_names = []
    for col in df.columns:
        column_names.append(str(col))

    for start in range(0, len(df), ROWS_PER_CHUNK):
        part = df.iloc[start:start + ROWS_PER_CHUNK]
        row_lines = []
        row_number = start + 1
        for row in part.itertuples(index=False):
            cells = []
            for i in range(len(column_names)):
                text = value_to_text(row[i])
                if text != "":
                    cells.append(column_names[i] + "=" + text)
            row_lines.append(f"Row {row_number}: " + "; ".join(cells))
            row_number += 1

        end = start + len(part)
        text = f"Table '{table_name}', rows {start + 1}-{end}:\n" + "\n".join(row_lines)
        sections.append({"text": text, "info": {"sheet": sheet_name, "rows": f"{start + 1}-{end}"}})

    return sections, warnings
