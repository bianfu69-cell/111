"""Export self-contained static dashboard into docs/ for GitHub Pages hosting."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from radar.config import ROOT_DIR

WEB_DIR = ROOT_DIR / "web"
DOCS_DIR = ROOT_DIR / "docs"


def export_static_site(snapshot: dict[str, Any]) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for asset in ("index.html", "styles.css", "app.js"):
        src = WEB_DIR / asset
        if src.exists():
            shutil.copy2(src, DOCS_DIR / asset)

    # Write static data.json (contains masked public config, never secrets)
    out_data = DOCS_DIR / "data.json"
    with out_data.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    # Disable Jekyll on GitHub Pages
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")
    return DOCS_DIR
