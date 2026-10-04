# server.py
# My MCP server.
# It gives the reader agents and the RAG search as MCP tools.
# The Manager Agent (in app.py) connects to this server and calls these tools.
#
# You can also run it alone:  python mcp_server/server.py

import json
import os
import sys

# add the project folder to path so we can import agents, rag, config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from agents import PDFReaderAgent, CSVReaderAgent, ExcelReaderAgent, WordReaderAgent
from agents.tabular import load_tables
from rag import registry
from rag import vector_store

server = MCPServer("document-scanner")


def to_json(data):
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


def scan_with_agent(agent, file_path):
    # run the agent, save the chunks in the vector database and save the details
    try:
        result = agent.run(file_path)
    except Exception as e:
        # ToolError sends the error message back to the app
        raise ToolError(type(e).__name__ + ": " + str(e))

    vector_store.add_chunks(result["doc_id"], result["chunks"])

    details = {
        "doc_id": result["doc_id"],
        "file_name": result["file_name"],
        "file_type": result["file_type"],
        "file_path": os.path.abspath(file_path),
        "agent": result["agent"],
        "chunks": len(result["chunks"]),
        "profile": result["profile"],
        "preview": result["preview"],
        "warnings": result["warnings"],
    }
    registry.add_document(result["doc_id"], details)
    return to_json(details)


# ---------------- Reader agent tools ----------------

@server.tool()
def read_pdf(file_path: str) -> str:
    """PDFReaderAgent: extract text from a PDF page by page and index it in the knowledge base."""
    return scan_with_agent(PDFReaderAgent(), file_path)


@server.tool()
def read_csv(file_path: str) -> str:
    """CSVReaderAgent: profile a CSV table and index its rows in the knowledge base."""
    return scan_with_agent(CSVReaderAgent(), file_path)


@server.tool()
def read_excel(file_path: str) -> str:
    """ExcelReaderAgent: read every sheet of an Excel workbook and index it in the knowledge base."""
    return scan_with_agent(ExcelReaderAgent(), file_path)


@server.tool()
def read_docx(file_path: str) -> str:
    """WordReaderAgent: read paragraphs, headings and tables of a Word document and index them."""
    return scan_with_agent(WordReaderAgent(), file_path)


# ---------------- Knowledge base tools ----------------

@server.tool()
def search_documents(query: str, top_k: int = 5, doc_ids: list[str] | None = None) -> str:
    """Semantic (RAG) search over all scanned documents.

    Args:
        query: What to look for, phrased as a question or keywords.
        top_k: Number of passages to return (1-20).
        doc_ids: Optional list of document ids to restrict the search to.
    """
    top_k = int(top_k)
    if top_k < 1:
        top_k = 1
    if top_k > 20:
        top_k = 20
    hits = vector_store.search(query, top_k, doc_ids)
    return to_json(hits)


@server.tool()
def list_documents() -> str:
    """List every scanned document with its id, file name, type and the agent that read it."""
    all_docs = registry.load_all()
    result = []
    for doc_id in all_docs:
        doc = all_docs[doc_id]
        result.append({
            "doc_id": doc["doc_id"],
            "file_name": doc["file_name"],
            "file_type": doc["file_type"],
            "agent": doc["agent"],
            "chunks": doc["chunks"],
        })
    return to_json(result)


@server.tool()
def get_document_info(doc_id: str) -> str:
    """Get the profile of one document: page/word counts, headings, sheets, columns, statistics."""
    doc = registry.get_document(doc_id)
    if doc is None:
        return to_json({"error": "No document with id " + doc_id + ". Use list_documents to see ids."})
    doc = dict(doc)
    doc.pop("file_path", None)  # don't show the full path
    return to_json(doc)


@server.tool()
def delete_document(doc_id: str) -> str:
    """Remove a document from the knowledge base."""
    vector_store.delete_document(doc_id)
    doc = registry.remove_document(doc_id)
    if doc is not None and os.path.exists(doc["file_path"]):
        os.remove(doc["file_path"])
    return to_json({"deleted": doc is not None, "doc_id": doc_id})


# ---------------- Table tools (for CSV / Excel) ----------------

def get_table(doc_id, sheet=""):
    doc = registry.get_document(doc_id)
    if doc is None:
        raise Exception("No document with id " + doc_id)
    if doc["file_type"] not in ["csv", "xlsx", "xls"]:
        raise Exception(doc["file_name"] + " is not a CSV or Excel file.")

    tables = load_tables(doc["file_path"])
    if sheet == "":
        sheet = list(tables.keys())[0]  # first sheet
    if sheet not in tables:
        raise Exception("Sheet " + sheet + " not found. Sheets are: " + str(list(tables.keys())))
    return sheet, tables[sheet]


