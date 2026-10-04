# app.py
# AI Document Scanner - Streamlit app
# Run it with:  streamlit run app.py

import hashlib
import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from agents.manager_agent import ManagerAgent, make_source_label
from config import (AGENT_ROUTES, INTERNAL_TOOLS, SUPPORTED_TYPES, UPLOAD_DIR, MCP_SERVER_FILE, TOP_K,
                    GEMINI_MODELS, OPENAI_MODELS, GEMINI_KEY_LINK, OPENAI_KEY_LINK)
from core.llm import make_llm
from core.mcp_client import MCPClient

# load API keys from the .env file
load_dotenv()

st.set_page_config(page_title="AI Document Scanner", page_icon="📄", layout="wide")

ICONS = {"pdf": "📕", "csv": "📊", "xlsx": "📗", "xls": "📗", "docx": "📘"}


def get_icon(file_type):
    if file_type in ICONS:
        return ICONS[file_type]
    return "📄"


# start the MCP server only one time (st.cache_resource keeps it running)
@st.cache_resource(show_spinner="Starting the MCP server... (first time it can take a minute)")
def start_mcp_server():
    return MCPClient(MCP_SERVER_FILE)


# session state variables
if "messages" not in st.session_state:
    st.session_state.messages = []
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []
if "summaries" not in st.session_state:
    st.session_state.summaries = {}

try:
    mcp = start_mcp_server()
except Exception as e:
    st.error("Could not start the MCP server: " + str(e))
    st.info("Please install the packages with: pip install -r requirements.txt and reload the page.")
    st.stop()


# ======================= SIDEBAR =======================
with st.sidebar:
    st.title("📄 Document Scanner")

    st.subheader("Step 1: Choose AI")
    provider = st.radio("LLM Provider", ["Gemini", "OpenAI"], horizontal=True)

    if provider == "Gemini":
        model_list = GEMINI_MODELS
        default_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        key_link = GEMINI_KEY_LINK
    else:
        model_list = OPENAI_MODELS
        default_key = os.getenv("OPENAI_API_KEY") or ""
        key_link = OPENAI_KEY_LINK

    model = st.selectbox("Model", model_list + ["Other"])
    if model == "Other":
        model = st.text_input("Type the model name", placeholder="example: gpt-4o")

    api_key = st.text_input(provider + " API Key", value=default_key, type="password",
                            help="Get your key here: " + key_link)

    if api_key and model:
        st.success("AI is ready ✅")
    else:
        st.warning(f"Please enter your API key. [Get a key here]({key_link})")

    with st.expander("⚙️ Advanced settings"):
        temperature = st.slider("Temperature", 0.0, 1.0, 0.2, 0.05,
                                help="Low = more exact answers, High = more creative answers")
        top_k = st.slider("Number of passages to search (top k)", 2, 15, TOP_K,
                          help="How many text pieces RAG gives to the AI")
        show_tools = st.checkbox("Show MCP tools used in chat", value=True)

    st.divider()

    # some numbers about the knowledge base
    try:
        docs = mcp.call_tool_json("list_documents")
    except Exception:
        docs = []
    total_chunks = 0
    for d in docs:
        total_chunks += d["chunks"]

    col1, col2 = st.columns(2)
    col1.metric("Documents", len(docs))
    col2.metric("Chunks", total_chunks)
    st.caption(f"🟢 MCP server running ({len(mcp.tools)} tools)")


# make the LLM and the manager agent
llm = None
if api_key and model:
    try:
        llm = make_llm(provider, api_key, model, temperature)
    except Exception as e:
        st.sidebar.error("Could not connect to " + provider + ": " + str(e))

manager = ManagerAgent(mcp, llm, top_k)

doc_names = {}
for d in docs:
    doc_names[d["doc_id"]] = get_icon(d["file_type"]) + " " + d["file_name"]


# ======================= HELPER FUNCTIONS =======================

def save_uploaded_file(uploaded_file):
    # save in a folder named by the file hash, so two files with same name don't clash
    data = uploaded_file.getvalue()
    folder = os.path.join(UPLOAD_DIR, hashlib.md5(data).hexdigest()[:12])
    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, uploaded_file.name)
    with open(file_path, "wb") as f:
        f.write(data)
    return file_path


