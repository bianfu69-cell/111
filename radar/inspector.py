"""Deep Yahoo Auctions item detail fetcher & Japanese defect/condition inspector."""

from __future__ import annotations

import html as html_lib
import json
import re
import time
import urllib.request
from typing import Any

INSPECTOR_VERSION = 2

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

# Standard boilerplate / warranty / return policy / grading legend lines
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
    r"対応致しかねます",
    r"対応いたしかねます",
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
]

# Negation cues in a clause ("破損なし", "-バッテリー膨張 : なし", "-画面割れ：なし", "問題見当たりませんでした")
NEGATION_PATTERNS = [
    r"(?:は|も|等)?(?:ありません|ありませんでした|ございません|見当たりません|見られません|感じられません|認められません)",
    r"[:：]\s*(?:なし|無し|無\b|ゼロ|0|ありません|ございません|良好|正常|問題なし|ok|○)\s*$",
    r"(?:割れ|破損|ヒビ|ひび|ムラ|シミ|抜け|不良|異常|欠品|欠損|ガタ|緩み|膨張|傷|キズ|問題|不具合)\s*[:：/\- ]*(?:なし|無し|無\b|ゼロ|0)",
    r"問題なく",
    r"正常に動作",
    r"良好です",
]

# Severe hardware defects (disqualify from steals & phone alerts)
SEVERE_RULES: list[tuple[str, list[str]]] = [
    (
        "铰链损坏/开合异常",
        [
            r"ヒンジ.{0,22}(?:破損|割れ|壊れ|折れ|欠品|欠損|浮き|緩|ガタ|外れ|硬い|ぐらつき|不良|不具合|異常|ダメ|修理|閉まら|開か)",
            r"(?:破損|割れ|欠品|欠損|外れ|浮き).{0,16}ヒンジ",
            r"ヒンジカバー.{0,10}(?:欠品|欠損|割れ|破損|なし|無し|外れ)",
        ],
    ),
    (
        "实质故障/拆机修理件",
        [
            r"部品取り|パーツ取り",
            r"修理してお使い|修理前提|修理が必要|修理ベース|要修理",
            r"ジャンク品|ジャンク扱い|ジャンクとして|ジャンク出品",
            r"起動しない|起動不可|立ち上がらない|電源が入らない|通電不可|通電しない",
            r"通電のみ|起動確認のみ|通電確認のみ|bios確認のみ|動作未確認|未チェック",
            r"biosロック|biosパスワード|パスワードロック|パスワード不明|mdmロック|mdm管理|管理者ロック|bitlocker",
        ],
    ),
    (
        "外壳/机身破损开裂",
        [
            r"(?:天板|底面|筐体|本体|ベゼル|フレーム|パームレスト|角|側面|カバー|ボディ|ポート付近|lanポート|排気口|枠).{0,22}(?:破損|割れ|ヒビ|ひび|亀裂|欠損|大きく凹|大凹|大変形|歪み|変形|浮き)",
            r"(?:破損|割れ|ヒビ|ひび|亀裂)(?:しています|があります|あり|有り|箇所|を確認|が見られ)",
            r"小さなヒビ|小さいヒビ|ヒビあり|割れあり|破損あり|欠けあり|欠損あり",
        ],
    ),
    (
        "屏幕硬伤(裂/线/漏液/不亮)",
        [
            r"(?:液晶|画面|ディスプレイ|パネル).{0,20}(?:割れ|液漏れ|線が入|縦線|横線|ライン抜け|黒点|黒シミ|黒ずみ|映らない|表示不良|表示されない|チラつき|ちらつき|バックライト不良|液晶不良|液晶不調|破損|故障)",
            r"液晶割れ|画面割れ|液晶漏れ|表示不良|縦線あり|横線あり",
        ],
    ),
    (
        "键盘/触控板故障",
        [
            r"(?:キー|キーボード|タッチパッド|トラックパッド|クリック|ボタン).{0,24}(?:反応しない|効かない|入力できない|入力不可|鈍い|チャタリング|連打|不良|故障|欠損|欠品|取れ|外れ|押せない|破損|不具合|反応悪)",
            r"チャタリング",
            r"キートップ.{0,12}(?:外れ|取れ|欠品|欠損|破損|割れ)",
        ],
    ),
    (
        "接口/主板/影音/网卡故障",
        [
            r"(?:usb|type-?c|thunderbolt|hdmi|lan|イヤホン|スピーカー|カメラ|wi-?fi|無線lan|bluetooth|マイク|充電口|ファン|sdスロット).{0,20}(?:不良|故障|使えない|使用不可|認識しない|反応しない|音が出ない|映らない|異音|破損|不具合|動作しない)",
            r"音が出ない|異音がする|ファン異音|充電口.{0,10}(?:緩|不良|破損|接触不良)",
        ],
    ),
    (
        "电池鼓包/无法充电/缺电池",
        [
            r"(?:バッテリー|バッテリ).{0,20}(?:膨張|膨らみ|充電不可|充電できない|認識しない|ng|死亡|故障|不良|欠品|取り外し|無し|なし|使用不可)",
            r"充電できません|充電不可|バッテリー膨張|バッテリ膨張",
        ],
    ),
]

