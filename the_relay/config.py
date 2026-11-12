"""Configuration management for The Relay."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PAPERS_DIR = DATA_DIR / "papers"
PARSED_DIR = DATA_DIR / "parsed"
RESULTS_PATH = ROOT_DIR / "results.csv"

# Load environment (.env is excluded from Git)
load_dotenv(ROOT_DIR / ".env")

# Provider settings - GroqCloud API is the ONLY real LLM provider
# Stand-in is kept exclusively for explicitly selected offline tests (LLM_PROVIDER=standin)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", os.getenv("PRIMARY_PROVIDER", "groq")).lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Default verified production model for GroqCloud (llama-3.3-70b-versatile decommissioned August 16, 2026)
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
RETIRED_MODELS = {"llama-3.3-70b-versatile"}

# The 3 specific arXiv papers required by the assignment brief
REQUIRED_PAPERS = {
    "1706.03762v7": {
        "title": "Attention Is All You Need",
        "arxiv_id": "1706.03762v7",
        "url": "https://arxiv.org/pdf/1706.03762v7.pdf",
        "filename": "1706.03762v7.pdf"
    },
    "2410.00037v1": {
        "title": "Moshi: a speech-text foundation model for real-time dialogue",
        "arxiv_id": "2410.00037v1",
        "url": "https://arxiv.org/pdf/2410.00037v1.pdf",
        "filename": "2410.00037v1.pdf"
    },
    "2507.07955v2": {
        "title": "Dynamic Chunking for End-to-End Hierarchical Sequence Modeling",
        "arxiv_id": "2507.07955v2",
        "url": "https://arxiv.org/pdf/2507.07955v2.pdf",
        "filename": "2507.07955v2.pdf"
    }
}

# Retrieval settings for experiments (Table 3)
RETRIEVAL_SETTINGS = {
    "setting_a": {
        "piece_size": 250,       # tokens (~1000 characters)
        "pieces_fetched": 3,
        "rerank": False,
        "mode": "bm25_only",     # Fast BM25-only retrieval
        "description": "Small chunks, top-3, BM25-only, no re-ranking (fast, low cost)"
    },
    "setting_b": {
        "piece_size": 500,       # tokens (~2000 characters)
        "pieces_fetched": 5,
        "rerank": True,
        "mode": "hybrid",        # True hybrid: BM25 + Dense Embeddings + RRF
        "description": "Medium chunks, top-5, true hybrid (BM25 + Dense + RRF)"
    },
    "setting_c": {
        "piece_size": 1000,      # tokens (~4000 characters)
        "pieces_fetched": 7,
        "rerank": True,
        "mode": "hybrid",        # Deep hybrid: BM25 + Dense Embeddings + RRF
        "description": "Large chunks, top-7, deep hybrid (BM25 + Dense + RRF)"
    }
}

DEFAULT_SETTING = os.getenv("DEFAULT_RETRIEVAL_SETTING", "setting_b")

# Client timeout & retry settings
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "15.0"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
BASE_BACKOFF_SECONDS = float(os.getenv("BASE_BACKOFF_SECONDS", "2.0"))

def validate_groq_config():
    """Startup validation: verify that GROQ_API_KEY is present and GROQ_MODEL is valid when in Groq mode."""
    if LLM_PROVIDER in ("groq", "real"):
        if not GROQ_API_KEY or not GROQ_API_KEY.strip():
            raise ValueError(
                "GROQ_API_KEY is not set or is empty. Please set GROQ_API_KEY in your environment or .env file."
            )
        if not GROQ_MODEL or not GROQ_MODEL.strip():
            raise ValueError(
                "GROQ_MODEL is not set or is empty. Please set GROQ_MODEL in your environment or .env file."
            )
        if GROQ_MODEL in RETIRED_MODELS:
            raise ValueError(
                f"Configured model '{GROQ_MODEL}' is decommissioned on GroqCloud Free tier. "
                f"Please update GROQ_MODEL to a supported production model such as 'openai/gpt-oss-20b'."
            )
