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

# Load environment
load_dotenv(ROOT_DIR / ".env")

# Provider settings
PRIMARY_PROVIDER = os.getenv("PRIMARY_PROVIDER", "gemini").lower()
FALLBACK_PROVIDER = os.getenv("FALLBACK_PROVIDER", "nvidia").lower()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

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
        "description": "Small chunks, top-3, no re-ranking (fast, low cost)"
    },
    "setting_b": {
        "piece_size": 500,       # tokens (~2000 characters)
        "pieces_fetched": 5,
        "rerank": True,
        "description": "Medium chunks, top-5, hybrid re-ranking (balanced quality)"
    },
    "setting_c": {
        "piece_size": 1000,      # tokens (~4000 characters)
        "pieces_fetched": 7,
        "rerank": True,
        "description": "Large chunks, top-7, deep re-ranking (high recall, high tokens)"
    }
}

DEFAULT_SETTING = os.getenv("DEFAULT_RETRIEVAL_SETTING", "setting_b")

# Limits & Resilience parameters
# Real Free Tier limits (Gemini 2.0 Flash / 1.5 Flash)
GEMINI_RPM_LIMIT = 15
GEMINI_RPD_LIMIT = 1500
GEMINI_TPM_LIMIT = 1000000

# NVIDIA NIM limits
NVIDIA_RPM_LIMIT = 40

# Client timeout & retry settings
REQUEST_TIMEOUT_SECONDS = 15.0
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
BASE_BACKOFF_SECONDS = 2.0

