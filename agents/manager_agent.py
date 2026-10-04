# manager_agent.py
# ManagerAgent - the main agent of the project.
# 1. It decides which reader agent should read a file (routing)
# 2. It answers questions using RAG:
#       Retrieve  -> get matching passages with the MCP "search_documents" tool
#       Augment   -> put the passages in the prompt
#       Generate  -> LLM writes the answer (and can call more MCP tools)

import json
import os

from config import AGENT_ROUTES, INTERNAL_TOOLS

SYSTEM_PROMPT = """You are the Manager Agent of an AI Document Scanner.
You work with these agents: PDFReaderAgent, CSVReaderAgent, ExcelReaderAgent and WordReaderAgent.
They have already read the user's documents into a knowledge base.

Rules:
- Answer only using the retrieved passages and tool results. Cite passages like [S1], [S2].
- If the passages are not enough, call search_documents again with a better query.
- For number questions on CSV/Excel files (total, average, count, top, filter) ALWAYS use
  describe_table, aggregate_table or filter_table to get exact numbers. Do not guess.
- If the answer is not in the documents, say that clearly. Do not make up facts.
- Keep answers short and use Markdown (bullet points, tables) when it helps.

Documents in the knowledge base:
"""


def make_source_label(metadata):
    # makes a label like "report.pdf · page 3"
    label = metadata.get("file_name", "unknown")
    if "page" in metadata:
        label += " · page " + str(metadata["page"])
    if metadata.get("sheet") and metadata.get("sheet") != "data":
        label += " · sheet '" + str(metadata["sheet"]) + "'"
    if "rows" in metadata:
        label += " · rows " + str(metadata["rows"])
    if metadata.get("section") and "page" not in metadata:
        label += " · " + str(metadata["section"])[:60]
    return label


class ManagerAgent:
    def __init__(self, mcp, llm=None, top_k=6):
        self.mcp = mcp
        self.llm = llm
        self.top_k = top_k

    # ---------- routing ----------

    def find_agent(self, file_name):
        # returns (agent name, mcp tool name)
        extension = os.path.splitext(file_name)[1].lower()
        if extension not in AGENT_ROUTES:
            raise Exception("This file type is not supported: " + extension)
        return AGENT_ROUTES[extension]

    def scan_file(self, file_path):
        agent_name, tool_name = self.find_agent(file_path)
        result = self.mcp.call_tool_json(tool_name, {"file_path": file_path})
        result["routed_to"] = agent_name
        result["mcp_tool"] = tool_name
        return result

    # ---------- documents ----------

    def list_documents(self):
        return self.mcp.call_tool_json("list_documents")

    def get_document_info(self, doc_id):
        return self.mcp.call_tool_json("get_document_info", {"doc_id": doc_id})

    def delete_document(self, doc_id):
        return self.mcp.call_tool_json("delete_document", {"doc_id": doc_id})

    def search(self, query, doc_ids=None, top_k=None):
        if top_k is None:
            top_k = self.top_k
        if not doc_ids:
            doc_ids = None
        return self.mcp.call_tool_json("search_documents", {"query": query, "top_k": top_k, "doc_ids": doc_ids})

    # ---------- question answering ----------

    def get_llm_tools(self):
        # give the LLM all MCP tools except the internal ones
        tools = []
        for tool in self.mcp.tools:
            if tool["name"] not in INTERNAL_TOOLS:
                tools.append(tool)
        return tools

    def basic_answer(self, sources, note):
        # used when there is no API key (or the LLM fails)
        # we just show the best matching passages from RAG search
        if len(sources) == 0:
            return note + "\n\nI could not find anything about this in your documents."

        answer = note + "\n\nHere are the most relevant parts of your documents:\n\n"
        for source in sources[:3]:
            text = source["text"]
            if len(text) > 500:
                text = text[:500] + "..."
            text = text.replace("\n", "\n> ")
            answer += f"**[{source['id']}] {source['label']}**\n> {text}\n\n"
        return answer

    def ask(self, question, history=None, doc_ids=None):
        if history is None:
            history = []

        # Step 1: Retrieve
        hits = self.search(question, doc_ids)
        sources = []
        context = ""
        number = 1
        for hit in hits:
            source = {
                "id": "S" + str(number),
                "label": make_source_label(hit["metadata"]),
                "score": hit["score"],
                "text": hit["text"],
                "doc_id": hit["metadata"].get("doc_id"),
            }
            sources.append(source)
            context += "[" + source["id"] + "] (" + source["label"] + ")\n" + hit["text"] + "\n\n"
            number += 1
        if context == "":
            context = "No passages matched."

        # no API key -> basic mode (only RAG search, no LLM)
        if self.llm is None:
            note = "ℹ️ **Basic mode** (no API key) - add an API key in the sidebar to get AI-written answers."
            return {"answer": self.basic_answer(sources, note), "sources": sources, "tool_calls": []}

        # Step 2: Augment (make the prompt)
        system_prompt = SYSTEM_PROMPT
        for doc in self.list_documents():
            if doc_ids and doc["doc_id"] not in doc_ids:
                continue
            system_prompt += f"- {doc['file_name']} (doc_id={doc['doc_id']}, type={doc['file_type']}, read by {doc['agent']})\n"
        if doc_ids:
            system_prompt += "\nOnly use these documents: " + ", ".join(doc_ids) + " (pass them as doc_ids when searching)."

        # last few chat messages so the LLM remembers the conversation
        messages = []
        for m in history[-8:]:
            if m["role"] in ["user", "assistant"]:
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": "Retrieved passages:\n" + context + "\nQuestion: " + question})

        # this function runs a tool when the LLM asks for it
        def run_tool(name, args):
            if name in INTERNAL_TOOLS:
                return json.dumps({"error": "Tool " + name + " is not allowed."})
            if name == "search_documents" and doc_ids and not args.get("doc_ids"):
                args["doc_ids"] = doc_ids
            return self.mcp.call_tool(name, args)

        # Step 3: Generate
        try:
            answer, tools_used = self.llm.ask(system_prompt, messages, self.get_llm_tools(), run_tool)
        except Exception as e:
            # if the key is wrong or the quota is finished, still give an answer in basic mode
            note = "⚠️ The AI could not answer (" + str(e)[:150] + "), so here is the **basic mode** answer."
            return {"answer": self.basic_answer(sources, note), "sources": sources, "tool_calls": []}
        answer = answer.strip()
        if answer == "":
            answer = "_(No answer returned.)_"
        return {"answer": answer, "sources": sources, "tool_calls": tools_used}