def show_numbers(doc):
    # show 3 numbers about the document depending on its type
    p = doc.get("profile", {})
    file_type = doc.get("file_type")
    col1, col2, col3 = st.columns(3)
    if file_type == "pdf":
        col1.metric("Pages", p.get("pages", 0))
        col2.metric("Words", p.get("word_count", 0))
        col3.metric("Chunks", doc.get("chunks", 0))
    elif file_type == "docx":
        col1.metric("Paragraphs", p.get("paragraphs", 0))
        col2.metric("Tables", p.get("tables", 0))
        col3.metric("Words", p.get("word_count", 0))
    elif file_type == "csv":
        col1.metric("Rows", p.get("rows", 0))
        col2.metric("Columns", len(p.get("columns", [])))
        col3.metric("Chunks", doc.get("chunks", 0))
    else:
        col1.metric("Sheets", len(p.get("sheets", [])))
        col2.metric("Total rows", p.get("total_rows", 0))
        col3.metric("Chunks", doc.get("chunks", 0))


def show_sources_and_tools(message):
    if message.get("sources"):
        with st.expander(f"📎 Sources ({len(message['sources'])} passages found by RAG)"):
            for s in message["sources"]:
                st.markdown(f"**[{s['id']}] {s['label']}** - score {s['score']:.2f}")
                text = s["text"]
                if len(text) > 600:
                    text = text[:600] + "..."
                st.caption(text)

    if show_tools and message.get("tool_calls"):
        with st.expander(f"🛠️ MCP tools used by the Manager Agent ({len(message['tool_calls'])})"):
            for t in message["tool_calls"]:
                st.markdown(f"**{t['tool']}**")
                st.json(t["arguments"], expanded=False)


def ask_question(question, selected_docs):
    st.session_state.messages.append({"role": "user", "content": question})
    try:
        with st.spinner("Manager Agent is searching your documents..."):
            history = st.session_state.messages[:-1]
            result = manager.ask(question, history, selected_docs)
        st.session_state.messages.append({
            "role": "assistant",
            "content": result["answer"],
            "sources": result["sources"],
            "tool_calls": result["tool_calls"],
        })
    except Exception as e:
        st.session_state.messages.append({"role": "assistant", "content": "⚠️ Error: " + str(e)})


def get_suggestions():
    file_types = []
    for d in docs:
        file_types.append(d["file_type"])

    suggestions = ["Give me a short summary of my documents"]
    if "pdf" in file_types or "docx" in file_types:
        suggestions.append("What are the key points and conclusions?")
        suggestions.append("List any important dates, names or numbers")
    if "csv" in file_types or "xlsx" in file_types or "xls" in file_types:
        suggestions.append("What columns does my data have?")
        suggestions.append("What are the main trends in the data?")
    return suggestions[:4]


# ======================= MAIN PAGE =======================

st.title("📄 AI Document Scanner")
st.write("Upload PDF, Word, Excel or CSV files and ask questions about them.")

col1, col2, col3 = st.columns(3)
col1.info("**Step 1: Choose AI**\n\nSelect Gemini or OpenAI and enter your key in the sidebar.")
col2.info("**Step 2: Upload**\n\nUpload your files in the Upload tab and click Scan.")
col3.info("**Step 3: Ask**\n\nAsk questions about your files in the Chat tab.")

tab1, tab2, tab3, tab4 = st.tabs(["📤 Upload & Scan", "💬 Ask Questions",
                                  f"📚 My Documents ({len(docs)})", "ℹ️ How it works"])


