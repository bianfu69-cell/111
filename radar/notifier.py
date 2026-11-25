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
) -> dict[str, dict[str, Any]]:
    """Send notifications to all configured channels. Returns status per channel."""
    notif = cfg.get("notifications", {})
    results: dict[str, dict[str, Any]] = {}

    if notif.get("windows_toast"):
        ok, info = _send_windows_toast(title, plain_body)
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
            payload: dict[str, Any] = {
                "title": title,
                "body": plain_body[:600],
                "group": "G83捡漏雷达",
                "sound": "bell",
            }
            if link_url:
                payload["url"] = link_url
            ok, info = _post_json(bark_url, payload)
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

    ntfy_topic = (notif.get("ntfy_topic") or "").strip()
    if ntfy_topic:
        try:
            ntfy_url = ntfy_topic if ntfy_topic.startswith("http") else f"https://ntfy.sh/{urllib.parse.quote(ntfy_topic)}"
            headers = {
                "Title": title.encode("ascii", "ignore").decode("ascii") or "G83 Deal Alert",
                "Priority": "high",
                "Tags": "laptop,moneybag",
                "User-Agent": "G83-Radar/1.0",
            }
            if link_url:
                headers["Click"] = link_url
            req = urllib.request.Request(
                ntfy_url,
                data=f"{title}\n{plain_body}".encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                results["ntfy"] = {"ok": 200 <= resp.status < 300, "info": f"HTTP {resp.status}"}
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


def format_deal_alert(items: list[dict[str, Any]]) -> tuple[str, str, str, str]:
    """Format a batch of hot deals into (title, markdown_body, plain_body, top_link)."""
    top = items[0]
    if len(items) == 1:
        title = (
            f"🔥 G83捡漏! {top['gen_label_short']} "
            f"等效¥{int(top['effective_512_cny'])} ({top['remaining_text']})"
        )
    else:
        title = (
            f"🔥 发现 {len(items)} 台 G83 好价! "
            f"最低 {top['gen_label_short']} 等效¥{int(top['effective_512_cny'])}"
        )

    md_lines: list[str] = []
    plain_lines: list[str] = []

    for idx, it in enumerate(items[:6], 1):
        seller_tag = "个人免税" if not it["is_store"] else "商家含税"
        deal_type = "💎一口价" if it.get("alert_reason") == "buy_now" else "⏰快结拍"
        price_jpy = it["buy_now_price_jpy"] if it.get("alert_reason") == "buy_now" else it["price_jpy"]
        untaxed = int(it["buy_now_untaxed_cny"] if it.get("alert_reason") == "buy_now" else it["untaxed_cny"])
        eff_512 = int(it["buy_now_effective_512_cny"] if it.get("alert_reason") == "buy_now" else it["effective_512_cny"])
        with_tax = int(it["buy_now_with_customs_cny"] if it.get("alert_reason") == "buy_now" else it["with_customs_cny"])
        save_cny = int(it["savings_vs_ref_cny"])

        specs = f"{it['gen_label_short']} | {it['cpu_model']} | {it['ram_label']} | {it['ssd_label']} | {it['condition_label']}"
        detail_note = ""
        if it.get("detail_inspected"):
            mods = it.get("detail_moderate_tags") or []
            mins = it.get("detail_minor_tags") or []
            pos = it.get("detail_positives") or []
            parts = []
            if mods:
                parts.append("⚠️瑕疵:" + "/".join(mods))
            else:
                parts.append("✅正文无硬伤")
            if mins:
                parts.append("提示:" + "/".join(mins))
            if pos:
                parts.append("/".join(pos))
            detail_note = " | ".join(parts)

        md_lines.append(
            f"#### {idx}. [{deal_type}] {it['title'][:65]}\n"
            f"- **配置**: {specs}\n"
            f"- **正文排雷**: {detail_note or '未深查'}\n"
            f"- **日拍价**: `{price_jpy:,} 日元` ({seller_tag}, 出价 {it['bid_count']} 次, 收藏 {it['watch_count']})\n"
            f"- **预计到手**: 未税 **¥{untaxed}** | 折合512G **¥{eff_512}** | 被税封顶 ¥{with_tax} (省 ¥{save_cny})\n"
            f"- **剩余时间**: {it['remaining_text']} | 评分: {it['steal_score']}/100\n"
            f"- **直达**: [在任意门查看]({it['doorzo_url']}) | [雅虎原页]({it['yahoo_url']})\n"
        )
        plain_lines.append(
            f"{idx}. [{deal_type}] {specs}\n"
            f"   排雷: {detail_note or '未深查'}\n"
            f"   日拍 {price_jpy:,}円({seller_tag}, {it['bid_count']}出价) -> 未税¥{untaxed} / 折合512G ¥{eff_512} (省¥{save_cny})\n"
            f"   剩余 {it['remaining_text']} | 任意门: {it['doorzo_url']}\n"
            f"   雅虎: {it['yahoo_url']}"
        )

    return title, "\n".join(md_lines), "\n".join(plain_lines), top["doorzo_url"]
