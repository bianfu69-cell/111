"""Core scan orchestration: fetch -> parse -> score -> persist -> alert -> export."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import time
from typing import Any

from radar.config import load_config, mask_secrets
from radar.fetcher import fetch_all_queries, fetch_jpy_cny_rate
from radar.inspector import fetch_and_inspect_item
from radar.notifier import format_deal_alert, send_notification
from radar.parser import apply_inspection, parse_yahoo_item
from radar.storage import (
    filter_new_alerts,
    get_all_marks,
    get_cached_inspections,
    record_price_snapshot,
    save_cached_inspection,
    save_latest_snapshot,
)


def _deep_inspect_candidates(
    parsed: list[dict[str, Any]],
    cfg: dict[str, Any],
    max_live_fetches: int = 35,
) -> dict[str, int]:
    """Auto-inspect Yahoo detail pages for promising / under-budget / closing-soon items."""
    # 1. Apply any already-cached inspections across ALL items (free, instant!)
    all_ids = [x["auction_id"] for x in parsed]
    cached = get_cached_inspections(all_ids, ttl_hours=24)
    cache_hits = 0
    for it in parsed:
        rep = cached.get(it["auction_id"])
        if rep and rep.get("inspected"):
            apply_inspection(it, rep, cfg)
            cache_hits += 1

    # 2. Pick top uninspected candidates to fetch live:
    #    Priority 1: ALL alert candidates & under-budget non-junk 16GB+ items
    #    Priority 2: Top scoring / soonest-ending 16GB+ items (13th/12th/11th gen)
    priority_list = [
        x for x in parsed
        if not x.get("detail_inspected")
        and not x.get("is_junk")
        and not x.get("ignored")
        and x.get("cpu_tier") != "i3"
        and x.get("generation") in (14, 13, 12, 11)
        and ((x.get("ram_gb") or 0) >= 16 or x.get("ram_gb") is None)
    ]
    priority_list.sort(
        key=lambda x: (
            0 if x.get("alert_reason") else (1 if (x.get("under_budget") or x.get("buy_now_under_budget")) else 2),
            -x["steal_score"],
            x["remaining_sec"],
        )
    )
    to_fetch = priority_list[:max_live_fetches]

    fetched_ok = 0
    if to_fetch:
        with ThreadPoolExecutor(max_workers=4) as pool:
            fut_map = {pool.submit(fetch_and_inspect_item, it["auction_id"]): it for it in to_fetch}
            for fut in as_completed(fut_map):
                it = fut_map[fut]
                try:
                    rep = fut.result()
                    if rep and rep.get("inspected"):
                        save_cached_inspection(it["auction_id"], rep)
                        apply_inspection(it, rep, cfg)
                        fetched_ok += 1
                except Exception:
                    pass

    return {
        "cache_hits": cache_hits,
        "live_fetched": fetched_ok,
        "total_inspected": sum(1 for x in parsed if x.get("detail_inspected")),
        "severe_caught": sum(1 for x in parsed if x.get("detail_severe_tags")),
    }


def run_scan(
    cfg: dict[str, Any] | None = None,
    send_alerts: bool = True,
    export_static: bool = False,
) -> dict[str, Any]:
    """Execute a complete radar scan and return the structured snapshot."""
    started_at = time.time()
    cfg = cfg or load_config(apply_env=True)
    cost_model = cfg.get("cost_model", {})

    # 1. Exchange rate
    if cost_model.get("auto_fx", True):
        fx_base, fx_source = fetch_jpy_cny_rate(fallback=float(cost_model.get("jpy_to_cny", 0.042)))
    else:
        fx_base, fx_source = float(cost_model.get("jpy_to_cny", 0.042)), "manual"

    spread = float(cost_model.get("fx_spread_pct", 3.5)) / 100.0
    effective_fx = round(fx_base * (1.0 + spread), 6)

    # 2. Fetch Yahoo Auctions listings across all queries
    raw_map, query_stats = fetch_all_queries(cfg)

    # 3. Parse, score, enrich
    now_utc = dt.datetime.now(dt.timezone.utc)
    marks = get_all_marks()
    parsed: list[dict[str, Any]] = []
    for raw in raw_map.values():
        item = parse_yahoo_item(raw, cfg, fx_rate_base=fx_base, now_utc=now_utc)
        if not item:
            continue
        mark = marks.get(item["auction_id"], {})
        item["starred"] = bool(mark.get("starred", False))
        item["ignored"] = bool(mark.get("ignored", False))
        item["note"] = mark.get("note", "")
        parsed.append(item)

    # 4. Stage 2: Deep-inspect Yahoo item detail descriptions for top candidates & all alert candidates
    inspect_stats = _deep_inspect_candidates(parsed, cfg, max_live_fetches=35)

    # 5. Record price history & compute delta
    delta_map = record_price_snapshot(parsed)
    for it in parsed:
        d = delta_map.get(it["auction_id"], {})
        it["first_price_jpy"] = d.get("first_price_jpy", it["price_jpy"])
        it["price_delta_jpy"] = d.get("price_delta_jpy", 0)
        it["is_new_seen"] = bool(d.get("is_new_seen", False))

    # Sort primarily by steal_score DESC, then effective_512_cny ASC
    parsed.sort(key=lambda x: (-x["steal_score"], x["effective_512_cny"], x["remaining_sec"]))

    # 6. Summary metrics (exclude both title-junk AND detail-page severe hardware defects!)
    active_non_junk = [x for x in parsed if not x["is_junk"] and not x.get("has_severe_defect") and not x["ignored"]]
    hot_alerts = [
        x for x in active_non_junk
        if x.get("alert_reason") in ("buy_now", "ending_soon")
    ]

    summary = {
        "total_raw": len(raw_map),
        "total_parsed": len(parsed),
        "total_clean": len(active_non_junk),
        "gen13_count": sum(1 for x in active_non_junk if x["generation"] == 13),
        "gen12_count": sum(1 for x in active_non_junk if x["generation"] == 12),
        "gen11_count": sum(1 for x in active_non_junk if x["generation"] == 11),
        "under_budget_count": sum(1 for x in active_non_junk if x["under_budget"] or x["buy_now_under_budget"]),
        "ending_soon_count": sum(1 for x in active_non_junk if 0 < x["remaining_sec"] <= 10800),
        "hot_alert_count": len(hot_alerts),
        "detail_inspected_count": inspect_stats["total_inspected"],
        "severe_caught_count": inspect_stats["severe_caught"],
    }

    # 7. Trigger notifications for new hot deals (guaranteed detail-inspected & free of severe defects!)
    alert_dispatch: dict[str, Any] = {"candidates": len(hot_alerts), "triggered": 0, "channels": {}}
    if send_alerts and hot_alerts:
        cooldown = int(cfg.get("filters", {}).get("alert_cooldown_minutes", 120))
        fresh = filter_new_alerts(hot_alerts, cooldown_minutes=cooldown)
        alert_dispatch["triggered"] = len(fresh)
        if fresh:
            title, md_body, plain_body, top_link = format_deal_alert(fresh)
            alert_dispatch["channels"] = send_notification(cfg, title, md_body, plain_body, link_url=top_link)

    now_cst = now_utc.astimezone(dt.timezone(dt.timedelta(hours=8)))
    snapshot = {
        "scanned_at": now_cst.strftime("%Y-%m-%d %H:%M:%S"),
        "scanned_ts": int(time.time()),
        "duration_sec": round(time.time() - started_at, 2),
        "fx_base": round(fx_base, 6),
        "fx_effective": effective_fx,
        "fx_source": fx_source,
        "summary": summary,
        "inspect_stats": inspect_stats,
        "query_stats": query_stats,
        "alert_dispatch": alert_dispatch,
        "config_public": mask_secrets(cfg),
        "items": parsed,
    }

    save_latest_snapshot(snapshot)

    if export_static:
        from radar.static_export import export_static_site
        export_static_site(snapshot)

    return snapshot
