# excel_agent.py
# ExcelReaderAgent - reads all the sheets of an excel file

from agents.base_agent import BaseAgent
from agents.tabular import load_tables, make_profile, make_sections


class ExcelReaderAgent(BaseAgent):
    name = "ExcelReaderAgent"
    extensions = [".xlsx", ".xls"]
    split_into_chunks = False

    def read_file(self, file_path):
        sheets = load_tables(file_path)
        sections = []
        warnings = []
        sheet_details = {}
        total_rows = 0

        for sheet_name in sheets:
            df = sheets[sheet_name]
            if df.empty:
                warnings.append(f"Sheet '{sheet_name}' is empty.")
                continue

            sheet_sections, sheet_warnings = make_sections(df, sheet_name, sheet_name)
            sections = sections + sheet_sections
            warnings = warnings + sheet_warnings

            sheet_details[sheet_name] = make_profile(df)
            total_rows += len(df)

        profile = {
            "sheets": list(sheets.keys()),
            "total_rows": total_rows,
            "sheet_details": sheet_details,
        }
        return sections, profile, warnings
