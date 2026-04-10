"""Document chunking for RAG pipeline."""

from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from docx import Document as DocxDocument
from config import CHUNK_SIZE, CHUNK_OVERLAP


def extract_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(file_path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        doc = DocxDocument(str(file_path))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    elif suffix in (".txt", ".md"):
        return file_path.read_text(encoding="utf-8")
    else:
        return file_path.read_text(encoding="utf-8", errors="ignore")


def chunk_text(text: str, source: str = "") -> list[dict]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_text(text)
    return [
        {"text": chunk, "source": source, "chunk_index": i}
        for i, chunk in enumerate(chunks)
        if chunk.strip()
    ]


def process_file(file_path: Path) -> list[dict]:
    text = extract_text(file_path)
    return chunk_text(text, source=file_path.name)
