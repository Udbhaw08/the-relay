"""Module to extract structured text and metadata from research paper PDFs."""
import re
from pathlib import Path
from pydantic import BaseModel
from pypdf import PdfReader
from the_relay.config import REQUIRED_PAPERS, PAPERS_DIR

class PaperPage(BaseModel):
    paper_id: str
    paper_title: str
    page_number: int  # 1-indexed
    text: str
    headings: list[str] = []

class StructuredDocument(BaseModel):
    paper_id: str
    paper_title: str
    pages: list[PaperPage]
    full_text: str

def clean_text(raw: str) -> str:
    """Normalize whitespace and remove non-printable characters."""
    # Remove hyphenation at line breaks
    text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", raw)
    # Replace multiple newlines / spaces with single clean space/newline
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def extract_headings(page_text: str) -> list[str]:
    """Simple heuristic to detect academic section headings (e.g. '3.2 Multi-Head Attention')."""
    heading_pattern = re.compile(r"^(?:[0-9]+\.[0-9]*|[A-Z][0-9]*\.)\s+[A-Z][A-Za-z0-9\s\-]+", re.MULTILINE)
    matches = heading_pattern.findall(page_text)
    return [m.strip() for m in matches if len(m.strip()) < 80]

def parse_paper_pdf(pdf_path: Path, paper_id: str) -> StructuredDocument:
    """Parse a single PDF into structured pages and text."""
    meta = REQUIRED_PAPERS.get(paper_id, {"title": pdf_path.stem})
    reader = PdfReader(str(pdf_path))
    pages: list[PaperPage] = []
    full_text_parts = []

    for idx, page in enumerate(reader.pages):
        raw_text = page.extract_text() or ""
        cleaned = clean_text(raw_text)
        headings = extract_headings(cleaned)
        
        page_obj = PaperPage(
            paper_id=paper_id,
            paper_title=meta["title"],
            page_number=idx + 1,
            text=cleaned,
            headings=headings
        )
        pages.append(page_obj)
        full_text_parts.append(f"--- [Page {idx + 1}] ---\n{cleaned}")

    return StructuredDocument(
        paper_id=paper_id,
        paper_title=meta["title"],
        pages=pages,
        full_text="\n\n".join(full_text_parts)
    )

def parse_all_papers(papers_dir: Path = PAPERS_DIR) -> dict[str, StructuredDocument]:
    """Parse all required papers in the directory."""
    docs = {}
    for paper_id, meta in REQUIRED_PAPERS.items():
        pdf_path = papers_dir / meta["filename"]
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF {pdf_path} not found. Run fetcher first.")
        docs[paper_id] = parse_paper_pdf(pdf_path, paper_id)
    return docs

