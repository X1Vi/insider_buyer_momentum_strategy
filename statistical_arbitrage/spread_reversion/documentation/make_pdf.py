#!/usr/bin/env python3
"""Convert documentation/MASTER_DOC.md to documentation/MASTER_DOC.pdf."""
import markdown
from xhtml2pdf import pisa
from pathlib import Path

SRC = Path(__file__).parent / "MASTER_DOC.md"
OUT = Path(__file__).parent / "MASTER_DOC.pdf"

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; color: #222; line-height: 1.45; }
h1 { font-size: 19pt; color: #0b3d66; border-bottom: 2px solid #0b3d66; padding-bottom: 4px; }
h2 { font-size: 14pt; color: #0b3d66; margin-top: 16px; border-bottom: 1px solid #ccc; padding-bottom: 2px; }
h3 { font-size: 11.5pt; color: #14568c; margin-top: 12px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9pt; }
th, td { border: 1px solid #999; padding: 4px 6px; text-align: left; }
th { background: #e8eef5; }
tr:nth-child(even) { background: #f6f8fa; }
code { background: #f0f0f0; padding: 1px 4px; border-radius: 3px; font-size: 9pt; }
pre { background: #f5f5f5; border: 1px solid #ddd; padding: 8px; font-size: 9pt; white-space: pre-wrap; }
blockquote { border-left: 4px solid #0b3d66; margin-left: 0; padding-left: 12px; color: #555; }
a { color: #14568c; text-decoration: none; }
"""

html = markdown.markdown(
    SRC.read_text(encoding="utf-8"),
    extensions=["tables", "fenced_code", "toc"],
)
full = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html}</body></html>"

with open(OUT, "wb") as f:
    pisa.CreatePDF(full, dest=f, encoding="utf-8")
print(f"wrote {OUT}")
