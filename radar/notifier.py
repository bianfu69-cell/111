"""Multi-channel push notification dispatcher (zero external dependencies)."""

from __future__ import annotations

import json
import platform
import subprocess
import urllib.parse
import urllib.request
from typing import Any


def _post_json(url: str, payload: dict[str, Any], timeout: int = 12) -> tuple[bool, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "G83-Radar/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return 200 <= resp.status < 300, body[:200]


def _post_form(url: str, fields: dict[str, str], timeout: int = 12) -> tuple[bool, str]:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "G83-Radar/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return 200 <= resp.status < 300, body[:200]


def _send_windows_toast(title: str, message: str) -> tuple[bool, str]:
    if platform.system() != "Windows":
        return False, "Not running on Windows"
    # Escape single quotes for PowerShell
    t_esc = title.replace("'", "''").replace("\n", " ")[:120]
    m_esc = message.replace("'", "''").replace("\n", " | ")[:240]
    ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastText02"><text id="1">{t_esc}</text><text id="2">{m_esc}</text></binding></visual></toast>')
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Dynabook G83 Radar').Show($toast)
"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return True, "Windows toast sent"
        return False, (proc.stderr or proc.stdout or "Toast failed")[:180]
    except Exception as exc:
        return False, str(exc)


def send_notification(
    cfg: dict[str, Any],
    title: str,
    markdown_body: str,
    plain_body: str,
    link_url: str = "",
    compact_body: str = "",
) -> dict[str, dict[str, Any]]:
    """Send notifications to all configured channels. Returns status per channel."""
    notif = cfg.get("notifications", {})
    results: dict[str, dict[str, Any]] = {}
    mobile_body = (compact_body or plain_body)[:900]

    if notif.get("windows_toast"):
        ok, info = _send_windows_toast(title, mobile_body)
        results["windows_toast"] = {"ok": ok, "info": info}

    pushplus_token = (notif.get("pushplus_token") or "").strip()
    if pushplus_token:
        try:
            ok, info = _post_json(
                "https://www.pushplus.plus/send",
                {
                    "token": pushplus_token,
                    "title": title,
                    "content": markdown_body,
                    "template": "markdown",
                },
            )
            results["pushplus"] = {"ok": ok, "info": info}
        except Exception as exc:
            results["pushplus"] = {"ok": False, "info": str(exc)}

    serverchan_key = (notif.get("serverchan_key") or "").strip()
    if serverchan_key:
        try:
            url = f"https://sctapi.ftqq.com/{urllib.parse.quote(serverchan_key)}.send"
            ok, info = _post_form(url, {"title": title, "desp": markdown_body})
            results["serverchan"] = {"ok": ok, "info": info}
        except Exception as exc:
            results["serverchan"] = {"ok": False, "info": str(exc)}

    bark_url = (notif.get("bark_url") or "").strip().rstrip("/")
    if bark_url:
        try:
            # Normalize bare key, root URL, or Bark App's sample URL with trailing sample text
            if not bark_url.startswith("http"):
                endpoint = f"https://api.day.app/{urllib.parse.quote(bark_url)}"
            else:
                parsed = urllib.parse.urlparse(bark_url)
                segs = [s for s in parsed.path.split("/") if s]
                device_key = segs[0] if segs else ""
                endpoint = f"{parsed.scheme}://{parsed.netloc}/{device_key}" if device_key else bark_url

            payload: dict[str, Any] = {
                "title": title,
                "body": mobile_body,
                "group": "G83捡漏雷达",
                "sound": "bell",
                "level": "timeSensitive",
            }
            if link_url:
                payload["url"] = link_url
            ok, info = _post_json(endpoint, payload)
            results["bark"] = {"ok": ok, "info": info}
        except Exception as exc:
            results["bark"] = {"ok": False, "info": str(exc)}

    feishu_webhook = (notif.get("feishu_webhook") or "").strip()
    if feishu_webhook:
        try:
            ok, info = _post_json(
                feishu_webhook,
                {
                    "msg_type": "text",
                    "content": {"text": f"{title}\n\n{plain_body}"},
                },
            )
            results["feishu"] = {"ok": ok, "info": info}
        except Exception as exc:
            results["feishu"] = {"ok": False, "info": str(exc)}

    dingtalk_webhook = (notif.get("dingtalk_webhook") or "").strip()
    if dingtalk_webhook:
        try:
            ok, info = _post_json(
                dingtalk_webhook,
                {
                    "msg_type": "markdown",
                    "msgtype": "markdown",
                    "markdown": {"title": title, "text": f"### {title}\n\n{markdown_body}"},
                },
            )
            results["dingtalk"] = {"ok": ok, "info": info}
        except Exception as exc:
            results["dingtalk"] = {"ok": False, "info": str(exc)}

    ntfy_topic = (notif.get("ntfy_topic") or "").strip().rstrip("/")
    if ntfy_topic:
        try:
            if ntfy_topic.startswith("http"):
                parsed = urllib.parse.urlparse(ntfy_topic)
                base_url = f"{parsed.scheme}://{parsed.netloc}"
                topic_name = parsed.path.strip("/").split("/")[-1]
            else:
                base_url = "https://ntfy.sh"
                topic_name = ntfy_topic

            payload_ntfy: dict[str, Any] = {
                "topic": topic_name,
                "title": title,
                "message": mobile_body,
                "priority": 4,
                "tags": ["laptop", "moneybag"],
            }
            if link_url:
                payload_ntfy["click"] = link_url
            ok, info = _post_json(base_url, payload_ntfy)
            results["ntfy"] = {"ok": ok, "info": info}
        except Exception as exc:
            results["ntfy"] = {"ok": False, "info": str(exc)}

    tg_token = (notif.get("telegram_bot_token") or "").strip()
    tg_chat = (notif.get("telegram_chat_id") or "").strip()
    if tg_token and tg_chat:
        try:
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            ok, info = _post_json(
                url,
                {
                    "chat_id": tg_chat,
                    "text": f"{title}\n\n{plain_body}",
                    "disable_web_page_preview": False,
                },
            )
            results["telegram"] = {"ok": ok, "info": info}
        except Exception as exc:
            results["telegram"] = {"ok": False, "info": str(exc)}

    return results


def _build_detail_note(it: dict[str, Any]) -> str:
    if not it.get("detail_inspected"):
        return "🔎待深查正文"
    mods = it.get("detail_moderate_tags") or []
    mins = it.get("detail_minor_tags") or []
    pos = it.get("detail_positives") or []
    parts = []
    if mods:
        parts.append("⚠️" + "/".join(mods))
    else:
        parts.append("✅正文无硬伤")
    if mins:
        parts.append("ℹ️" + "/".join(mins))
    if pos:
        parts.append("✨" + "/".join(pos[:2]))
    return " · ".join(parts)


def format_deal_alert(items: list[dict[str, Any]], is_digest: bool = False) -> tuple[str, str, str, str, str]:
    """Format hot deals (or live Top-3 digest) into (title, markdown_body, plain_body, top_link, compact_body)."""
    top = items[0]
    if is_digest:
        title = (
            f"📊 G83实时榜单预览(Top{min(3, len(items))}) "
            f"榜首 {top['gen_label_short']} 折合¥{int(top['effective_512_cny'])}"
        )
    elif len(items) == 1:
        title = (
            f"🔥 G83捡漏! {top['gen_label_short']} "
            f"折合¥{int(top['effective_512_cny'])} ({top['remaining_text']})"
        )
    else:
        title = (
            f"🔥 发现 {len(items)} 台 G83 好价! "
            f"最低 {top['gen_label_short']} 折合¥{int(top['effective_512_cny'])}"
        )

    md_lines: list[str] = []
    plain_lines: list[str] = []
    compact_lines: list[str] = []

    limit = 3 if is_digest else 5
    for idx, it in enumerate(items[:limit], 1):
        seller_tag = "个人免税" if not it["is_store"] else "商家含税"
        is_bn = it.get("alert_reason") == "buy_now"
        deal_type = "💎一口价" if is_bn else ("👀实时榜" if is_digest else "⏰快结拍")
        price_jpy = it["buy_now_price_jpy"] if is_bn else it["price_jpy"]
        untaxed = int(it["buy_now_untaxed_cny"] if is_bn else it["untaxed_cny"])
        eff_512 = int(it["buy_now_effective_512_cny"] if is_bn else it["effective_512_cny"])
        with_tax = int(it["buy_now_with_customs_cny"] if is_bn else it["with_customs_cny"])
        save_cny = int(it["savings_vs_ref_cny"])
        save_txt = f"省¥{save_cny}" if save_cny >= 0 else f"超参考¥{abs(save_cny)}"

        specs = f"{it['gen_label_short']} | {it['cpu_model']} | {it['ram_label']}/{it['ssd_label']} | {it['condition_label']}"
        detail_note = _build_detail_note(it)

        md_lines.append(
            f"#### {idx}. [{deal_type}] {it['title'][:65]}\n"
            f"- **配置**: {specs}\n"
            f"- **正文排雷**: {detail_note}\n"
            f"- **日拍价**: `{price_jpy:,} 日元` ({seller_tag}, 出价 {it['bid_count']} 次, 收藏 {it['watch_count']})\n"
            f"- **预计到手**: 未税 **¥{untaxed}** | 折合512G **¥{eff_512}** | 被税封顶 ¥{with_tax} ({save_txt})\n"
            f"- **剩余时间**: {it['remaining_text']} | 评分: {it['steal_score']}/100\n"
            f"- **直达**: [在任意门查看]({it['doorzo_url']}) | [雅虎原页]({it['yahoo_url']})\n"
        )
        plain_lines.append(
            f"{idx}. [{deal_type}] {specs}\n"
            f"   排雷: {detail_note}\n"
            f"   日拍 {price_jpy:,}円({seller_tag}, {it['bid_count']}出价) -> 未税¥{untaxed} / 折合512G ¥{eff_512} ({save_txt})\n"
            f"   剩余 {it['remaining_text']} | 雅虎: {it['yahoo_url']}"
        )
        compact_lines.append(
            f"{idx}. [{deal_type}] {specs}\n"
            f"   {price_jpy:,}円({seller_tag}·{it['bid_count']}出价) → 未税¥{untaxed} | 折合512G ¥{eff_512}({save_txt}) | 被税¥{with_tax}\n"
            f"   {detail_note} | 剩{it['remaining_text']} | {it['steal_score']}分"
        )

    if is_digest:
        compact_lines.append("👆 这是真实格式预览（点此直达榜首任意门页；平时仅达标捡漏才推送）")
    else:
        compact_lines.append("👆 点此通知直达任意门商品页查看出价")

    return title, "\n".join(md_lines), "\n".join(plain_lines), top["doorzo_url"], "\n".join(compact_lines)