# Moderate cosmetic / functional blemishes (keep visible, warn clearly, penalize score)
MODERATE_RULES: list[tuple[str, list[str]]] = [
    (
        "屏幕白斑/压痕/镀膜磨损",
        [
            r"白ムラ|白いムラ|白シミ|白いシミ|光ムラ|全体.{0,4}ムラ|色ムラ|輝度ムラ|明点|輝点|ドット抜け|圧迫痕|圧迫跡|液晶ヤケ|画面ヤケ|黄ばみ|コーティング剥がれ|コーティング剥げ|キーボード跡|キーボード痕|液晶.{0,14}(?:ムラ|シミ|擦り傷|傷あり|キズあり)",
        ],
    ),
    (
        "机身凹陷/缺脚垫/明显磨损",
        [
            r"ヘコミ|へこみ|凹み|打痕",
            r"ゴム足.{0,10}(?:欠品|欠損|なし|無し|取れ|外れ)",
            r"塗装ハゲ|塗装剥がれ|塗装剥げ|文字消え|印字消え|キー印字消え",
            r"難あり理由|訳あり理由|少難",
        ],
    ),
    (
        "电池明显损耗",
        [
            r"(?:バッテリー|バッテリ).{0,15}(?:劣化|消耗が激|駆動時間短|持ちが悪|弱って)",
        ],
    ),
]

