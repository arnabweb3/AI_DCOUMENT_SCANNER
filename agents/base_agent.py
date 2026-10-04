# base_agent.py
# Parent class for all my reader agents (PDF, CSV, Excel, Word)

import hashlib
import os

from rag.chunker import split_text


def get_doc_id(file_path):
    # make an id from the file content, so the same file always gets the same id
    with open(file_path, "rb") as f:
        content = f.read()
    return hashlib.md5(content).hexdigest()[:12]


class BaseAgent:
    name = "BaseAgent"
    extensions = []
    split_into_chunks = True  # csv/excel agents set this to False because rows are already small

    def read_file(self, file_path):
        # every child agent has to write this function
        # it must return 3 things: sections, profile, warnings
        # a section is a dict like {"text": "...", "info": {"page": 1}}
        raise NotImplementedError("Child agent must write read_file()")

    def run(self, file_path):
        if not os.path.exists(file_path):
            raise Exception("File not found: " + file_path)

        extension = os.path.splitext(file_path)[1].lower()
        if extension not in self.extensions:
            raise Exception(self.name + " cannot read " + extension + " files")

        sections, profile, warnings = self.read_file(file_path)
        file_name = os.path.basename(file_path)

        # make chunks from the sections
        chunks = []
        for section in sections:
            if self.split_into_chunks:
                pieces = split_text(section["text"])
            else:
                pieces = [section["text"].strip()]

            for piece in pieces:
                if piece == "":
                    continue
                metadata = dict(section["info"])
                metadata["file_name"] = file_name
                metadata["agent"] = self.name
                chunks.append({"text": piece, "metadata": metadata})

        # small preview to show in the app
        all_text = ""
        for section in sections:
            all_text = all_text + section["text"] + "\n\n"
        preview = all_text[:1500]

        if len(chunks) == 0:
            warnings.append("No readable text was found in this file.")

        return {
            "doc_id": get_doc_id(file_path),
            "file_name": file_name,
            "file_type": extension.replace(".", ""),
            "agent": self.name,
            "chunks": chunks,
            "profile": profile,
            "preview": preview,
            "warnings": warnings,
        }
