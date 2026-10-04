# pdf_agent.py
# PDFReaderAgent - reads text from pdf files page by page

from pypdf import PdfReader

from agents.base_agent import BaseAgent


class PDFReaderAgent(BaseAgent):
    name = "PDFReaderAgent"
    extensions = [".pdf"]

    def read_file(self, file_path):
        reader = PdfReader(file_path)
        warnings = []

        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise Exception("This PDF is password protected.")

        sections = []
        empty_pages = 0
        word_count = 0
        page_number = 1
        for page in reader.pages:
            text = page.extract_text()
            if text is None or text.strip() == "":
                empty_pages += 1
            else:
                text = text.strip()
                word_count += len(text.split())
                sections.append({"text": text, "info": {"page": page_number}})
            page_number += 1

        if empty_pages > 0:
            warnings.append(f"{empty_pages} page(s) had no text (maybe they are scanned images).")

        # title and author if the pdf has them
        title = None
        author = None
        if reader.metadata:
            title = reader.metadata.get("/Title")
            author = reader.metadata.get("/Author")

        profile = {
            "pages": len(reader.pages),
            "pages_with_text": len(sections),
            "word_count": word_count,
            "title": str(title) if title else None,
            "author": str(author) if author else None,
        }
        return sections, profile, warnings
