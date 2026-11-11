"""Script to fetch exact Mermaid Dagre rendered SVG and high-res PNG matching Image 2."""
import base64
import urllib.request
from pathlib import Path

code = """flowchart TD
    UserReq([Incoming Question]) --> IngressQueue[Priority Queue & Concurrency Gate]
    
    subgraph Pipeline["The Relay Pipeline (4 Steps + Tool Call + Loop)"]
        IngressQueue --> Step1[Step 1: Query Parser & Intent Decomposer]
        Step1 --> ToolCall[Tool Call: retrieve_passages]
        ToolCall --> Step2[Step 2: Hybrid Paper Retrieval BM25 + Dense]
        Step2 --> Step3[Step 3: Synthesis & Citation Drafter]
        Step3 --> Step4[Step 4: Verification & Hallucination Guard]
        Step4 -- Citation Missing / Hallucination Detected --> LoopBack[Loop: Broaden Query / Refine Retrieval]
        LoopBack --> Step2
        Step4 -- Citation Verified --> Reply[Final Verified Answer with Citations]
        Step4 -- Unanswerable in Papers --> Refusal[Explicit Refusal: Papers do not say]
    end

    subgraph LLM_Layer["Model Provider Layer"]
        Step1 & Step3 & Step4 --> Router{Source Selector}
        Router -- Real Mode --> GroqClient[Groq Cloud API Client]
        Router -- Stand-in Mode --> StandInClient[Calibrated Stand-in Simulator]
        GroqClient --> Telemetry[Rate Limit Header Parser & Latency Profiler]
        StandInClient --> Telemetry
    end

    Telemetry --> CSVLogger[(results.csv Logger)]
    CSVLogger --> TableGenerator[compute_tables.py -> Tables 1, 2a, 2b, 3]"""

b64_code = base64.b64encode(code.encode("utf-8")).decode("ascii")

# 1. Fetch exact dark theme SVG
svg_url = f"https://mermaid.ink/svg/{b64_code}"
print("Fetching SVG from mermaid.ink...")
req_svg = urllib.request.Request(svg_url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req_svg, timeout=20) as resp:
    svg_content = resp.read()
    Path("docs/architecture_diagram.svg").write_bytes(svg_content)
    print(f"Saved exact SVG ({len(svg_content)} bytes)")

# 2. Fetch high-res PNG (scale=2) for universal display in any editor
png_url = f"https://mermaid.ink/img/{b64_code}?scale=2"
print("Fetching PNG from mermaid.ink...")
req_png = urllib.request.Request(png_url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req_png, timeout=20) as resp:
    png_content = resp.read()
    Path("docs/architecture_diagram.png").write_bytes(png_content)
    print(f"Saved exact PNG ({len(png_content)} bytes)")
