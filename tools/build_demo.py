"""Builds the static demo for GitHub Pages into docs/.

    python tools/build_demo.py

The demo is the same web app with web/demo.js standing in for the backend (sample data, no AI, no keys).
GitHub: Settings → Pages → Branch: main, folder: /docs.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB, OUT = ROOT / "web", ROOT / "docs"


def build() -> Path:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "samples").mkdir(parents=True)
    for name in ("styles.css", "i18n.js", "assistant.js", "app.js", "reconcile.js", "recon.js", "demo.js"):
        shutil.copy2(WEB / name, OUT / name)
    for pdf in sorted((ROOT / "samples").glob("*.pdf")):
        shutil.copy2(pdf, OUT / "samples" / pdf.name)
    (OUT / "samples" / "bank").mkdir()
    for csv_file in sorted((ROOT / "samples" / "bank").glob("*.csv")):
        shutil.copy2(csv_file, OUT / "samples" / "bank" / csv_file.name)

    html = (WEB / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'"/static/([\w.]+)(\?v=\d+)?"', r'"./\1\2"', html)  # absolute → relative paths
    html = html.replace('<script src="./i18n.js', '<script src="./demo.js"></script>\n<script src="./i18n.js', 1)
    html = html.replace("<title>Fatoora Copilot</title>", "<title>Fatoora Copilot · Demo</title>\n"
                        '<meta name="description" content="AI invoice assistant for Saudi finance teams: ZATCA pre-checks, '
                        'duplicate detection, approvals and bank reconciliation. Demo with sample data.">', 1)
    assert "/static/" not in html and "demo.js" in html and "assistant.js" in html, "demo build failed"
    (OUT / "index.html").write_text(html, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is
    return OUT


if __name__ == "__main__":
    out = build()
    print(f"Demo built in {out.relative_to(ROOT)}/ ({sum(1 for _ in out.rglob('*') if _.is_file())} files)")
