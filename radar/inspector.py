"""Multi-category Yahoo Auctions item detail fetcher & Japanese defect inspector."""

from __future__ import annotations

import html as html_lib
import json
import re
import threading
import time
import urllib.request
from typing import Any

_FLEA_LOCK = threading.Lock()
_FLEA_LAST_TS = 0.0

from radar.templates import (
    UNIVERSAL_MINOR_RULES,
    UNIVERSAL_MODERATE_RULES,
    UNIVERSAL_SEVERE_RULES,
    get_template,
)

INSPECTOR_VERSION = 4

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

# Standard Japanese boilerplate / warranty / return policy / grading legends
DISCLAIMER_PATTERNS = [
    r"ご了承ください",
    r"ご容赦ください",
    r"ご理解の上",
    r"ご理解ください",
    r"消耗品のため",
    r"保証対象外",
    r"保証期間",
    r"保証はございません",
    r"保証はありません",
    r"保証いたしかねます",
    r"保証致しかねます",
    r"保証無しとさせていただき",
    r"保証はできません",
    r"保証なし",
    r"赤ロム.{0,8}保証",
    r"対応致しかねます",
    r"対応いたしかねます",
    r"対応できかねます",
    r"初期不良",
    r"ダンボール",
    r"ダウンタイム",
    r"返品の対象",
    r"返品不可",
    r"返品はお受け",
    r"交換・返品",
    r"返金",
    r"お客様ご自身",
    r"お客様の都合",
    r"運送会社",
    r"配送事故",
    r"輸送中",
    r"ノークレーム",
    r"ノーリターン",
    r"入札を取り消",
    r"評価が.{0,12}以下",
    r"他の付属品は一切無",
    r"オフィスソフトは付属いたしません",
    r"office.?は付属",
    r"記載なき場合は写真のもののみ",
    r"質問欄からご連絡",
    r"お支払い金額",
    r"落札者お支払い総額",
    r"ジャンク扱い商品については",
    r"ジャンク品と記載のある商品",
    r"ジャンク品は保証",
    r"ジャンク品又は記載",
    r"に該当する場合をジャンク品",
    r"^\s*J\s+ジャンク",
    r"^\s*\d+[\.\)．]\s*ジャンク品",
    r"状態ランク.{0,15}ジャンク",
    r"対象外\)",
    r"場合は、",
    r"場合があります",
    r"場合がございます",
    r"撮影に影響.{0,8}(?:ありません|ございません|なし|無し|ない)",
]

# Negation cues in a clause ("破損なし", "-バッテリー膨張 : なし", "カビ・クモリなし", "ドリフトなし")
NEGATION_PATTERNS = [
    r"(?:は|も|等)?(?:ありません|ありませんでした|ございません|見当たりません|見られません|感じられません|認められません|確認できませんでした)",
    r"[:：]\s*(?:なし|無し|無\b|ゼロ|0|ありません|ございません|良好|正常|問題なし|ok|○)\s*$",
    r"(?:割れ|破損|ヒビ|ひび|ムラ|シミ|抜け|不良|異常|欠品|欠損|ガタ|緩み|膨張|傷|キズ|問題|不具合|カビ|クモリ|曇り|ドリフト|焼け|ベタつき|破れ|剥がれ|チャタリング|ダブルクリック|空回り|逆回転|文字消え)\s*[:：/\- ]*(?:なし|無し|無\b|ゼロ|0|等?なく|は無い)",
    r"状態良好",
    r"問題なく",
    r"正常に動作",
    r"良好です",
    r"クリアです",
    r"きれいです|綺麗です",
]


