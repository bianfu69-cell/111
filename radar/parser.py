"""Dynabook G83 title parser, landed cost calculator, and steal scorer."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

# Hard-exclude keywords (junk, broken, parts, non-laptop accessories)
JUNK_KEYWORDS = [
    "ジャンク",
    "junk",
    "部品取り",
    "パーツ取り",
    "起動不可",
    "起動しない",
    "通電不可",
    "通電しない",
    "通電未確認",
    "動作未確認",
    "画面割れ",
    "液晶割れ",
    "biosロック",
    "biosパスワード",
    "パスワードロック",
    "外観壊れ",
    "破損品",
    "故障品",
    "現状渡し",
    "ノークレーム",
]

ACCESSORY_KEYWORDS = [
    "acアダプタ",
    "電源アダプタ",
    "充電器",
    "電源ケーブル",
    "純正バッテリー",
    "交換用バッテリー",
    "バッテリーのみ",
    "パームレスト",
    "リカバリーディスク",
    "リカバリディスク",
    "リカバリーusb",
    "キーボードのみ",
    "液晶パネルのみ",
    "マザーボードのみ",
    "保護フィルム",
    "覗き見防止",
    "キーボードカバー",
    "キャリングケース",
    "インナーケース",
    "天板のみ",
    "ボトムケース",
    "冷却ファン",
    "ヒンジのみ",
]

# Soft warning tags: keep visible, warn clearly, penalize score
DEFECT_PATTERNS: list[tuple[str, str]] = [
    (r"難あり|少難|訳あり|ワケあり|(?:^|[\s/【(])難(?:$|[\s/】)])", "有瑕疵/难あり"),
    (r"液晶不調|白ムラ|明点|輝点|色ムラ|圧迫痕|シミ|線が入|画面ヤケ|キーボード跡", "屏幕瑕疵/白斑"),
    (r"ストレージ無|ssd無|ssdなし|hdd無|os無|osなし", "无硬盘/无系统"),
    (r"ac無|acなし|アダプタ無|アダプタなし|充電器無", "无电源适配器"),
    (r"バッテリー劣化|バッテリーNG|バッテリー不可|バッテリー不良", "电池损耗/异常"),
    (r"割れ|欠け|ヒビ|凹み|へこみ", "外壳磕碰/裂痕"),
    (r"1円スタート|1円[〜～~]|１円スタート|１円[〜～~]", "1円起拍(尾盘易涨)"),
]

CONDITION_MAP: dict[str, tuple[str, int]] = {
    "NEW": ("全新未拆", 12),
    "USED10": ("99新/几乎未用", 10),
    "USED20": ("95新/无明显划痕", 8),
    "USED40": ("88~90新/轻微痕迹", 2),
    "USED60": ("75~85新/明显痕迹", -8),
    "USED80": ("成色差/整体不良", -25),
}

# Dynabook G83 model suffix -> generation mapping
MODEL_SUFFIX_GEN: dict[str, int] = {
    "MY": 14,
    "MW": 14,
    "LY": 13,
    "LW": 13,
    "LV": 13,
    "KY": 12,
    "KW": 12,
    "KV": 12,
    "HU": 11,
    "HS": 11,
    "HV": 11,
    "HR": 11,
    "FP": 10,
    "FR": 10,
    "FS": 10,
    "DN": 8,
    "DP": 8,
    "M": 8,
}

# CPU pattern -> (generation, tier, normalized label, is_p_series)
CPU_REGEX = re.compile(
    r"(?:core\s*)?(?:ultra\s*(?P<ultra>[57])\s*[- ]?(?P<ultramod>1[25][56][uh])"
    r"|(?P<tier>i[3579])\s*[- ]?(?P<model>(?:13|12|11|10|8)\d{2,3}[a-z0-9]{0,2}))",
    re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
    # Convert full-width ASCII to half-width for reliable regex parsing
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


def _detect_model_suffix(norm_title: str) -> str:
    m = re.search(r"G83\s*[/\- ]\s*([A-Z]{1,2})\b", norm_title, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m2 = re.search(r"G83([A-Z]{2})\b", norm_title, re.IGNORECASE)
    if m2:
        cand = m2.group(1).upper()
        if cand in MODEL_SUFFIX_GEN:
            return cand
    return ""


def _detect_cpu_and_gen(norm_title: str, model_suffix: str) -> tuple[int, str, str, bool]:
    """Return (generation_int, cpu_tier, cpu_model, is_p_series)."""
    m = CPU_REGEX.search(norm_title)
    if m:
        if m.group("ultra"):
            tier = f"Ultra{m.group('ultra')}"
            model = f"Ultra {m.group('ultra')}-{m.group('ultramod').upper()}"
            return 14, tier, model, False
        tier = m.group("tier").lower()
        mod = m.group("model").upper()
        if mod.startswith("13"):
            gen = 13
        elif mod.startswith("12"):
            gen = 12
        elif mod.startswith("11"):
            gen = 11
        elif mod.startswith("10"):
            gen = 10
        elif mod.startswith("8"):
            gen = 8
        else:
            gen = 0
        is_p = mod.endswith("P")
        return gen, tier, f"{tier}-{mod}", is_p

    # Fallback: explicit generation mention in Japanese ("第13世代", "13世代")
    gen = 0
    mg = re.search(r"第?\s*(14|13|12|11|10|8)\s*世代", norm_title)
    if mg:
        gen = int(mg.group(1))
    elif model_suffix in MODEL_SUFFIX_GEN:
        gen = MODEL_SUFFIX_GEN[model_suffix]

    tier_m = re.search(r"core\s*(i[3579])", norm_title, re.IGNORECASE)
    tier = tier_m.group(1).lower() if tier_m else ""

    # Standalone 1340P / 1240P without i5 prefix
    mod_m = re.search(r"\b(1340P|1334U|1345U|1355U|1360P|1315U|1240P|1235U|1245U|1255U|1135G7|1145G7|1165G7)\b", norm_title, re.IGNORECASE)
    if mod_m:
        mod = mod_m.group(1).upper()
        gen = int(mod[:2])
        if not tier:
            tier = "i3" if mod == "1315U" else ("i7" if mod in ("1355U", "1360P", "1255U", "1165G7") else "i5")
        return gen, tier, f"{tier}-{mod}", mod.endswith("P")

    label = f"{tier} 第{gen}代" if (tier and gen) else (f"第{gen}代" if gen else (tier or "未知CPU"))
    return gen, tier, label, False


def _detect_ram_gb(norm_title: str) -> int | None:
    # Explicit RAM keyword patterns first
    explicit = [
        r"(?:メモリ|ﾒﾓﾘ|ram|mem)\s*[:：/\- ]?\s*(32|24|16|8|4)(?:\.\d+)?\s*g(?:b)?\b",
        r"\b(32|24|16|8)gb\s*(?:ram|メモリ|lpddr|ddr)",
        r"[/\s](32|16|8)g(?:b)?\s*[/\s]\s*(?:nvme|ssd|m\.2)?\s*(?:128|256|512|1000|1024|1tb)",
    ]
    for pat in explicit:
        m = re.search(pat, norm_title, re.IGNORECASE)
        if m:
            return int(m.group(1))

    # Fallback: standalone 32GB / 16GB / 8GB not preceded by SSD/NVMe
    for m in re.finditer(r"(?<![a-z0-9])(32|16|8)\s*gb\b", norm_title, re.IGNORECASE):
        prefix = norm_title[max(0, m.start() - 10):m.start()].lower()
        if not any(tok in prefix for tok in ("ssd", "nvme", "hdd", "emmc")):
            return int(m.group(1))
    return None


def _detect_ssd_gb(norm_title: str) -> int | None:
    if re.search(r"ストレージ無|ssd無|ssdなし|ストレージなし", norm_title, re.IGNORECASE):
        return 0

    # Explicit TB patterns
    if re.search(r"(?:ssd|nvme|m\.2|ストレージ)?\s*[:：/\- ]?\s*2\s*tb\b", norm_title, re.IGNORECASE):
        return 2048
    if re.search(r"(?:ssd|nvme|m\.2|ストレージ)?\s*[:：/\- ]?\s*1\s*tb\b", norm_title, re.IGNORECASE):
        return 1024

    # Explicit GB patterns
    explicit = [
        r"(?:nvme\s*ssd|m\.2\s*ssd|ssd|nvme|ストレージ)\s*[:：/\- ]?\s*(1024|1000|512|256|128)\s*g(?:b)?\b",
        r"\b(512|256|128)\s*g(?:b)?\s*(?:nvme|ssd|m\.2)",
        r"(?:32|16|8)g(?:b)?\s*[/\s+]\s*(512|256|128)g(?:b)?\b",
    ]
    for pat in explicit:
        m = re.search(pat, norm_title, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            return 1024 if val == 1000 else val

    # Fallback standalone 512G / 256G / 128G
    m = re.search(r"\b(512|256|128)\s*g(?:b)?\b", norm_title, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _format_remaining(seconds: float) -> str:
    if seconds <= 0:
        return "已结束"
    mins = int(seconds // 60)
    if mins < 60:
        return f"{mins}分钟"
    hours = mins // 60
    rem_m = mins % 60
    if hours < 24:
        return f"{hours}小时{rem_m}分"
    days = hours // 24
    rem_h = hours % 24
    return f"{days}天{rem_h}小时"


def make_doorzo_url(yahoo_url: str) -> str:
    hex_encoded = yahoo_url.encode("utf-8").hex()
    return f"https://www.doorzo.com/zh-hans/mall/yahoo/detail/{hex_encoded}"


def calc_landed_cost(
    price_jpy: int,
    domestic_shipping_jpy: int,
    cost_model: dict[str, Any],
    ssd_gb: int | None,
    effective_fx: float,
) -> dict[str, float]:
    doorzo_fee = float(cost_model.get("doorzo_fee_jpy", 300))
    intl_shipping = float(cost_model.get("intl_shipping_jpy", 4500))
    customs_rate = float(cost_model.get("customs_tax_rate", 0.13))
    ssd_upgrade_cny = float(cost_model.get("ssd_upgrade_256_to_512_cny", 180))

    total_jpy = float(price_jpy) + float(domestic_shipping_jpy) + doorzo_fee + intl_shipping
    untaxed_cny = round(total_jpy * effective_fx, 1)
    customs_est_cny = round(float(price_jpy) * effective_fx * customs_rate, 1)
    with_customs_cny = round(untaxed_cny + customs_est_cny, 1)

    # Apples-to-apples 512GB equivalent cost
    if ssd_gb == 256:
        ssd_adj = ssd_upgrade_cny
    elif ssd_gb == 128 or ssd_gb == 0:
        ssd_adj = ssd_upgrade_cny + 40
    else:
        ssd_adj = 0.0

    effective_512_cny = round(untaxed_cny + ssd_adj, 1)
    return {
        "total_jpy": round(total_jpy, 0),
        "untaxed_cny": untaxed_cny,
        "customs_est_cny": customs_est_cny,
        "with_customs_cny": with_customs_cny,
        "ssd_adj_cny": ssd_adj,
        "effective_512_cny": effective_512_cny,
    }


def parse_yahoo_item(
    raw: dict[str, Any],
    cfg: dict[str, Any],
    fx_rate_base: float,
    now_utc: dt.datetime | None = None,
) -> dict[str, Any] | None:
    """Parse one Yahoo Auctions __NEXT_DATA__ listing item into an enriched G83 record."""
    auction_id = str(raw.get("auctionId") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not auction_id or not title:
        return None

    norm_title = _normalize_text(title)
    lower_title = norm_title.lower()

    # Ensure it's actually a G83 listing
    if "g83" not in lower_title:
        return None

    # Check category path: reject obvious non-laptop categories
    cat_ids = {c.get("id") for c in (raw.get("categoryPath") or []) if isinstance(c, dict)}
    cat_names = " ".join(str(c.get("name") or "") for c in (raw.get("categoryPath") or []))
    is_laptop_cat = (23412 in cat_ids) or ("ノート" in cat_names) or (not cat_ids)
    is_accessory = any(kw in lower_title for kw in ACCESSORY_KEYWORDS) or (not is_laptop_cat)
    if is_accessory:
        return None

    # Condition and junk/defect flags
    cond_code = str(raw.get("itemCondition") or "USED40")
    cond_label, cond_bonus = CONDITION_MAP.get(cond_code, ("二手", 0))
    is_junk = (cond_code == "USED80") or any(kw in lower_title for kw in JUNK_KEYWORDS)

    # Extra check: very suspicious ultra-low buy-now under 6000 JPY is almost always parts/junk
    price_jpy = int(raw.get("price") or 0)
    if price_jpy <= 0:
        return None

    warnings: list[str] = []
    for pat, label in DEFECT_PATTERNS:
        if re.search(pat, norm_title, re.IGNORECASE):
            warnings.append(label)
    if any(kw in norm_title for kw in ("美品", "極美品", "超美品", "優良美品", "未使用")):
        cond_bonus += 5

    # Specs parsing
    model_suffix = _detect_model_suffix(norm_title)
    gen, cpu_tier, cpu_model, is_p_series = _detect_cpu_and_gen(norm_title, model_suffix)
    ram_gb = _detect_ram_gb(norm_title)
    ssd_gb = _detect_ssd_gb(norm_title)

    # Seller & tax details
    seller = raw.get("seller") or {}
    is_store = bool(seller.get("isStore")) or (raw.get("taxFlag") == 1)
    tax_flag = int(raw.get("taxFlag") or 0)
    good_rating = str(seller.get("goodRating") or "")

    # Prices (Yahoo __NEXT_DATA__ `price` and `buyNowPrice` are ALREADY tax-inclusive when taxFlag=1)
    buy_now_jpy = int(raw.get("buyNowPrice") or 0) or None
    is_fixed_price = bool(raw.get("isFixedPrice")) or bool(raw.get("isFleamarketItem")) or (
        buy_now_jpy is not None and buy_now_jpy == price_jpy
    )

    # Domestic shipping
    cost_model = cfg.get("cost_model", {})
    default_dom_ship = int(cost_model.get("default_domestic_shipping_jpy", 1200))
    is_free_shipping = bool(raw.get("isFreeShipping"))
    raw_ship = raw.get("currentPriceShippingFee")
    if is_free_shipping:
        dom_ship_jpy = 0
        dom_ship_known = True
    elif isinstance(raw_ship, (int, float)) and raw_ship >= 0:
        dom_ship_jpy = int(raw_ship)
        dom_ship_known = True
    else:
        dom_ship_jpy = default_dom_ship
        dom_ship_known = False

    # Effective FX rate including Doorzo spread
    spread = float(cost_model.get("fx_spread_pct", 3.5)) / 100.0
    effective_fx = round(fx_rate_base * (1.0 + spread), 6)

    # Compute landed costs for current bid and buy-now
    cur_cost = calc_landed_cost(price_jpy, dom_ship_jpy, cost_model, ssd_gb, effective_fx)
    if buy_now_jpy:
        bn_ship = raw.get("buyNowPriceShippingFee")
        bn_dom_ship = 0 if is_free_shipping else (int(bn_ship) if isinstance(bn_ship, (int, float)) else dom_ship_jpy)
        bn_cost = calc_landed_cost(buy_now_jpy, bn_dom_ship, cost_model, ssd_gb, effective_fx)
    else:
        bn_cost = None

    # End time & remaining seconds
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    end_time_str = str(raw.get("endTime") or "")
    remaining_sec = 0.0
    end_ts = 0
    if end_time_str:
        try:
            end_dt = dt.datetime.fromisoformat(end_time_str)
            end_ts = int(end_dt.timestamp())
            remaining_sec = max(0.0, (end_dt.astimezone(dt.timezone.utc) - now).total_seconds())
        except Exception:
            pass
    if remaining_sec <= 0 and isinstance(raw.get("leftTime"), (int, float)):
        remaining_sec = max(0.0, float(raw["leftTime"]))

    # Generation rules & benchmark comparison
    gen_rules = cfg.get("generation_rules", {})
    gen_key = str(gen) if str(gen) in gen_rules else "other"
    rule = gen_rules.get(gen_key, gen_rules.get("other", {"max_effective_512_cny": 1200, "xianyu_ref_cny": 1500, "label": "其他", "enabled": False}))
    target_cny = float(rule.get("max_effective_512_cny", 2000))
    ref_cny = float(rule.get("xianyu_ref_cny", 2400))

    # Best price metric (if fixed price, effective price is buy-now; otherwise current price)
    gen_enabled = bool(rule.get("enabled", True))
    eff_512 = cur_cost["effective_512_cny"]
    savings_vs_ref = round(ref_cny - eff_512, 1)
    under_budget = gen_enabled and (eff_512 <= target_cny)
    bn_under_budget = gen_enabled and bool(bn_cost and bn_cost["effective_512_cny"] <= target_cny)

    # Steal Score (0 - 100): designed specifically for hunting real Yahoo Auctions bargains
    bid_count = int(raw.get("bidCount") or 0)
    watch_count = int(raw.get("watchCount") or 0)
    rem_min = remaining_sec / 60.0
    is_early_low_start = (not is_fixed_price) and (
        ("1円起拍(尾盘易涨)" in warnings) or (price_jpy <= 5000)
    )
    if is_early_low_start and "1円起拍(尾盘易涨)" not in warnings:
        warnings.append("低价起拍(尾盘易涨)")

    # Use realistic effective discount: cap discount contribution from ultra-low early bids
    discount_ratio = max(-0.5, min(0.55, (ref_cny - eff_512) / max(ref_cny, 1.0)))
    score = 48.0 + discount_ratio * 78.0

    # Time urgency + buy-now bonus
    if bn_under_budget:
        score += 22.0
    elif rem_min <= 30:
        score += 20.0
    elif rem_min <= 120:
        score += 15.0
    elif rem_min <= 240:
        score += 10.0
    elif rem_min <= 480:
        score += 4.0
    elif rem_min > 1440:  # > 24h away
        score -= 12.0

    # Competition realism adjustment
    if is_early_low_start and rem_min > 180:
        score -= 22.0
    elif bid_count == 0 and rem_min <= 240:
        score += 10.0  # Uncontested and ending soon!
    elif bid_count <= 3 and rem_min <= 240:
        score += 5.0
    elif bid_count >= 15:
        score -= 10.0

    if watch_count <= 3 and rem_min <= 240:
        score += 4.0

    # Seller, spec & condition adjustments
    if not is_store:
        score += 6.0  # Personal seller (no tax markup, softer competition)
    if gen == 13 and is_p_series:
        score += 8.0  # Exact user dream CPU (1340P!)
    elif gen == 13 and cpu_tier in ("i5", "i7"):
        score += 5.0
    if ram_gb and ram_gb >= 16:
        score += 4.0
    elif ram_gb == 8:
        score -= 30.0
    if ssd_gb and ssd_gb >= 512:
        score += 4.0
    if cpu_tier == "i3":
        score -= 18.0
    if not gen_enabled:
        score -= 28.0

    score += cond_bonus
    real_defect_count = sum(1 for w in warnings if "起拍" not in w)
    score -= real_defect_count * 12.0

    # Prevent far-away 1-yen / early auctions from dominating the leaderboard over real closing deals
    if not bn_under_budget and not is_fixed_price:
        if is_early_low_start and rem_min > 180:
            score = min(score, 48.0)
        elif rem_min > 1440:
            score = min(score, 58.0)
        elif rem_min > 360:
            score = min(score, 72.0)

    # Over-budget / overpriced items should never score like top steals just for ending soon
    if not under_budget and not bn_under_budget:
        if eff_512 > ref_cny:
            score = min(score, 55.0)
        else:
            score = min(score, 74.0)

    if is_junk:
        score = min(score, 10.0)

    steal_score = int(max(0, min(100, round(score))))

    # Alert eligibility (used by scan engine to trigger phone/desktop alerts)
    flt = cfg.get("filters", {})
    alert_reason = ""
    if (
        rule.get("enabled", True)
        and not is_junk
        and (not flt.get("exclude_i3", True) or cpu_tier != "i3")
        and (not flt.get("require_16gb", True) or (ram_gb is not None and ram_gb >= 16) or (flt.get("allow_unknown_ram", False) and ram_gb is None))
        and (not flt.get("exclude_defects", False) or real_defect_count == 0)
    ):
        if flt.get("alert_buy_now_immediately", True) and bn_under_budget and steal_score >= int(flt.get("alert_min_steal_score", 55)):
            alert_reason = "buy_now"
        elif (
            under_budget
            and 0 < rem_min <= float(flt.get("alert_ending_within_minutes", 180))
            and steal_score >= int(flt.get("alert_min_steal_score", 55))
        ):
            alert_reason = "ending_soon"

    yahoo_url = f"https://auctions.yahoo.co.jp/jp/auction/{auction_id}"
    doorzo_url = make_doorzo_url(yahoo_url)

    gen_label_short = (
        f"Ultra/14代" if gen == 14 else (f"{gen}代" if gen in (13, 12, 11, 10, 8) else "未知代")
    )
    if model_suffix:
        gen_label_short = f"{gen_label_short} G83/{model_suffix}"

    return {
        "auction_id": auction_id,
        "title": title,
        "image_url": str(raw.get("imageUrl") or ""),
        "yahoo_url": yahoo_url,
        "doorzo_url": doorzo_url,
        "generation": gen,
        "gen_key": gen_key,
        "gen_label_short": gen_label_short,
        "model_suffix": model_suffix,
        "cpu_tier": cpu_tier or "unknown",
        "cpu_model": cpu_model,
        "is_p_series": is_p_series,
        "ram_gb": ram_gb,
        "ram_label": f"{ram_gb}GB" if ram_gb else "内存未标",
        "ssd_gb": ssd_gb,
        "ssd_label": ("1TB" if ssd_gb == 1024 else ("2TB" if ssd_gb == 2048 else ("无SSD" if ssd_gb == 0 else (f"{ssd_gb}GB" if ssd_gb else "硬盘未标")))),
        "condition_code": cond_code,
        "condition_label": cond_label,
        "is_junk": is_junk,
        "warnings": warnings,
        "has_defect": real_defect_count > 0,
        "is_store": is_store,
        "tax_flag": tax_flag,
        "seller_rating": good_rating,
        "price_jpy": price_jpy,
        "buy_now_price_jpy": buy_now_jpy,
        "is_fixed_price": is_fixed_price,
        "dom_ship_jpy": dom_ship_jpy,
        "dom_ship_known": dom_ship_known,
        "is_free_shipping": is_free_shipping,
        "effective_fx": effective_fx,
        "untaxed_cny": cur_cost["untaxed_cny"],
        "customs_est_cny": cur_cost["customs_est_cny"],
        "with_customs_cny": cur_cost["with_customs_cny"],
        "ssd_adj_cny": cur_cost["ssd_adj_cny"],
        "effective_512_cny": cur_cost["effective_512_cny"],
        "buy_now_untaxed_cny": bn_cost["untaxed_cny"] if bn_cost else None,
        "buy_now_effective_512_cny": bn_cost["effective_512_cny"] if bn_cost else None,
        "buy_now_with_customs_cny": bn_cost["with_customs_cny"] if bn_cost else None,
        "target_cny": target_cny,
        "ref_cny": ref_cny,
        "savings_vs_ref_cny": savings_vs_ref,
        "under_budget": under_budget,
        "buy_now_under_budget": bn_under_budget,
        "bid_count": bid_count,
        "watch_count": watch_count,
        "end_time": end_time_str,
        "end_ts": end_ts,
        "remaining_sec": int(remaining_sec),
        "remaining_text": _format_remaining(remaining_sec),
        "steal_score": steal_score,
        "alert_reason": alert_reason,
        "detail_inspected": False,
        "detail_status": "unchecked",
        "detail_severe_tags": [],
        "detail_moderate_tags": [],
        "detail_minor_tags": [],
        "detail_positives": [],
        "detail_evidence": [],
        "has_severe_defect": is_junk,
        "is_auto_extend": None,
        "photo_count": 0,
        "battery_health_pct": None,
    }


def apply_inspection(item: dict[str, Any], report: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Merge deep Yahoo description inspection findings into a parsed item and re-score."""
    if not report or not report.get("inspected"):
        return item

    cost_model = cfg.get("cost_model", {})
    flt = cfg.get("filters", {})

    # Backfill missing RAM / SSD if description specified them
    recalc_cost = False
    if item.get("ram_gb") is None and report.get("backfill_ram_gb"):
        item["ram_gb"] = int(report["backfill_ram_gb"])
        item["ram_label"] = f"{item['ram_gb']}GB(正文)"
    if item.get("ssd_gb") is None and report.get("backfill_ssd_gb") is not None:
        ssd_gb = int(report["backfill_ssd_gb"])
        item["ssd_gb"] = ssd_gb
        item["ssd_label"] = (
            "1TB(正文)" if ssd_gb == 1024 else
            ("2TB(正文)" if ssd_gb == 2048 else
            ("无SSD(正文)" if ssd_gb == 0 else f"{ssd_gb}GB(正文)"))
        )
        recalc_cost = True

    if recalc_cost:
        cur_cost = calc_landed_cost(
            int(item["price_jpy"]),
            int(item["dom_ship_jpy"]),
            cost_model,
            item["ssd_gb"],
            float(item["effective_fx"]),
        )
        item["untaxed_cny"] = cur_cost["untaxed_cny"]
        item["customs_est_cny"] = cur_cost["customs_est_cny"]
        item["with_customs_cny"] = cur_cost["with_customs_cny"]
        item["ssd_adj_cny"] = cur_cost["ssd_adj_cny"]
        item["effective_512_cny"] = cur_cost["effective_512_cny"]
        item["savings_vs_ref_cny"] = round(float(item["ref_cny"]) - cur_cost["effective_512_cny"], 1)
        gen_enabled = bool((cfg.get("generation_rules", {}).get(item["gen_key"]) or {}).get("enabled", True))
        item["under_budget"] = gen_enabled and (cur_cost["effective_512_cny"] <= float(item["target_cny"]))
        if item.get("buy_now_price_jpy"):
            bn_cost = calc_landed_cost(
                int(item["buy_now_price_jpy"]),
                int(item["dom_ship_jpy"]),
                cost_model,
                item["ssd_gb"],
                float(item["effective_fx"]),
            )
            item["buy_now_untaxed_cny"] = bn_cost["untaxed_cny"]
            item["buy_now_effective_512_cny"] = bn_cost["effective_512_cny"]
            item["buy_now_with_customs_cny"] = bn_cost["with_customs_cny"]
            item["buy_now_under_budget"] = gen_enabled and (bn_cost["effective_512_cny"] <= float(item["target_cny"]))

    severe_tags = list(report.get("severe_tags") or [])
    moderate_tags = list(report.get("moderate_tags") or [])
    minor_tags = list(report.get("minor_tags") or [])
    positives = list(report.get("positives") or [])
    evidence = list(report.get("evidence") or [])

    item["detail_inspected"] = True
    item["detail_status"] = str(report.get("status") or "clean")
    item["detail_severe_tags"] = severe_tags
    item["detail_moderate_tags"] = moderate_tags
    item["detail_minor_tags"] = minor_tags
    item["detail_positives"] = positives
    item["detail_evidence"] = evidence
    item["is_auto_extend"] = report.get("is_auto_extend")
    item["photo_count"] = int(report.get("photo_count") or 0)
    item["battery_health_pct"] = report.get("battery_health_pct")

    # Update defect/junk flags and re-score rigorously
    has_severe = bool(item.get("is_junk")) or bool(severe_tags)
    item["has_severe_defect"] = has_severe
    if severe_tags or moderate_tags:
        item["has_defect"] = True

    score = float(item["steal_score"])
    if severe_tags:
        # Hard veto: broken hinge / parts-only / cracked shell / dead key / broken screen is NOT a steal!
        score = min(score - 55.0, 18.0)
        item["alert_reason"] = ""
    else:
        if moderate_tags:
            score -= len(moderate_tags) * 14.0
        if minor_tags:
            score -= len(minor_tags) * 4.0
        if not moderate_tags and not item.get("has_defect"):
            score += 4.0  # Bonus for verified-clean description!
        if item.get("ram_gb") == 8:
            score -= 25.0
            item["alert_reason"] = ""

        # Re-check alert eligibility with updated score & defect flags
        min_score = int(flt.get("alert_min_steal_score", 55))
        if flt.get("exclude_defects", False) and moderate_tags:
            item["alert_reason"] = ""
        elif score < min_score:
            item["alert_reason"] = ""
        elif item["alert_reason"] and not (item["under_budget"] or item["buy_now_under_budget"]):
            item["alert_reason"] = ""

    item["steal_score"] = int(max(0, min(100, round(score))))
    return item
