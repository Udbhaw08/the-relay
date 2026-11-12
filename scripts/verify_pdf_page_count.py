"""
Render docs/SUBMISSION_REPORT.md to HTML and PDF via headless Edge,
and verify that page count is strictly <= 2 pages using pypdf.
"""
import re
import html
import subprocess
from pathlib import Path
import pypdf

ROOT = Path(__file__).resolve().parent.parent
MD_PATH = ROOT / "docs" / "SUBMISSION_REPORT.md"
HTML_PATH = ROOT / "docs" / "SUBMISSION_REPORT.html"
PDF_PATH = ROOT / "docs" / "SUBMISSION_REPORT.pdf"
EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

def parse_markdown_to_html(md_text: str) -> str:
    lines = md_text.splitlines()
    html_out = []
    in_table = False
    table_rows = []

    def flush_table():
        nonlocal in_table, table_rows
        if not table_rows:
            in_table = False
            return ""
        out = ["<table>"]
        # Determine header vs body
        header = table_rows[0]
        out.append("<thead><tr>")
        for cell in header:
            out.append(f"<th>{cell}</th>")
        out.append("</tr></thead>")
        out.append("<tbody>")
        for row in table_rows[1:]:
            out.append("<tr>")
            for cell in row:
                out.append(f"<td>{cell}</td>")
            out.append("</tr>")
        out.append("</tbody></table>")
        table_rows = []
        in_table = False
        return "\n".join(out)

    for line in lines:
        sline = line.strip()

        # Table rows
        if sline.startswith("|") and sline.endswith("|"):
            parts = [c.strip() for c in sline[1:-1].split("|")]
            # Check if separator row (e.g. :--- | :---)
            if all(re.match(r"^:?-+:?$", p) for p in parts if p):
                continue
            # Format inline code and bold in cells
            formatted_parts = []
            for p in parts:
                p_esc = html.escape(p)
                p_esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", p_esc)
                p_esc = re.sub(r"`(.+?)`", r"<code>\1</code>", p_esc)
                formatted_parts.append(p_esc)
            in_table = True
            table_rows.append(formatted_parts)
            continue
        elif in_table:
            html_out.append(flush_table())

        if not sline:
            continue

        if sline == "---":
            html_out.append("<hr>")
            continue

        if sline.startswith("# "):
            title = html.escape(sline[2:].strip())
            html_out.append(f"<h1>{title}</h1>")
            continue
        if sline.startswith("## "):
            h2 = html.escape(sline[3:].strip())
            html_out.append(f"<h2>{h2}</h2>")
            continue
        if sline.startswith("### "):
            h3 = html.escape(sline[4:].strip())
            html_out.append(f"<h3>{h3}</h3>")
            continue
        if sline.startswith("#### "):
            h4 = html.escape(sline[5:].strip())
            html_out.append(f"<h4>{h4}</h4>")
            continue

        if sline.startswith("> "):
            bq = html.escape(sline[2:].strip())
            bq = re.sub(r"\*(.+?)\*", r"<em>\1</em>", bq)
            bq = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", bq)
            html_out.append(f"<blockquote>{bq}</blockquote>")
            continue

        if sline.startswith("- "):
            li = html.escape(sline[2:].strip())
            li = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", li)
            li = re.sub(r"`(.+?)`", r"<code>\1</code>", li)
            html_out.append(f"<ul><li>{li}</li></ul>")
            continue

        if re.match(r"^\d+\.\s+", sline):
            num_li = re.sub(r"^\d+\.\s+", "", sline)
            num_li = html.escape(num_li)
            num_li = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", num_li)
            num_li = re.sub(r"`(.+?)`", r"<code>\1</code>", num_li)
            html_out.append(f"<ol><li>{num_li}</li></ol>")
            continue

        # Normal paragraph
        p = html.escape(sline)
        p = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", p)
        p = re.sub(r"\*(.+?)\*", r"<em>\1</em>", p)
        p = re.sub(r"`(.+?)`", r"<code>\1</code>", p)
        p = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', p)
        html_out.append(f"<p>{p}</p>")

    if in_table:
        html_out.append(flush_table())

    return "\n".join(html_out)

def render_md_to_html(md_path: Path, html_path: Path):
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    body = parse_markdown_to_html(text)

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
    size: letter;
    margin: 0.35in 0.4in;
}}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 8.0pt;
    line-height: 1.22;
    color: #111;
    margin: 0;
    padding: 0;
}}
h1 {{
    font-size: 12pt;
    margin: 0 0 3px 0;
    line-height: 1.15;
    color: #0b2545;
}}
h2 {{
    font-size: 9.0pt;
    margin: 5px 0 2px 0;
    border-bottom: 1px solid #ccc;
    padding-bottom: 1px;
    color: #134074;
}}
h3 {{
    font-size: 8.2pt;
    margin: 3px 0 1px 0;
    color: #1d2d44;
}}
h4 {{
    font-size: 7.8pt;
    margin: 2px 0 1px 0;
}}
p {{
    margin: 0 0 2.5px 0;
}}
ul, ol {{
    margin: 0 0 2px 0;
    padding-left: 14px;
}}
li {{
    margin-bottom: 1px;
}}
hr {{
    border: 0;
    border-top: 1px solid #ddd;
    margin: 3px 0;
}}
blockquote {{
    margin: 2px 0 3px 8px;
    padding-left: 6px;
    border-left: 2px solid #0077b6;
    color: #333;
    font-style: italic;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    margin: 2px 0 3px 0;
    font-size: 6.8pt;
    line-height: 1.12;
}}
th, td {{
    border: 1px solid #bbb;
    padding: 1.2px 3px;
    text-align: left;
}}
th {{
    background-color: #f0f4f8;
    font-weight: 600;
}}
tr:nth-child(even) {{
    background-color: #fafbfc;
}}
code {{
    font-family: Consolas, monospace;
    font-size: 7.2pt;
    background: #f4f4f4;
    padding: 0 2px;
}}
a {{
    color: #0077b6;
    text-decoration: none;
}}
</style>
</head>
<body>
{body}
</body>
</html>
"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[HTML] Rendered HTML to {html_path}")

def convert_html_to_pdf(html_path: Path, pdf_path: Path):
    cmd = [
        EDGE_EXE,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        str(html_path.resolve().as_uri())
    ]
    print(f"[Edge] Running headless PDF print...")
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    print(f"[PDF] Generated {pdf_path}")

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
    render_md_to_html(MD_PATH, HTML_PATH)
    convert_html_to_pdf(HTML_PATH, PDF_PATH)
    pages = verify_pdf_pages(PDF_PATH)