# ---------- TAB 1: Upload ----------
with tab1:
    st.subheader("Upload your documents")
    st.caption("Supported files: PDF, CSV, Excel (xlsx/xls) and Word (docx). You can upload many files at once.")

    files = st.file_uploader("Upload files", type=SUPPORTED_TYPES, accept_multiple_files=True,
                             key="uploader_" + str(st.session_state.uploader_key))

    if files:
        st.write("**Manager Agent will send the files to these agents:**")
        for f in files:
            agent_name, tool_name = manager.find_agent(f.name)
            file_type = f.name.split(".")[-1].lower()
            st.write(f"{get_icon(file_type)} {f.name} → **{agent_name}** (MCP tool: `{tool_name}`)")

        if st.button(f"🔍 Scan {len(files)} file(s)", type="primary", use_container_width=True):
            results = []
            progress = st.progress(0, text="Starting...")
            for i in range(len(files)):
                f = files[i]
                agent_name, tool_name = manager.find_agent(f.name)
                progress.progress(i / len(files), text=f"{agent_name} is reading {f.name}...")
                with st.status(f"Scanning {f.name} with {agent_name}...") as status:
                    try:
                        file_path = save_uploaded_file(f)
                        result = manager.scan_file(file_path)
                        result["ok"] = True
                        status.update(label=f"✅ {f.name} - {result['chunks']} chunks saved", state="complete")
                    except Exception as e:
                        result = {"file_name": f.name, "ok": False, "error": str(e), "routed_to": agent_name}
                        status.update(label=f"❌ {f.name} - {e}", state="error")
                results.append(result)
            progress.progress(1.0, text="Done!")

            st.session_state.scan_results = results
            st.session_state.uploader_key += 1  # this clears the file uploader
            st.rerun()

    # show results of the last scan
    if st.session_state.scan_results:
        good = []
        bad = []
        for r in st.session_state.scan_results:
            if r["ok"]:
                good.append(r)
            else:
                bad.append(r)

        if len(good) > 0:
            st.success(f"🎉 {len(good)} file(s) scanned! Now go to the 💬 Ask Questions tab.")
        for r in bad:
            st.error(f"{r['file_name']} could not be read by {r['routed_to']}: {r['error']}")

        for r in good:
            with st.container(border=True):
                st.markdown(f"#### {get_icon(r['file_type'])} {r['file_name']}  (read by {r['routed_to']})")
                show_numbers(r)
                for w in r.get("warnings", []):
                    st.warning(w)
                with st.expander("See extracted text"):
                    st.text(r.get("preview", "")[:1500])

        if st.button("Clear results"):
            st.session_state.scan_results = []
            st.rerun()
    elif not files:
        st.info("👆 Upload one or more files to start.")


# ---------- TAB 2: Chat ----------
with tab2:
    if len(docs) == 0:
        st.info("No documents yet. Please upload and scan files in the 📤 Upload & Scan tab first.")
    else:
        col1, col2, col3 = st.columns([3, 1, 1])
        selected_docs = col1.multiselect("Search in", options=list(doc_names.keys()),
                                         format_func=lambda doc_id: doc_names[doc_id],
                                         placeholder="All documents (or choose some files)")

        if len(st.session_state.messages) > 0:
            # download chat as a markdown file
            chat_text = ""
            for m in st.session_state.messages:
                chat_text += "**" + m["role"].title() + ":** " + m["content"] + "\n\n"
            col2.download_button("⬇️ Save chat", chat_text,
                                 file_name="chat_" + datetime.now().strftime("%Y%m%d_%H%M") + ".md",
                                 use_container_width=True)
            if col3.button("🗑️ Clear chat", use_container_width=True):
                st.session_state.messages = []
                st.rerun()

        if llm is None:
            st.warning("Please enter your API key in the sidebar to ask questions.")

        # suggestion buttons when chat is empty
        if len(st.session_state.messages) == 0:
            st.write("**Try one of these questions:**")
            suggestions = get_suggestions()
            button_cols = st.columns(2)
            for i in range(len(suggestions)):
                if button_cols[i % 2].button(suggestions[i], key="suggestion_" + str(i),
                                             use_container_width=True, disabled=(llm is None)):
                    ask_question(suggestions[i], selected_docs)
                    st.rerun()

        # show the chat
        for message in st.session_state.messages:
            if message["role"] == "user":
                avatar = "🧑"
            else:
                avatar = "🤖"
            with st.chat_message(message["role"], avatar=avatar):
                st.markdown(message["content"])
                if message["role"] == "assistant":
                    show_sources_and_tools(message)

        question = st.chat_input("Ask a question about your documents...", disabled=(llm is None))
        if question:
            ask_question(question, selected_docs)
            st.rerun()