def find_column(df, column):
    # match column name without caring about upper/lower case
    for col in df.columns:
        if str(col).strip().lower() == column.strip().lower():
            return col
    raise Exception("Column " + column + " not found. Columns are: " + str([str(c) for c in df.columns]))


@server.tool()
def describe_table(doc_id: str, sheet: str = "") -> str:
    """Show columns, data types, the first rows and summary statistics of a CSV/Excel table.

    Args:
        doc_id: Document id of a CSV or Excel file.
        sheet: Excel sheet name (leave empty for the first sheet / CSV).
    """
    try:
        sheet, df = get_table(doc_id, sheet)
    except Exception as e:
        return to_json({"error": str(e)})

    columns = {}
    for col in df.columns:
        columns[str(col)] = str(df[col].dtype)

    return to_json({
        "sheet": sheet,
        "rows": len(df),
        "columns": columns,
        "head": df.head(5).to_dict(orient="records"),
        "statistics": df.describe(include="all").round(3).fillna("").to_dict(),
    })


@server.tool()
def filter_table(doc_id: str, column: str, operator: str, value: str, sheet: str = "", limit: int = 20) -> str:
    """Return the rows of a CSV/Excel table where `column <operator> value`.

    Args:
        doc_id: Document id of a CSV or Excel file.
        column: Column to filter on.
        operator: One of ==, !=, >, >=, <, <=, contains.
        value: Value to compare with (numbers are converted automatically).
        sheet: Excel sheet name (leave empty for the first sheet / CSV).
        limit: Maximum rows to return.
    """
    try:
        sheet, df = get_table(doc_id, sheet)
        col = find_column(df, column)
    except Exception as e:
        return to_json({"error": str(e)})

    if operator == "contains":
        mask = df[col].astype(str).str.contains(value, case=False, na=False)
    else:
        # if value is a number compare as numbers, otherwise compare as text
        try:
            target = float(value)
            data = pd.to_numeric(df[col], errors="coerce")
        except ValueError:
            target = value.lower()
            data = df[col].astype(str).str.lower()

        if operator == "==":
            mask = data == target
        elif operator == "!=":
            mask = data != target
        elif operator == ">":
            mask = data > target
        elif operator == ">=":
            mask = data >= target
        elif operator == "<":
            mask = data < target
        elif operator == "<=":
            mask = data <= target
        else:
            return to_json({"error": "Unknown operator " + operator})

    result = df[mask]
    limit = max(1, min(int(limit), 200))
    return to_json({
        "sheet": sheet,
        "matching_rows": len(result),
        "rows": result.head(limit).to_dict(orient="records"),
    })


@server.tool()
def aggregate_table(doc_id: str, column: str, agg: str, group_by: str = "", sheet: str = "") -> str:
    """Compute an aggregate over a CSV/Excel column, optionally grouped by another column.

    Args:
        doc_id: Document id of a CSV or Excel file.
        column: Column to aggregate.
        agg: One of sum, mean, median, min, max, count, nunique.
        group_by: Optional column to group by.
        sheet: Excel sheet name (leave empty for the first sheet / CSV).
    """
    allowed = ["sum", "mean", "median", "min", "max", "count", "nunique"]
    if agg not in allowed:
        return to_json({"error": "agg must be one of " + str(allowed)})

    try:
        sheet, df = get_table(doc_id, sheet)
        col = find_column(df, column)
        group_col = None
        if group_by != "":
            group_col = find_column(df, group_by)
    except Exception as e:
        return to_json({"error": str(e)})

    data = df[col]
    if agg in ["sum", "mean", "median"]:
        data = pd.to_numeric(data, errors="coerce")

    if group_col is not None:
        grouped = data.groupby(df[group_col]).agg(agg).sort_values(ascending=False)
        result = {}
        for key, val in grouped.head(50).items():
            if pd.isna(val):
                result[str(key)] = None
            else:
                result[str(key)] = round(float(val), 4)
    else:
        val = data.agg(agg)
        if pd.isna(val):
            result = None
        else:
            result = round(float(val), 4)

    return to_json({"sheet": sheet, "column": str(col), "agg": agg,
                    "group_by": str(group_col) if group_col is not None else None, "result": result})


if __name__ == "__main__":
    server.run()