def _normalize(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def html_to_lines(desc_html: str) -> list[str]:
    if not desc_html:
        return []
    text = re.sub(r"<(?:br|/div|/p|/tr|/li|/h\d|/dd|/dt)[^>]*>", "\n", desc_html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    lines: list[str] = []
    for raw_ln in text.splitlines():
        ln = re.sub(r"\s+", " ", raw_ln).strip()
        if ln:
            lines.append(ln)
    return lines


def _is_disclaimer(line: str) -> bool:
    return any(re.search(pat, line, re.I) for pat in DISCLAIMER_PATTERNS)


def _is_negated_clause(clause: str) -> bool:
    return any(re.search(pat, clause, re.I) for pat in NEGATION_PATTERNS)


def _extract_battery_health(lines: list[str]) -> int | None:
    joined = "\n".join(lines)
    m = re.search(
        r"(?:バッテリー|バッテリ|電池).{0,24}?(?:健康度|残量|容量比|状態|劣化率|最大容量|満充電).{0,10}?(\d{2,3})\s*%",
        joined,
        re.I,
    )
    if m:
        val = int(m.group(1))
        if 10 <= val <= 100:
            return val

    m_des = re.search(r"(?:design\s*capacity|設計容量)\D{0,12}([\d,]{4,6})\s*mwh", joined, re.I)
    m_full = re.search(r"(?:full\s*charge\s*capacity|満充電容量)\D{0,12}([\d,]{4,6})\s*mwh", joined, re.I)
    if m_des and m_full:
        des = int(m_des.group(1).replace(",", ""))
        full = int(m_full.group(1).replace(",", ""))
        if des > 0 and 0 < full <= des * 1.1:
            return min(100, int(round(full / des * 100)))
    return None


def _extract_shutter_count(lines: list[str]) -> int | None:
    joined = _normalize("\n".join(lines))
    m = re.search(r"(?:シャッター回数|ショット数|撮影枚数|総撮影枚数|レリーズ回数)\D{0,12}([\d,]{1,7})\s*(?:回|枚|ショット)?", joined, re.I)
    if m:
        val = int(m.group(1).replace(",", ""))
        if 0 <= val <= 500000:
            return val
    return None


def _backfill_laptop_specs(lines: list[str]) -> tuple[int | None, int | None]:
    ram_gb: int | None = None
    ssd_gb: int | None = None
    for raw_ln in lines:
        ln = _normalize(raw_ln)
        if ram_gb is None:
            m = re.search(r"(?:メイン)?(?:メモリ[ー]?|ram)\s*[:：/\- ]+\D{0,18}?(32|24|16|8)\s*gb", ln, re.I)
            if m:
                ram_gb = int(m.group(1))
        if ssd_gb is None:
            if re.search(r"(?:ストレージ|ssd|ハードディスク)\s*[:：/\- ]+\s*(?:なし|無し|無\b|欠品)", ln, re.I):
                ssd_gb = 0
            else:
                m_tb = re.search(r"(?:ストレージ|ssd|nvme|ハードディスク)\s*[:：/\- ]+\D{0,20}?(1|2)\s*tb", ln, re.I)
                if m_tb:
                    ssd_gb = int(m_tb.group(1)) * 1024
                else:
                    m_gb = re.search(
                        r"(?:ストレージ|ssd|nvme|ハードディスク)\s*[:：/\- ]+\D{0,24}?(1024|1000|512|256|128)\s*gb",
                        ln,
                        re.I,
                    )
                    if m_gb:
                        v = int(m_gb.group(1))
                        ssd_gb = 1024 if v == 1000 else v
    return ram_gb, ssd_gb


def analyze_description(
    lines: list[str],
    category: str = "general",
    is_auto_extend: bool | None = None,
    photo_count: int = 0,
) -> dict[str, Any]:
    tpl = get_template(category)
    severe_rules = list(tpl.get("severe_rules") or []) + list(UNIVERSAL_SEVERE_RULES)
    moderate_rules = list(tpl.get("moderate_rules") or []) + list(UNIVERSAL_MODERATE_RULES)
    minor_rules = list(tpl.get("minor_rules") or []) + list(UNIVERSAL_MINOR_RULES)

    severe_tags: list[str] = []
    moderate_tags: list[str] = []
    minor_tags: list[str] = []
    positives: list[str] = []
    evidence: list[dict[str, str]] = []
    seen_evidence: set[str] = set()

    def _add_evidence(level: str, tag: str, line: str) -> None:
        key = f"{tag}:{line[:60]}"
        if key not in seen_evidence and len(evidence) < 8:
            seen_evidence.add(key)
            evidence.append({"level": level, "tag": tag, "text": line[:140]})

    for raw_ln in lines:
        norm_ln = _normalize(raw_ln)
        if _is_disclaimer(norm_ln):
            continue

        clauses = [c.strip() for c in re.split(r"[。！？\n]+", norm_ln) if c.strip()]
        for clause in clauses:
            if _is_disclaimer(clause):
                continue

            for tag, patterns in severe_rules:
                for pat in patterns:
                    if re.search(pat, clause, re.I):
                        if tag != "实质故障/拆机修理件" and _is_negated_clause(clause):
                            continue
                        if tag not in severe_tags:
                            severe_tags.append(tag)
                        _add_evidence("severe", tag, raw_ln)
                        break

            for tag, patterns in moderate_rules:
                for pat in patterns:
                    if re.search(pat, clause, re.I):
                        if _is_negated_clause(clause):
                            continue
                        if tag not in moderate_tags:
                            moderate_tags.append(tag)
                        _add_evidence("moderate", tag, raw_ln)
                        break

            for tag, patterns in minor_rules:
                for pat in patterns:
                    if re.search(pat, clause, re.I):
                        if tag not in minor_tags:
                            minor_tags.append(tag)
                        _add_evidence("minor", tag, raw_ln)
                        break

            # Category-aware positive highlights
            if category == "laptop":
                if (
                    "无电源适配器" not in minor_tags
                    and "含电源适配器" not in positives
                    and re.search(r"(?:付属品|同梱).{0,24}(?:acアダプタ|電源アダプタ)", clause, re.I)
                    and not re.search(r"付属しません|なし|無し|欠品|別売", clause, re.I)
                ):
                    positives.append("含电源适配器")
            else:
                if "带原盒/配件全" not in positives and re.search(r"付属品完備|元箱あり|元箱付|箱付き|完品", clause, re.I):
                    positives.append("带原盒/配件全")
                if "未开封/几乎未用" not in positives and re.search(r"新品未開封|未開封品|未使用品", clause, re.I):
                    positives.append("未开封/几乎未用")

    battery_pct = _extract_battery_health(lines) if category in ("laptop", "phone_tablet", "console") else None
    if battery_pct is not None:
        min_ok = 75 if category == "phone_tablet" else 60
        if battery_pct < min_ok:
            if "电池明显损耗" not in moderate_tags:
                moderate_tags.append("电池明显损耗")
            _add_evidence("moderate", "电池明显损耗", f"电池最大容量约 {battery_pct}%")
        elif battery_pct >= 80:
            positives.append(f"电池健康约{battery_pct}%")

    shutter_count = _extract_shutter_count(lines) if category == "camera" else None
    if shutter_count is not None:
        positives.append(f"快门约{shutter_count:,}次")

    ram_bf, ssd_bf = _backfill_laptop_specs(lines) if category == "laptop" else (None, None)

    if severe_tags:
        status = "severe"
    elif moderate_tags:
        status = "moderate"
    else:
        status = "clean"

    return {
        "version": INSPECTOR_VERSION,
        "category": category,
        "inspected": True,
        "status": status,
        "severe_tags": severe_tags,
        "moderate_tags": moderate_tags,
        "minor_tags": minor_tags,
        "positives": positives,
        "evidence": evidence,
        "is_auto_extend": is_auto_extend,
        "photo_count": photo_count,
        "battery_health_pct": battery_pct,
        "shutter_count": shutter_count,
        "backfill_ram_gb": ram_bf,
        "backfill_ssd_gb": ssd_bf,
        "checked_at": int(time.time()),
        "error": "",
    }


def fetch_and_inspect_item(auction_id: str, category: str = "general") -> dict[str, Any]:
    """Fetch Yahoo Auctions OR PayPay Flea Market (z...) detail page and inspect description."""
    is_flea = auction_id.startswith("z")
    url = (
        f"https://paypayfleamarket.yahoo.co.jp/item/{auction_id}"
        if is_flea
        else f"https://auctions.yahoo.co.jp/jp/auction/{auction_id}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,zh-CN;q=0.8",
        },
    )
    try:
        if is_flea:
            # Polite serialization for PayPay Flea Market to avoid HTTP 429 rate-limits
            global _FLEA_LAST_TS
            with _FLEA_LOCK:
                wait = 1.4 - (time.time() - _FLEA_LAST_TS)
                if wait > 0:
                    time.sleep(wait)
                with urllib.request.urlopen(req, timeout=16) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                _FLEA_LAST_TS = time.time()
        else:
            with urllib.request.urlopen(req, timeout=16) as resp:
                body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return {
            "version": INSPECTOR_VERSION,
            "category": category,
            "inspected": False,
            "status": "error",
            "severe_tags": [],
            "moderate_tags": [],
            "minor_tags": [],
            "positives": [],
            "evidence": [],
            "checked_at": int(time.time()),
            "error": str(exc),
        }

    m = NEXT_DATA_RE.search(body)
    if not m:
        return {
            "version": INSPECTOR_VERSION,
            "category": category,
            "inspected": False,
            "status": "error",
            "severe_tags": [],
            "moderate_tags": [],
            "minor_tags": [],
            "positives": [],
            "evidence": [],
            "checked_at": int(time.time()),
            "error": "No __NEXT_DATA__ on detail page",
        }

    try:
        data = json.loads(m.group(1))
        if is_flea:
            item = (
                data.get("props", {})
                .get("initialState", {})
                .get("itemsState", {})
                .get("items", {})
                .get("item", {})
            )
            desc_plain = item.get("description") or ""
            lines = [ln.strip() for ln in str(desc_plain).splitlines() if ln.strip()]
            imgs = item.get("images") or item.get("imageUrls") or []
            return analyze_description(
                lines,
                category=category,
                is_auto_extend=False,
                photo_count=len(imgs) if isinstance(imgs, list) else 0,
            )

        item = data["props"]["pageProps"]["initialState"]["item"]["detail"]["item"]
        desc_html = item.get("descriptionHtml") or ""
        desc_plain = item.get("description") or ""
        lines = html_to_lines(desc_html) if desc_html else [ln.strip() for ln in str(desc_plain).splitlines() if ln.strip()]
        is_auto_ext = item.get("isAutomaticExtension")
        if is_auto_ext is None:
            is_auto_ext = item.get("isExtendedAuction")
        imgs = item.get("img") or []
        photo_count = len(imgs) if isinstance(imgs, list) else 0
        return analyze_description(
            lines,
            category=category,
            is_auto_extend=bool(is_auto_ext) if is_auto_ext is not None else None,
            photo_count=photo_count,
        )
    except Exception as exc:
        return {
            "version": INSPECTOR_VERSION,
            "category": category,
            "inspected": False,
            "status": "error",
            "severe_tags": [],
            "moderate_tags": [],
            "minor_tags": [],
            "positives": [],
            "evidence": [],
            "checked_at": int(time.time()),
            "error": f"Parse error: {exc}",
        }
