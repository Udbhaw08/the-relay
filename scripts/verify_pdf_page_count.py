"""
Compile docs/SUBMISSION_REPORT.tex to PDF via Tectonic LaTeX engine,
and verify that page count is strictly <= 2 pages using pypdf.
"""
import subprocess
from pathlib import Path
import pypdf

ROOT = Path(__file__).resolve().parent.parent
TEX_PATH = ROOT / "docs" / "SUBMISSION_REPORT.tex"
PDF_PATH = ROOT / "docs" / "SUBMISSION_REPORT.pdf"
TECTONIC_EXE = ROOT / "scripts" / "bin" / "tectonic.exe"

def compile_tex_to_pdf(tex_path: Path, out_dir: Path):
    if TECTONIC_EXE.exists():
        print(f"[LaTeX] Compiling {tex_path.name} via Tectonic ({TECTONIC_EXE})...")
        cmd = [str(TECTONIC_EXE), "-o", str(out_dir), str(tex_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[LaTeX Warning] Tectonic output:\n{res.stderr or res.stdout}")
        else:
            print(f"[LaTeX] Successfully compiled {tex_path.name} to {PDF_PATH.name}")
    else:
        # Fallback to system tectonic if in PATH
        print(f"[LaTeX] Compiling {tex_path.name} via system tectonic...")
        cmd = ["tectonic", "-o", str(out_dir), str(tex_path)]
        subprocess.run(cmd, check=True)

def verify_pdf_pages(pdf_path: Path) -> int:
    reader = pypdf.PdfReader(str(pdf_path))
    num_pages = len(reader.pages)
    print(f"[Verification] PDF Page Count: {num_pages}")
    if num_pages <= 2:
        print(f"[SUCCESS] Submission report strictly complies with <= 2 pages! (Found: {num_pages} pages)")
    else:
        print(f"[WARNING] PDF is {num_pages} pages (> 2 pages). Adjust styling.")
    return num_pages

if __name__ == "__main__":
    compile_tex_to_pdf(TEX_PATH, ROOT / "docs")
    pages = verify_pdf_pages(PDF_PATH)
    if pages > 2:
        exit(1)
