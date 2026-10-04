# AI Document Scanner

It is an AI app that reads documents (PDF, CSV, Excel, Word) and answers
questions about them. It uses **RAG** and **MCP**, and you can choose **Gemini** or **OpenAI** as the LLM.
The user interface is made with **Streamlit**.

## Agents

- **ManagerAgent** - the main agent. It sends each file to the correct agent and answers questions.
- **PDFReaderAgent** - reads PDF files
- **CSVReaderAgent** - reads CSV files
- **ExcelReaderAgent** - reads Excel files (.xlsx, .xls)
- **WordReaderAgent** - reads Word files (.docx)

## How it works

**MCP:** I made an MCP server (`mcp_server/server.py`). The 4 reader agents and the search are
tools in this server. The Manager Agent connects to the server and calls the tools.
The LLM can also call some of the tools (like search or table calculations).

**RAG:**

1. When a file is uploaded, the agent reads it and cuts the text into small chunks.
2. The chunks are saved in ChromaDB (a vector database). ChromaDB makes the embeddings locally.
3. When you ask a question, the most similar chunks are found (Retrieve), added to the prompt
   (Augment), and the LLM writes the answer (Generate).

```
User -> Streamlit -> Manager Agent -> MCP Server -> Reader Agents -> ChromaDB
                          |
                          v
                   Gemini / OpenAI
```

## How to run

1. Install Python 3.10 or newer
2. Open a terminal in this folder and run:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Or just double click `run.bat` on Windows.

3. Put your API key in the sidebar, or create a `.env` file like this:

```
GOOGLE_API_KEY=your_gemini_key
OPENAI_API_KEY=your_openai_key
```

Note: the first time it downloads a small embedding model (about 80 MB).

## Folders

```
app.py              - streamlit app
config.py           - settings
agents/             - manager agent and the 4 reader agents
core/mcp_client.py  - connects to the MCP server
core/llm.py         - gemini and openai code
mcp_server/server.py - MCP server with all the tools
rag/                - chunking, vector database, saved documents list
data/               - uploaded files and database (made automatically)
```

## Problems I know about

- Scanned PDFs (only images) have no text so they can't be read.
- For very big tables only the first 5000 rows are used for search, but calculations use all rows.
