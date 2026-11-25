"""One-shot multi-profile CLI scanner for GitHub Actions, Task Scheduler, or terminal checks."""

from __future__ import annotations

import argparse
import sys

from radar.config import load_config
from radar.engine import run_scan
from radar.notifier import format_deal_alert, send_notification


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Multi-Category Yahoo Auctions Doorzo Radar Scanner")
    parser.add_argument("--no-alert", action="store_true", help="Do not dispatch push notifications")
    parser.add_argument("--export-static", action="store_true", help="Export docs/ static site for GitHub Pages")
    parser.add_argument("--test-notify", action="store_true", help="Send a test notification and exit")
    parser.add_argument("--send-digest", action="store_true", help="Force-send Top 3 live listings preview push")
    parser.add_argument("--top", type=int, default=12, help="How many top listings to print in terminal")
    args = parser.parse_args()

    cfg = load_config(apply_env=True)

    if args.test_notify:
        res = send_notification(
            cfg,
            "🔔 万能日淘捡漏雷达测试推送",
            "#### 推送通道测试成功！\n已连通手机/桌面提醒。",
            "推送通道测试成功！已连通手机/桌面提醒。",
            link_url="https://www.doorzo.com/",
        )
        print("Test notification results:", res)
        return 0

    snap = run_scan(cfg=cfg, send_alerts=not args.no_alert, export_static=args.export_static)
    s = snap["summary"]
    print(f"\n=== 万能日淘雅虎日拍扫描完成 ({snap['scanned_at']}, 耗时 {snap['duration_sec']}s) ===")
    print(f"汇率: 基准 {snap['fx_base']} -> 任意门估算 {snap['fx_effective']} ({snap['fx_source']})")
    print(
        f"监控商品: {s['profile_count']} 个 | 抓取 {s['total_raw']} 条 -> 有效 {s['total_clean']} 件 | "
        f"达标捡漏: {s['under_budget_count']} | 3小时内结拍: {s['ending_soon_count']}"
    )
    for ps in snap.get("profile_summaries") or []:
        if not ps.get("enabled"):
            continue
        low = f"最低¥{int(ps['lowest_cny'])}" if ps.get("lowest_cny") is not None else "暂无"
        print(
            f"  - {ps['icon']} {ps['name']}: 有效 {ps['clean_count']} 件 | "
            f"达标 {ps['under_budget_count']} | 拦截硬伤 {ps['severe_caught_count']} | {low}"
        )

    ist = snap.get("inspect_stats") or {}
    print(
        f"正文深度排雷: 已查 {ist.get('total_inspected', 0)} 件 "
        f"(缓存 {ist.get('cache_hits', 0)}, 实时 {ist.get('live_fetched', 0)}) -> 自动拦截硬伤 {ist.get('severe_caught', 0)} 件"
    )
    ad = snap["alert_dispatch"]
    print(f"推送检查: 达标候选 {ad['candidates']} 件, 本次新触发推送 {ad['triggered']} 件")

    clean_top = [
        x for x in snap["items"]
        if not x["is_junk"] and not x.get("has_severe_defect") and not x["ignored"]
        and (x["category"] != "laptop" or (x["cpu_tier"] != "i3" and ((x["ram_gb"] or 0) >= 16 or x["profile_id"] != "dynabook_g83")))
    ]
    if args.send_digest and clean_top:
        title, md_body, plain_body, top_link, compact_body = format_deal_alert(clean_top[:3], is_digest=True)
        digest_res = send_notification(cfg, title, md_body, plain_body, link_url=top_link, compact_body=compact_body)
        print("真实榜单预览推送结果:", digest_res)

    print(f"\n--- Top {min(args.top, len(clean_top))} 综合捡漏榜 (已剔除详情硬伤) ---")
    for idx, it in enumerate(clean_top[: args.top], 1):
        flag = "🔥达标" if (it["under_budget"] or it["buy_now_under_budget"]) else "观察"
        seller = "个人免税" if not it["is_store"] else "商家含税"
        warns = list(it.get("warnings") or []) + list(it.get("detail_moderate_tags") or []) + list(it.get("detail_minor_tags") or [])
        warn_str = f" ⚠️{','.join(dict.fromkeys(warns))}" if warns else ""
        chk = "✅正文无硬伤" if (it.get("detail_inspected") and not it.get("detail_severe_tags") and not it.get("detail_moderate_tags")) else ("🔍已深查" if it.get("detail_inspected") else "未深查")
        print(
            f"{idx:2d}. [{flag} {it['steal_score']}分 | {chk}] {it['profile_icon']}{it['profile_name']} | "
            f"{seller} | 剩{it['remaining_text']} | 出价{it['bid_count']}"
        )
        print(
            f"    日拍 {it['price_jpy']:,}円 -> 预计到手 ¥{int(it['effective_512_cny'])} (省¥{int(it['savings_vs_ref_cny'])}) | "
            f"{'包税专线' if it.get('tax_included_shipping') else '被税封顶 ¥' + str(int(it['with_customs_cny']))}{warn_str}"
        )
        print(f"    {it['title'][:82]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
