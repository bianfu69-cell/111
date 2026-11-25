"""Yahoo Auctions Japan __NEXT_DATA__ fetcher and live FX rate loader."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import time
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

_FX_CACHE: dict[str, Any] = {"rate": None, "fetched_at": 0.0, "source": "fallback"}


def fetch_jpy_cny_rate(fallback: float = 0.042, force: bool = False) -> tuple[float, str]:
    """Fetch live JPY->CNY exchange rate with 6-hour in-memory cache."""
    now = time.time()
    if not force and _FX_CACHE["rate"] and (now - _FX_CACHE["fetched_at"] < 21600):
        return float(_FX_CACHE["rate"]), str(_FX_CACHE["source"])

    endpoints = [
        ("open.er-api", "https://open.er-api.com/v6/latest/JPY"),
        ("frankfurter", "https://api.frankfurter.dev/v1/latest?base=JPY&symbols=CNY"),
    ]
    for source_name, url in endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "G83-Radar/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            rate = float((data.get("rates") or {}).get("CNY") or 0)
            if 0.02 < rate < 0.15:
                _FX_CACHE.update({"rate": rate, "fetched_at": now, "source": source_name})
                return rate, source_name
        except Exception:
            continue

    return fallback, "config_fallback"


def fetch_yahoo_query(
    query: str,
    category_id: str = "23412",
    max_items: int = 50,
    sort: str = "end",
    order: str = "a",
) -> tuple[list[dict[str, Any]], int, str | None]:
    """Fetch Yahoo Auctions Japan search results via embedded __NEXT_DATA__ JSON."""
    params = {
        "p": query,
        "exflg": "1",
        "b": "1",
        "n": str(min(max(max_items, 20), 100)),
        "s1": sort,
        "o1": order,
    }
    if category_id:
        params["auccat"] = str(category_id)

    url = "https://auctions.yahoo.co.jp/search/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,zh-CN;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=18) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return [], 0, f"HTTP error for '{query}': {exc}"

    m = NEXT_DATA_RE.search(html)
    if not m:
        return [], 0, f"No __NEXT_DATA__ found for '{query}' (page len={len(html)})"

    try:
        data = json.loads(m.group(1))
        listing = data["props"]["pageProps"]["initialState"]["search"]["items"]["listing"]
        items = listing.get("items") or []
        total = int(listing.get("totalResultsAvailable") or len(items))
        return items, total, None
    except Exception as exc:
        return [], 0, f"JSON parse error for '{query}': {exc}"


def fetch_all_queries(cfg: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Poll all configured queries politely (3 concurrent workers) and deduplicate by auctionId."""
    queries = [str(q).strip() for q in (cfg.get("queries") or ["dynabook G83/LY", "dynabook G83 16GB"]) if str(q).strip()]
    category_id = str(cfg.get("yahoo_category_id") or "23412")
    max_items = int(cfg.get("max_items_per_query") or 50)

    tasks: list[tuple[str, str, int, str]] = [
        (q, q, max_items, "end") for q in queries
    ]
    for extra_q in ("dynabook G83/LY", "dynabook G83/LW"):
        tasks.append((f"{extra_q} (低价排序)", extra_q, 30, "cbids"))

    dedup: dict[str, dict[str, Any]] = {}
    stats: list[dict[str, Any]] = []

    def _run_one(label: str, q: str, limit: int, sort_by: str) -> tuple[str, list[dict[str, Any]], int, str | None]:
        items, total, err = fetch_yahoo_query(q, category_id=category_id, max_items=limit, sort=sort_by, order="a")
        return label, items, total, err

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(_run_one, lbl, q, lim, srt) for (lbl, q, lim, srt) in tasks]
        for fut in as_completed(futs):
            label, items, total, err = fut.result()
            added = 0
            for raw in items:
                aid = str(raw.get("auctionId") or "").strip()
                if aid and aid not in dedup:
                    dedup[aid] = raw
                    added += 1
            stats.append({
                "query": label,
                "fetched": len(items),
                "total_available": total,
                "unique_added": added,
                "error": err,
            })

    return dedup, stats
