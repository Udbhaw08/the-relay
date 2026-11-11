"""Configurable chunker for research papers supporting Settings A, B, and C."""
import math
import re
from pydantic import BaseModel
from the_relay.ingestion.parser import StructuredDocument

class Chunk(BaseModel):
    chunk_id: str
    paper_id: str
    paper_title: str
    page_number: int
    section: str
    text: str
    token_count: int

def estimate_tokens(text: str) -> int:
    """Approximate token count (1 token ≈ 4 characters or 0.75 words)."""
    words = len(text.split())
    chars = len(text)
    return max(1, int(max(words * 1.3, chars / 4.0)))

def chunk_document(doc: StructuredDocument, target_tokens: int = 500, overlap_fraction: float = 0.15) -> list[Chunk]:
    """
    Chunk document by target token length with semantic boundary preservation
    (pages and section headings).
    """
    chunks: list[Chunk] = []
    chunk_counter = 0

    for page in doc.pages:
        current_section = page.headings[0] if page.headings else "General"
        # Split page text into paragraphs
        paragraphs = [p.strip() for p in page.text.split("\n\n") if p.strip()]
        
        current_text = ""
        current_tokens = 0
        
        for para in paragraphs:
            # Check if this paragraph contains a section header
            for h in page.headings:
                if h in para:
                    current_section = h
                    break
            
            para_tokens = estimate_tokens(para)
            
            if current_tokens + para_tokens <= target_tokens:
                current_text = f"{current_text}\n\n{para}".strip()
                current_tokens += para_tokens
            else:
                # If current_text has content, store it
                if current_text:
                    chunk_counter += 1
                    cid = f"{doc.paper_id}_p{page.page_number}_c{chunk_counter}"
                    chunks.append(Chunk(
                        chunk_id=cid,
                        paper_id=doc.paper_id,
                        paper_title=doc.paper_title,
                        page_number=page.page_number,
                        section=current_section,
                        text=current_text,
                        token_count=current_tokens
                    ))
                
                # Overlap logic: keep the last sentence/part if possible
                if para_tokens > target_tokens:
                    # Paragraph itself is larger than target_tokens; split by sentences
                    sentences = re.split(r"(?<=[.!?])\s+", para)
                    sub_text = ""
                    sub_tokens = 0
                    for sent in sentences:
                        sent_tokens = estimate_tokens(sent)
                        if sub_tokens + sent_tokens > target_tokens and sub_text:
                            chunk_counter += 1
                            cid = f"{doc.paper_id}_p{page.page_number}_c{chunk_counter}"
                            chunks.append(Chunk(
                                chunk_id=cid,
                                paper_id=doc.paper_id,
                                paper_title=doc.paper_title,
                                page_number=page.page_number,
                                section=current_section,
                                text=sub_text,
                                token_count=sub_tokens
                            ))
                            sub_text = sent
                            sub_tokens = sent_tokens
                        else:
                            sub_text = f"{sub_text} {sent}".strip()
                            sub_tokens += sent_tokens
                    current_text = sub_text
                    current_tokens = sub_tokens
                else:
                    current_text = para
                    current_tokens = para_tokens

        # Flush trailing text on page
        if current_text:
            chunk_counter += 1
            cid = f"{doc.paper_id}_p{page.page_number}_c{chunk_counter}"
            chunks.append(Chunk(
                chunk_id=cid,
                paper_id=doc.paper_id,
                paper_title=doc.paper_title,
                page_number=page.page_number,
                section=current_section,
                text=current_text,
                token_count=current_tokens
            ))

    return chunks

def build_chunk_indices(docs: dict[str, StructuredDocument], target_tokens: int) -> list[Chunk]:
    """Build all chunks across all parsed papers for a given target token size."""
    all_chunks: list[Chunk] = []
    for doc in docs.values():
        all_chunks.extend(chunk_document(doc, target_tokens=target_tokens))
    return all_chunks

