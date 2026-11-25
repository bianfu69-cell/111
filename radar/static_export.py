"""Export self-contained static dashboard into docs/ for GitHub Pages hosting."""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from radar.config import ROOT_DIR

WEB_DIR = ROOT_DIR / "web"
DOCS_DIR = ROOT_DIR / "docs"


def export_static_site(snapshot: dict[str, Any]) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    ver = str(int(snapshot.get("scanned_ts") or time.time()))
    for asset in ("styles.css", "app.js"):
        src = WEB_DIR / asset
        if src.exists():
            shutil.copy2(src, DOCS_DIR / asset)

    # Inject cache-busting query string into docs/index.html so mobile browsers never serve stale JS/CSS
    src_html = WEB_DIR / "index.html"
    if src_html.exists():
        html_text = src_html.read_text(encoding="utf-8")
        html_text = re.sub(r'href="styles\.css(?:\?v=[^"]*)?"', f'href="styles.css?v={ver}"', html_text)
        html_text = re.sub(r'src="app\.js(?:\?v=[^"]*)?"', f'src="app.js?v={ver}"', html_text)
        (DOCS_DIR / "index.html").write_text(html_text, encoding="utf-8")

    # Write static data.json (contains masked public config, never secrets)
    out_data = DOCS_DIR / "data.json"
    with out_data.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    # Disable Jekyll on GitHub Pages
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")
    return DOCS_DIR
