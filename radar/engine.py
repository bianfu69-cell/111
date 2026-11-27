"""Core multi-profile scan orchestration: fetch -> parse -> deep inspect -> persist -> alert -> export."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import time
from typing import Any

from radar.config import load_config, mask_secrets
from radar.fetcher import fetch_all_profiles, fetch_jpy_cny_rate
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
from radar.templates import list_templates_public


def _deep_inspect_candidates(
    parsed: list[dict[str, Any]],
    profile_map: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
    max_total_live_fetches: int = 40,
) -> dict[str, int]:
    """Apply 24h cached inspections across all items, then fetch live for top candidates per profile."""
    all_ids = list({x["auction_id"] for x in parsed})
    cat_map = {x["auction_id"]: x["category"] for x in parsed}
    cached = get_cached_inspections(all_ids, ttl_hours=24, min_version=4, category_map=cat_map)
    cache_hits = 0
    for it in parsed:
        rep = cached.get(it["auction_id"])
        if rep and rep.get("inspected"):
            apply_inspection(it, rep, profile_map[it["profile_id"]], cfg)
            cache_hits += 1

    # Fair per-profile quota so every user-added product gets its top deals inspected
    active_pids = list({x["profile_id"] for x in parsed})
    per_profile_quota = max(10, max_total_live_fetches // max(1, len(active_pids)))

    to_fetch_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for pid in active_pids:
        prof = profile_map[pid]
        lo = prof.get("laptop_options") or {}
        cands = []
        for x in parsed:
            if x["profile_id"] != pid or x.get("detail_inspected") or x.get("is_junk") or x.get("ignored"):
                continue
            if x["category"] == "laptop":
                if lo.get("exclude_i3") and x.get("cpu_tier") == "i3":
                    continue
                if lo.get("require_16gb") and x.get("ram_gb") is not None and x["ram_gb"] < 16:
                    continue
                gen_rules = lo.get("generation_rules") or {}
                if gen_rules and not (gen_rules.get(x["gen_key"]) or {}).get("enabled", True):
                    continue
            cands.append(x)

        cands.sort(
            key=lambda x: (
                0 if x.get("alert_reason") else (1 if (x.get("under_budget") or x.get("buy_now_under_budget")) else 2),
                -x["steal_score"],
                x["remaining_sec"],
            )
        )
        for it in cands[:per_profile_quota]:
            key = (it["auction_id"], it["category"])
            to_fetch_map.setdefault(key, []).append(it)

    fetched_ok = 0
    if to_fetch_map:
        with ThreadPoolExecutor(max_workers=4) as pool:
            fut_map = {
                pool.submit(fetch_and_inspect_item, aid, cat): (aid, items_list)
                for (aid, cat), items_list in list(to_fetch_map.items())[:max_total_live_fetches]
            }
            for fut in as_completed(fut_map):
                aid, items_list = fut_map[fut]
                try:
                    rep = fut.result()
                    if rep and rep.get("inspected"):
                        save_cached_inspection(aid, rep)
                        for it in items_list:
                            apply_inspection(it, rep, profile_map[it["profile_id"]], cfg)
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
    """Execute a complete multi-profile radar scan and return the structured snapshot."""
    started_at = time.time()
    cfg = cfg or load_config(apply_env=True)
    profiles = cfg.get("profiles") or []
    profile_map = {p["id"]: p for p in profiles}
    cost_model = cfg.get("cost_model", {})

    # 1. Exchange rate
    if cost_model.get("auto_fx", True):
        fx_base, fx_source = fetch_jpy_cny_rate(fallback=float(cost_model.get("jpy_to_cny", 0.042)))
    else:
        fx_base, fx_source = float(cost_model.get("jpy_to_cny", 0.042)), "manual"

    spread = float(cost_model.get("fx_spread_pct", 3.5)) / 100.0
    effective_fx = round(fx_base * (1.0 + spread), 6)

    # 2. Fetch Yahoo Auctions listings across all enabled profiles
    per_profile_raw, query_stats = fetch_all_profiles(profiles)
    total_raw = sum(len(b) for b in per_profile_raw.values())

    # 3. Parse & score per profile
    now_utc = dt.datetime.now(dt.timezone.utc)
    marks = get_all_marks()
    parsed: list[dict[str, Any]] = []
    for pid, raw_bucket in per_profile_raw.items():
        prof = profile_map[pid]
        for raw in raw_bucket.values():
            item = parse_yahoo_item(raw, prof, cfg, fx_rate_base=fx_base, now_utc=now_utc)
            if not item:
                continue
            mark = marks.get(item["auction_id"], {})
            item["starred"] = bool(mark.get("starred", False))
            item["ignored"] = bool(mark.get("ignored", False))
            item["note"] = mark.get("note", "")
            parsed.append(item)

    # 4. Stage 2: Deep-inspect Yahoo item detail descriptions per profile
    inspect_stats = _deep_inspect_candidates(parsed, profile_map, cfg, max_total_live_fetches=40)

    # 5. Record price history
    delta_map = record_price_snapshot(parsed)
    for it in parsed:
        d = delta_map.get(it["auction_id"], {})
        it["first_price_jpy"] = d.get("first_price_jpy", it["price_jpy"])
        it["price_delta_jpy"] = d.get("price_delta_jpy", 0)
        it["is_new_seen"] = bool(d.get("is_new_seen", False))

    parsed.sort(key=lambda x: (-x["steal_score"], x["effective_512_cny"], x["remaining_sec"]))

    # 6. Build per-profile summaries & overall summary
    active_clean = [x for x in parsed if not x["is_junk"] and not x.get("has_severe_defect") and not x["ignored"]]
    hot_alerts = [x for x in active_clean if x.get("alert_reason") in ("buy_now", "ending_soon")]

    profile_summaries: list[dict[str, Any]] = []
    for p in profiles:
        pid = p["id"]
        p_all = [x for x in parsed if x["profile_id"] == pid and not x["ignored"]]
        p_clean = [x for x in active_clean if x["profile_id"] == pid]
        p_under = [x for x in p_clean if x["under_budget"] or x["buy_now_under_budget"]]
        profile_summaries.append({
            "id": pid,
            "name": p["name"],
            "icon": p.get("icon", "📦"),
            "category": p.get("category", "general"),
            "enabled": bool(p.get("enabled", True)),
            "target_cny": p.get("target_cny", 0),
            "ref_cny": p.get("ref_cny", 0),
            "tax_included_shipping": bool(p.get("tax_included_shipping", False)),
            "total_count": len(p_all),
            "clean_count": len(p_clean),
            "under_budget_count": len(p_under),
            "ending_soon_count": sum(1 for x in p_clean if 0 < x["remaining_sec"] <= 10800),
            "severe_caught_count": sum(1 for x in p_all if x.get("detail_severe_tags")),
            "lowest_cny": min((x["effective_512_cny"] for x in p_clean), default=None),
        })

    summary = {
        "total_raw": total_raw,
        "total_parsed": len(parsed),
        "total_clean": len(active_clean),
        "profile_count": sum(1 for p in profiles if p.get("enabled", True)),
        "under_budget_count": sum(1 for x in active_clean if x["under_budget"] or x["buy_now_under_budget"]),
        "ending_soon_count": sum(1 for x in active_clean if 0 < x["remaining_sec"] <= 10800),
        "hot_alert_count": len(hot_alerts),
        "detail_inspected_count": inspect_stats["total_inspected"],
        "severe_caught_count": inspect_stats["severe_caught"],
    }

    # 7. Trigger deduplicated notifications grouped neatly
    alert_dispatch: dict[str, Any] = {"candidates": len(hot_alerts), "triggered": 0, "channels": {}}
    if send_alerts and hot_alerts:
        cooldown = int(cfg.get("filters", {}).get("alert_cooldown_minutes", 120))
        fresh = filter_new_alerts(hot_alerts, cooldown_minutes=cooldown)
        alert_dispatch["triggered"] = len(fresh)
        if fresh:
            title, md_body, plain_body, top_link, compact_body = format_deal_alert(fresh)
            group_name = f"日淘雷达·{fresh[0]['profile_name']}" if len({x["profile_id"] for x in fresh}) == 1 else "日淘多品类雷达"
            alert_dispatch["channels"] = send_notification(
                cfg, title, md_body, plain_body, link_url=top_link, compact_body=compact_body, group_name=group_name
            )

    now_cst = now_utc.astimezone(dt.timezone(dt.timedelta(hours=8)))
    snapshot = {
        "version": 2,
        "scanned_at": now_cst.strftime("%Y-%m-%d %H:%M:%S"),
        "scanned_ts": int(time.time()),
        "duration_sec": round(time.time() - started_at, 2),
        "fx_base": round(fx_base, 6),
        "fx_effective": effective_fx,
        "fx_source": fx_source,
        "summary": summary,
        "profiles": profiles,
        "profile_summaries": profile_summaries,
        "templates": list_templates_public(),
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
