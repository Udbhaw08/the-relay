"""Module to fetch required arXiv papers at exact specified versions."""
import os
import urllib.request
import time
from pathlib import Path
from the_relay.config import REQUIRED_PAPERS, PAPERS_DIR

def fetch_paper(arxiv_id: str, dest_dir: Path = PAPERS_DIR) -> Path:
    """Download an arXiv paper if it does not already exist."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    if arxiv_id not in REQUIRED_PAPERS:
        raise ValueError(f"Unknown paper arxiv_id: {arxiv_id}")

    meta = REQUIRED_PAPERS[arxiv_id]
    target_path = dest_dir / meta["filename"]

    if target_path.exists() and target_path.stat().st_size > 10000:
        return target_path

    url = meta["url"]
    print(f"[Fetcher] Downloading {meta['title']} ({arxiv_id}) from {url}...")
    headers = {"User-Agent": "TheRelay-Benchmark/1.0 (academic research)"}
    req = urllib.request.Request(url, headers=headers)
    
    with urllib.request.urlopen(req, timeout=30) as resp:
        content = resp.read()
        if not content.startswith(b"%PDF"):
            raise RuntimeError(f"Fetched content from {url} is not a valid PDF")
        with open(target_path, "wb") as f:
            f.write(content)

    print(f"[Fetcher] Saved {meta['filename']} ({len(content) / 1024:.1f} KB)")
    return target_path

def fetch_all_papers(dest_dir: Path = PAPERS_DIR) -> dict[str, Path]:
    """Download all 3 required research papers."""
    results = {}
    for arxiv_id in REQUIRED_PAPERS:
        results[arxiv_id] = fetch_paper(arxiv_id, dest_dir)
        time.sleep(0.5)  # Be polite to arXiv export
    return results

if __name__ == "__main__":
    fetch_all_papers()