# Minor / accessory notices
MINOR_RULES: list[tuple[str, list[str]]] = [
    (
        "无电源适配器",
        [
            r"(?:acアダプタ[ー]?|電源アダプタ[ー]?|充電器|電源ケーブル).{0,16}(?:付属しません|付属せず|付属なし|付属いたしません|付属致しません|なし|無し|欠品|付きません|別売|含まれません)",
            r"本体のみ.{0,12}(?:ac|アダプタ|電源)",
        ],
    ),
    (
        "无硬盘/无系统",
        [
            r"(?:ssd|ストレージ|ハードディスク).{0,10}(?:なし|無し|欠品|未搭載|取り外し)",
            r"os(?:なし|無し|未インストール|付属しません|は入っていません)",
        ],
    ),
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
    # Match "バッテリー健康度 91%" or "残量 88%" or "DESIGN CAPACITY / FULL CHARGE CAPACITY"
    m = re.search(
        r"(?:バッテリー|バッテリ|電池).{0,24}?(?:健康度|残量|容量比|状態|劣化率|最大容量|満充電).{0,10}?(\d{2,3})\s*%",
        joined,
        re.I,
    )
    if m:
        val = int(m.group(1))
        if 10 <= val <= 100:
            return val

    # Try calculating from Design Capacity & Full Charge Capacity (mWh)
    m_des = re.search(r"(?:design\s*capacity|設計容量)\D{0,12}([\d,]{4,6})\s*mwh", joined, re.I)
    m_full = re.search(r"(?:full\s*charge\s*capacity|満充電容量)\D{0,12}([\d,]{4,6})\s*mwh", joined, re.I)
    if m_des and m_full:
        des = int(m_des.group(1).replace(",", ""))
        full = int(m_full.group(1).replace(",", ""))
        if des > 0 and 0 < full <= des * 1.1:
            return min(100, int(round(full / des * 100)))
    return None


def _backfill_specs(lines: list[str]) -> tuple[int | None, int | None]:
    """Extract RAM GB and SSD GB from the item description specs section."""
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
    is_auto_extend: bool | None = None,
    photo_count: int = 0,
) -> dict[str, Any]:
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

        # Split into sentence clauses so negation in one clause doesn't hide a defect in another
        clauses = [c.strip() for c in re.split(r"[。！？\n]+", norm_ln) if c.strip()]
        for clause in clauses:
            if _is_disclaimer(clause):
                continue

            # Check severe rules first
            matched_severe = False
            for tag, patterns in SEVERE_RULES:
                for pat in patterns:
                    if re.search(pat, clause, re.I):
                        # For non-junk rules, ignore explicitly negated clauses ("破損なし", "割れはありません")
                        if tag != "实质故障/拆机修理件" and _is_negated_clause(clause):
                            continue
                        # Avoid flagging "ACアダプター付属しません" as battery/shell defect
                        if tag not in severe_tags:
                            severe_tags.append(tag)
                        _add_evidence("severe", tag, raw_ln)
                        matched_severe = True
                        break

            # Check moderate rules
            for tag, patterns in MODERATE_RULES:
                for pat in patterns:
                    if re.search(pat, clause, re.I):
                        if _is_negated_clause(clause):
                            continue
                        if tag not in moderate_tags:
                            moderate_tags.append(tag)
                        _add_evidence("moderate", tag, raw_ln)
                        break

            # Check minor rules
            for tag, patterns in MINOR_RULES:
                for pat in patterns:
                    if re.search(pat, clause, re.I):
                        if tag not in minor_tags:
                            minor_tags.append(tag)
                        _add_evidence("minor", tag, raw_ln)
                        break

            # Positive: AC adapter included
            if (
                "无电源适配器" not in minor_tags
                and "含电源适配器" not in positives
                and re.search(r"(?:付属品|同梱).{0,24}(?:acアダプタ|電源アダプタ)", clause, re.I)
                and not re.search(r"付属しません|なし|無し|欠品|別売", clause, re.I)
            ):
                positives.append("含电源适配器")

    battery_pct = _extract_battery_health(lines)
    if battery_pct is not None:
        if battery_pct < 60:
            if "电池明显损耗" not in moderate_tags:
                moderate_tags.append("电池明显损耗")
            _add_evidence("moderate", "电池明显损耗", f"电池容量约 {battery_pct}%")
        elif battery_pct >= 80:
            positives.append(f"电池健康约{battery_pct}%")

    ram_bf, ssd_bf = _backfill_specs(lines)

    if severe_tags:
        status = "severe"
    elif moderate_tags:
        status = "moderate"
    else:
        status = "clean"

    return {
        "version": INSPECTOR_VERSION,
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
        "backfill_ram_gb": ram_bf,
        "backfill_ssd_gb": ssd_bf,
        "checked_at": int(time.time()),
        "error": "",
    }


def fetch_and_inspect_item(auction_id: str) -> dict[str, Any]:
    """Fetch Yahoo Auctions detail page and return deep inspection report."""
    url = f"https://auctions.yahoo.co.jp/jp/auction/{auction_id}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,zh-CN;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=16) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return {
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
        item = data["props"]["pageProps"]["initialState"]["item"]["detail"]["item"]
        desc_html = item.get("descriptionHtml") or ""
        desc_plain = item.get("description") or ""
        lines = html_to_lines(desc_html) if desc_html else [ln.strip() for ln in str(desc_plain).splitlines() if ln.strip()]
        is_auto_ext = item.get("isAutomaticExtension")
        if is_auto_ext is None:
            is_auto_ext = item.get("isExtendedAuction")
        imgs = item.get("img") or []
        photo_count = len(imgs) if isinstance(imgs, list) else 0
        return analyze_description(lines, is_auto_extend=bool(is_auto_ext) if is_auto_ext is not None else None, photo_count=photo_count)
    except Exception as exc:
        return {
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
