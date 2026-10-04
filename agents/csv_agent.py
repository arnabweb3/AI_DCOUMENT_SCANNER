# csv_agent.py
# CSVReaderAgent - reads csv files, makes a summary and turns rows into text

from agents.base_agent import BaseAgent
from agents.tabular import read_csv_file, make_profile, make_sections


class CSVReaderAgent(BaseAgent):
    name = "CSVReaderAgent"
    extensions = [".csv"]
    split_into_chunks = False

    def read_file(self, file_path):
        df = read_csv_file(file_path)
        table_name = file_path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
        sections, warnings = make_sections(df, table_name, "data")
        profile = make_profile(df)
        profile["sheets"] = ["data"]
        return sections, profile, warnings
