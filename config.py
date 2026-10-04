# config.py
# All the settings of my project are kept here so I can change them easily

import os

# folders
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma")
REGISTRY_FILE = os.path.join(DATA_DIR, "documents.json")
MCP_SERVER_FILE = os.path.join(BASE_DIR, "mcp_server", "server.py")

# create the folders if they are not there
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CHROMA_DIR, exist_ok=True)

# which agent reads which file type, and the MCP tool name for that agent
AGENT_ROUTES = {
    ".pdf": ("PDFReaderAgent", "read_pdf"),
    ".csv": ("CSVReaderAgent", "read_csv"),
    ".xlsx": ("ExcelReaderAgent", "read_excel"),
    ".xls": ("ExcelReaderAgent", "read_excel"),
    ".docx": ("WordReaderAgent", "read_docx"),
}
SUPPORTED_TYPES = ["pdf", "csv", "xlsx", "xls", "docx"]

# these MCP tools are only used by the app, the LLM should not call them
INTERNAL_TOOLS = ["read_pdf", "read_csv", "read_excel", "read_docx", "delete_document"]

# LLM models
GEMINI_MODELS = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-pro-latest", "gemini-3.5-flash-lite"]
OPENAI_MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"]
GEMINI_KEY_LINK = "https://aistudio.google.com/app/apikey"
OPENAI_KEY_LINK = "https://platform.openai.com/api-keys"

# RAG settings
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
ROWS_PER_CHUNK = 20  # for csv / excel
MAX_ROWS_TO_INDEX = 5000
TOP_K = 6

# LLM tool calling settings
MAX_TOOL_ROUNDS = 6
MAX_TOOL_RESULT_LENGTH = 12000
