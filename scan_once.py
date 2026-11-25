"""One-shot CLI scanner for GitHub Actions, Task Scheduler, or quick terminal checks."""

from __future__ import annotations

import argparse
import sys

from radar.config import load_config
from radar.engine import run_scan
from radar.notifier import send_notification


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Dynabook G83 Yahoo Auctions One-Shot Scanner")
    parser.add_argument("--no-alert", action="store_true", help="Do not dispatch push notifications")
    parser.add_argument("--export-static", action="store_true", help="Export docs/ static site for GitHub Pages")
    parser.add_argument("--test-notify", action="store_true", help="Send a test notification and exit")
    parser.add_argument("--top", type=int, default=12, help="How many top listings to print in terminal")
    args = parser.parse_args()

    cfg = load_config(apply_env=True)

    if args.test_notify:
        res = send_notification(
            cfg,
            "🔔 Dynabook G83 捡漏雷达测试推送",
            "#### 推送通道测试成功！\n已连通手机/桌面提醒。",
            "推送通道测试成功！已连通手机/桌面提醒。",
            link_url="https://www.doorzo.com/",
        )
        print("Test notification results:", res)
        return 0

    snap = run_scan(cfg=cfg, send_alerts=not args.no_alert, export_static=args.export_static)
    s = snap["summary"]
    print(f"\n=== Dynabook G83 雅虎日拍扫描完成 ({snap['scanned_at']}, 耗时 {snap['duration_sec']}s) ===")
    print(f"汇率: 基准 {snap['fx_base']} -> 任意门估算 {snap['fx_effective']} ({snap['fx_source']})")
    print(
        f"抓取 {s['total_raw']} 条 -> 有效整机 {s['total_clean']} 台 | "
        f"13代:{s['gen13_count']}  12代:{s['gen12_count']}  11代:{s['gen11_count']} | "
        f"达标捡漏:{s['under_budget_count']} | 3小时内结拍:{s['ending_soon_count']}"
    )
    ist = snap.get("inspect_stats") or {}
    print(
        f"正文深度排雷: 已查 {ist.get('total_inspected', 0)} 台 "
        f"(缓存命中 {ist.get('cache_hits', 0)}, 实时深查 {ist.get('live_fetched', 0)}) -> "
        f"自动拦截详情暗病/硬伤 {ist.get('severe_caught', 0)} 台"
    )
    ad = snap["alert_dispatch"]
    print(f"推送检查: 达标候选 {ad['candidates']} 台, 本次新触发推送 {ad['triggered']} 台")

    clean_16 = [
        x for x in snap["items"]
        if not x["is_junk"] and not x.get("has_severe_defect") and not x["ignored"]
        and x["cpu_tier"] != "i3" and x["generation"] in (14, 13, 12, 11) and (x["ram_gb"] or 0) >= 16
    ]
    print(f"\n--- Top {min(args.top, len(clean_16))} 综合捡漏榜 (16GB+, 已剔除详情硬伤) ---")
    for idx, it in enumerate(clean_16[: args.top], 1):
        flag = "🔥达标" if (it["under_budget"] or it["buy_now_under_budget"]) else "观察"
        seller = "个人免税" if not it["is_store"] else "商家含税"
        bn = f" | 一口价折合512G ¥{int(it['buy_now_effective_512_cny'])}" if it.get("buy_now_effective_512_cny") else ""
        warns = list(it.get("warnings") or []) + list(it.get("detail_moderate_tags") or []) + list(it.get("detail_minor_tags") or [])
        warn_str = f" ⚠️{','.join(dict.fromkeys(warns))}" if warns else ""
        chk = "✅正文无硬伤" if (it.get("detail_inspected") and not it.get("detail_severe_tags") and not it.get("detail_moderate_tags")) else ("🔍已深查" if it.get("detail_inspected") else "未深查")
        print(
            f"{idx:2d}. [{flag} {it['steal_score']}分 | {chk}] {it['gen_label_short']} | {it['cpu_model']} | "
            f"{it['ram_label']}/{it['ssd_label']} | {seller} | 剩{it['remaining_text']} | 出价{it['bid_count']}"
        )
        print(
            f"    日拍 {it['price_jpy']:,}円 -> 未税到手 ¥{int(it['untaxed_cny'])} | "
            f"折合512G ¥{int(it['effective_512_cny'])} (省¥{int(it['savings_vs_ref_cny'])}) | "
            f"被税封顶 ¥{int(it['with_customs_cny'])}{bn}{warn_str}"
        )
        print(f"    {it['title'][:80]}")
        print(f"    雅虎: {it['yahoo_url']}")

    caught = [x for x in snap["items"] if x.get("detail_severe_tags")]
    if caught:
        print(f"\n--- ⛔ 正文排雷自动拦截的暗病/硬伤机 ({len(caught)} 台) ---")
        for c in caught[:8]:
            ev = (c.get("detail_evidence") or [{}])[0].get("text", "")
            print(f"  - [{c['auction_id']}] {c['gen_label_short']} {c['price_jpy']:,}円 | 硬伤: {', '.join(c['detail_severe_tags'])}")
            if ev:
                print(f"    原文: {ev[:95]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