# ---------- TAB 3: My Documents ----------
with tab3:
    if len(docs) == 0:
        st.info("No documents yet. Scan some files first.")
    else:
        with st.container(border=True):
            st.write("**🔎 Quick search** (only RAG search, no API key needed)")
            search_text = st.text_input("Search", placeholder="example: payment terms, total revenue, email",
                                        label_visibility="collapsed")
            if search_text:
                hits = manager.search(search_text, top_k=top_k)
                if len(hits) == 0:
                    st.caption("Nothing found.")
                for hit in hits:
                    st.markdown(f"**{make_source_label(hit['metadata'])}** - score {hit['score']:.2f}")
                    st.caption(hit["text"][:500])

        st.write("")
        for d in docs:
            title = f"{get_icon(d['file_type'])} **{d['file_name']}** - read by {d['agent']} - {d['chunks']} chunks"
            with st.expander(title):
                info = manager.get_document_info(d["doc_id"])
                show_numbers(info)
                p = info.get("profile", {})

                if p.get("headings"):
                    st.write("**Headings:** " + " · ".join(p["headings"][:15]))
                if p.get("columns"):
                    st.write("**Columns:** " + ", ".join(p["columns"]))
                if p.get("sheet_details"):
                    for sheet_name in p["sheet_details"]:
                        sheet = p["sheet_details"][sheet_name]
                        st.write(f"**Sheet {sheet_name}** - {sheet['rows']} rows - columns: " + ", ".join(sheet["columns"]))
                for w in info.get("warnings", []):
                    st.warning(w)

                b1, b2, b3 = st.columns([1, 1, 3])
                if b1.button("✨ Summarize", key="sum_" + d["doc_id"], disabled=(llm is None)):
                    with st.spinner("Making summary..."):
                        try:
                            result = manager.ask("Give a clear, well-structured summary of '" + d["file_name"] + "'.",
                                                 doc_ids=[d["doc_id"]])
                            st.session_state.summaries[d["doc_id"]] = result["answer"]
                        except Exception as e:
                            st.session_state.summaries[d["doc_id"]] = "⚠️ Error: " + str(e)
                if b2.button("🗑️ Delete", key="del_" + d["doc_id"]):
                    manager.delete_document(d["doc_id"])
                    st.session_state.summaries.pop(d["doc_id"], None)
                    st.toast("Deleted " + d["file_name"])
                    st.rerun()

                if d["doc_id"] in st.session_state.summaries:
                    st.markdown(st.session_state.summaries[d["doc_id"]])

                if st.checkbox("Show extracted text", key="preview_" + d["doc_id"]):
                    st.text(info.get("preview", "")[:1500])


# ---------- TAB 4: How it works ----------
with tab4:
    st.subheader("How my project works")

    st.graphviz_chart("""
    digraph {
        rankdir=LR
        node [shape=box, style="rounded,filled", fillcolor=lightblue]
        User [label="User\\n(Streamlit)", fillcolor=lightyellow]
        Manager [label="Manager Agent"]
        LLM [label="LLM\\n(Gemini / OpenAI)", fillcolor=lightgreen]
        MCP [label="MCP Server", fillcolor=plum]
        PDF [label="PDFReaderAgent"]
        CSV [label="CSVReaderAgent"]
        Excel [label="ExcelReaderAgent"]
        Word [label="WordReaderAgent"]
        DB [label="ChromaDB\\n(vector database)", fillcolor=pink]
        User -> Manager
        Manager -> LLM [label="question + passages"]
        LLM -> Manager [label="tool calls"]
        Manager -> MCP [label="MCP tool calls"]
        MCP -> PDF
        MCP -> CSV
        MCP -> Excel
        MCP -> Word
        PDF -> DB
        CSV -> DB
        Excel -> DB
        Word -> DB
        MCP -> DB [label="search"]
    }
    """)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
**When you scan a file:**
1. The **Manager Agent** checks the file type and picks the right agent.
2. It calls that agent using an **MCP tool** (read_pdf, read_csv, read_excel, read_docx).
3. The agent reads the file, cuts the text into small chunks and saves them in **ChromaDB**.

**When you ask a question (RAG):**
1. **Retrieve** - find the most similar chunks with the MCP tool `search_documents`.
2. **Augment** - add those chunks to the prompt.
3. **Generate** - the LLM writes the answer with sources like [S1]. It can also call
   more MCP tools, for example to calculate exact totals from an Excel file.
""")
    with col2:
        st.markdown("**MCP tools in my server:**")
        for tool in mcp.tools:
            if tool["name"] in INTERNAL_TOOLS:
                used_by = "used by the app"
            else:
                used_by = "used by the LLM"
            first_line = tool["description"].split("\n")[0]
            st.markdown(f"- `{tool['name']}` - {first_line} ({used_by})")

        st.markdown("**Which agent reads which file:**")
        table = "| File type | Agent | MCP tool |\n|---|---|---|\n"
        for ext in AGENT_ROUTES:
            table += f"| {ext} | {AGENT_ROUTES[ext][0]} | {AGENT_ROUTES[ext][1]} |\n"
        st.markdown(table)
