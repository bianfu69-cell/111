"""Multi-category Yahoo Auctions listing parser, landed cost calculator, and steal scorer."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from radar.templates import get_template

# Hard-exclude title keywords (junk, broken, parts)
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
]

# Soft warning patterns on listing title
TITLE_WARNING_PATTERNS: list[tuple[str, str]] = [
    (r"難あり|少難|訳あり|ワケあり|(?:^|[\s/【(])難(?:$|[\s/】)])", "标题标明有瑕疵"),
    (r"液晶不調|白ムラ|明点|輝点|色ムラ|圧迫痕|シミ|線が入|画面ヤケ|キーボード跡", "屏幕瑕疵/白斑"),
    (r"カビ|クモリ|曇り|バルサム", "镜头霉/雾提示"),
    (r"赤ロム|利用制限×|ドリフト", "有锁/漂移提示"),
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

MODEL_SUFFIX_GEN: dict[str, int] = {
    "MY": 14, "MW": 14,
    "LY": 13, "LW": 13, "LV": 13,
    "KY": 12, "KW": 12, "KV": 12,
    "HU": 11, "HS": 11, "HV": 11, "HR": 11,
    "FP": 10, "FR": 10, "FS": 10,
    "DN": 8, "DP": 8, "M": 8,
}

CPU_REGEX = re.compile(
    r"(?:core\s*)?(?:ultra\s*(?P<ultra>[57])\s*[- ]?(?P<ultramod>1[25][56][uh])"
    r"|(?P<tier>i[3579])\s*[- ]?(?P<model>(?:14|13|12|11|10|8)\d{2,3}[a-z0-9]{0,2}))",
    re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
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


def _detect_model_suffix(norm_title: str) -> tuple[str, int]:
    """Return (display_model_tag, inferred_gen) for Dynabook G83 or Fujitsu LIFEBOOK U-series."""
    m = re.search(r"G83\s*[/\- ]\s*([A-Z]{1,2})\b", norm_title, re.IGNORECASE)
    if m:
        suf = m.group(1).upper()
        return f"G83/{suf}", MODEL_SUFFIX_GEN.get(suf, 0)
    m2 = re.search(r"G83([A-Z]{2})\b", norm_title, re.IGNORECASE)
    if m2 and m2.group(1).upper() in MODEL_SUFFIX_GEN:
        suf = m2.group(1).upper()
        return f"G83/{suf}", MODEL_SUFFIX_GEN[suf]

    # Fujitsu LIFEBOOK U9313 / U9311 / U7313 / U9312 / U9413 / U7314
    mf = re.search(r"\b(U[79][34](1[1234])X?)\b", norm_title, re.IGNORECASE)
    if mf:
        model_code = mf.group(1).upper()
        gen_num = int(mf.group(2))
        return model_code, gen_num
    return "", 0


def _detect_cpu_and_gen(norm_title: str, inferred_gen: int = 0) -> tuple[int, str, str, bool]:
    # Low-end Celeron / Pentium detection (common trap on U9311!)
    if re.search(r"\b(?:celeron|pentium|6305)\b", norm_title, re.IGNORECASE):
        return inferred_gen, "celeron", "Celeron(低配)", False

    # Apple Silicon detection for MacBook profiles
    m_apple = re.search(r"\b(M[1234]\s*(?:Pro|Max|Ultra)?)\b", norm_title, re.IGNORECASE)
    if m_apple and any(w in norm_title.lower() for w in ("macbook", "mac", "apple", "air", "pro")):
        chip = re.sub(r"\s+", " ", m_apple.group(1).upper())
        return 0, "apple", chip, ("PRO" in chip or "MAX" in chip)

    m = CPU_REGEX.search(norm_title)
    if m:
        if m.group("ultra"):
            tier = f"Ultra{m.group('ultra')}"
            model = f"Ultra {m.group('ultra')}-{m.group('ultramod').upper()}"
            return 14, tier, model, False
        tier = m.group("tier").lower()
        mod = m.group("model").upper()
        gen = int(mod[:2]) if mod[:2] in ("14", "13", "12", "11", "10") else (8 if mod.startswith("8") else 0)
        return gen, tier, f"{tier}-{mod}", mod.endswith("P")

    gen = 0
    mg = re.search(r"第?\s*(14|13|12|11|10|8)\s*世代", norm_title)
    if mg:
        gen = int(mg.group(1))
    elif inferred_gen:
        gen = inferred_gen

    tier_m = re.search(r"core\s*(i[3579])", norm_title, re.IGNORECASE)
    tier = tier_m.group(1).lower() if tier_m else ""

    mod_m = re.search(
        r"\b(1370P|1360P|1350P|1340P|1365U|1355U|1345U|1335U|1334U|1315U|1270P|1260P|1240P|1265U|1255U|1245U|1235U|1185G7|1165G7|1145G7|1135G7)\b",
        norm_title,
        re.IGNORECASE,
    )
    if mod_m:
        mod = mod_m.group(1).upper()
        gen = int(mod[:2])
        if not tier:
            if mod == "1315U":
                tier = "i3"
            elif mod in ("1370P", "1360P", "1365U", "1355U", "1270P", "1260P", "1265U", "1255U", "1185G7", "1165G7"):
                tier = "i7"
            else:
                tier = "i5"
        return gen, tier, f"{tier}-{mod}", mod.endswith("P")

    # Ryzen detection
    m_ry = re.search(r"ryzen\s*([3579])\s*[- ]?(\d{4}[a-z]{0,2})", norm_title, re.IGNORECASE)
    if m_ry:
        return 0, f"r{m_ry.group(1)}", f"Ryzen {m_ry.group(1)}-{m_ry.group(2).upper()}", False

    label = f"{tier} 第{gen}代" if (tier and gen) else (f"第{gen}代" if gen else (tier or "CPU未标"))
    return gen, tier, label, False


def _detect_ram_gb(norm_title: str) -> int | None:
    explicit = [
        r"(?:メモリ|ﾒﾓﾘ|ram|mem)\s*[:：/\- ]?\s*(64|32|24|16|8|4)(?:\.\d+)?\s*g(?:b)?\b",
        r"\b(64|32|24|16|8)gb\s*(?:ram|メモリ|lpddr|ddr)",
        r"[/\s+](64|32|24|16|8)g(?:b)?\s*[/\s+]\s*(?:nvme|ssd|m\.2)?\s*(?:128|256|512|1000|1024|1tb)",
    ]
    for pat in explicit:
        m = re.search(pat, norm_title, re.IGNORECASE)
        if m:
            return int(m.group(1))
    for m in re.finditer(r"(?<![a-z0-9])(64|32|24|16|8)\s*gb\b", norm_title, re.IGNORECASE):
        prefix = norm_title[max(0, m.start() - 10):m.start()].lower()
        if not any(tok in prefix for tok in ("ssd", "nvme", "hdd", "emmc")):
            return int(m.group(1))
    return None


def _detect_ssd_gb(norm_title: str) -> int | None:
    if re.search(r"ストレージ無|ssd無|ssdなし|ストレージなし", norm_title, re.IGNORECASE):
        return 0
    if re.search(r"(?:ssd|nvme|m\.2|ストレージ)?\s*[:：/\- ]?\s*2\s*tb\b", norm_title, re.IGNORECASE):
        return 2048
    if re.search(r"(?:ssd|nvme|m\.2|ストレージ)?\s*[:：/\- ]?\s*1\s*tb\b", norm_title, re.IGNORECASE):
        return 1024
    explicit = [
        r"(?:nvme\s*ssd|m\.2\s*ssd|ssd|nvme|ストレージ)\s*[:：/\- ]?\s*(1024|1000|512|256|128)\s*g(?:b)?\b",
        r"\b(512|256|128)\s*g(?:b)?\s*(?:nvme|ssd|m\.2)",
        r"(?:64|32|16|8)g(?:b)?\s*[/\s+]\s*(512|256|128)g(?:b)?\b",
    ]
    for pat in explicit:
        m = re.search(pat, norm_title, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            return 1024 if val == 1000 else val
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


def make_doorzo_url(source_url: str, is_fleamarket: bool = False) -> str:
    mall = "paypay" if is_fleamarket else "yahoo"
    return f"https://www.doorzo.com/zh-hans/mall/{mall}/detail/{source_url.encode('utf-8').hex()}"


def calc_landed_cost(
    price_jpy: int,
    domestic_shipping_jpy: int,
    profile: dict[str, Any],
    cost_model: dict[str, Any],
    ssd_gb: int | None,
    effective_fx: float,
) -> dict[str, float]:
    doorzo_fee = float(cost_model.get("doorzo_fee_jpy", 300))
    intl_shipping = float(profile.get("intl_shipping_jpy", 2000))
    tax_incl = bool(profile.get("tax_included_shipping", False))
    customs_rate = 0.0 if tax_incl else float(profile.get("customs_tax_rate", 0.13))

    lo = profile.get("laptop_options") or {}
    ssd_upgrade_cny = float(lo.get("ssd_upgrade_256_to_512_cny", 0)) if profile.get("category") == "laptop" else 0.0

    total_jpy = float(price_jpy) + float(domestic_shipping_jpy) + doorzo_fee + intl_shipping
    untaxed_cny = round(total_jpy * effective_fx, 1)
    customs_est_cny = round(float(price_jpy) * effective_fx * customs_rate, 1)
    with_customs_cny = round(untaxed_cny + customs_est_cny, 1)

    if ssd_upgrade_cny > 0:
        if ssd_gb == 256:
            ssd_adj = ssd_upgrade_cny
        elif ssd_gb in (128, 0):
            ssd_adj = ssd_upgrade_cny + 40.0
        else:
            ssd_adj = 0.0
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
    profile: dict[str, Any],
    cfg: dict[str, Any],
    fx_rate_base: float,
    now_utc: dt.datetime | None = None,
) -> dict[str, Any] | None:
    """Parse one Yahoo Auctions listing item under a specific user product profile."""
    auction_id = str(raw.get("auctionId") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not auction_id or not title:
        return None

    norm_title = _normalize_text(title)
    lower_title = norm_title.lower()
    category = str(profile.get("category") or "general")
    tpl = get_template(category)

    # Profile-level must_include & custom exclude_keywords
    must_inc = [str(w).strip().lower() for w in (profile.get("must_include") or []) if str(w).strip()]
    if must_inc and not any(tok in lower_title for tok in must_inc):
        return None

    custom_excl = [str(w).strip().lower() for w in (profile.get("exclude_keywords") or []) if str(w).strip()]
    if custom_excl and any(tok in lower_title for tok in custom_excl):
        return None

    # Category-level accessory exclusion
    acc_kws = [w.lower() for w in (tpl.get("accessory_keywords") or [])]
    if any(kw in lower_title for kw in acc_kws):
        return None

    # For laptop profiles, also reject obvious non-laptop categories
    if category == "laptop":
        cat_ids = {c.get("id") for c in (raw.get("categoryPath") or []) if isinstance(c, dict)}
        cat_names = " ".join(str(c.get("name") or "") for c in (raw.get("categoryPath") or []))
        is_laptop_cat = (23412 in cat_ids) or ("ノート" in cat_names) or (not cat_ids)
        if not is_laptop_cat:
            return None

    price_jpy = int(raw.get("price") or 0)
    if price_jpy <= 0:
        return None

    # Condition and junk/warning flags
    cond_code = str(raw.get("itemCondition") or "USED40")
    cond_label, cond_bonus = CONDITION_MAP.get(cond_code, ("二手", 0))
    is_junk = (cond_code == "USED80") or any(kw in lower_title for kw in JUNK_KEYWORDS)

    warnings: list[str] = []
    for pat, label in TITLE_WARNING_PATTERNS:
        if re.search(pat, norm_title, re.IGNORECASE):
            warnings.append(label)
    if any(kw in norm_title for kw in ("美品", "極美品", "超美品", "優良美品", "未使用", "未開封")):
        cond_bonus += 5

    # Specs parsing (laptop-specific vs universal)
    is_laptop = category == "laptop"
    if is_laptop:
        model_tag, inferred_gen = _detect_model_suffix(norm_title)
        model_suffix = model_tag
        gen, cpu_tier, cpu_model, is_p_series = _detect_cpu_and_gen(norm_title, inferred_gen)
        ram_gb = _detect_ram_gb(norm_title)
        ssd_gb = _detect_ssd_gb(norm_title)
        gen_label_short = (
            "Ultra/14代" if gen == 14 else (f"{gen}代" if gen in (13, 12, 11, 10, 8) else ("Apple Silicon" if cpu_tier == "apple" else "笔记本"))
        )
        if model_tag:
            gen_label_short = f"{gen_label_short} {model_tag}"
    else:
        model_suffix = ""
        gen, cpu_tier, cpu_model, is_p_series = 0, "", "", False
        ram_gb = None
        ssd_gb = None
        # Detect storage capacity on phones/tablets/consoles (e.g., 128GB/256GB/512GB/1TB)
        if category in ("phone_tablet", "console"):
            m_st = re.search(r"\b(1TB|512GB|256GB|128GB|64GB)\b", norm_title, re.IGNORECASE)
            if m_st:
                cpu_model = m_st.group(1).upper()
        gen_label_short = f"{profile['name']}"

    # Seller & pricing
    seller = raw.get("seller") or {}
    is_store = bool(seller.get("isStore")) or (raw.get("taxFlag") == 1)
    tax_flag = int(raw.get("taxFlag") or 0)
    good_rating = str(seller.get("goodRating") or "")

    buy_now_jpy = int(raw.get("buyNowPrice") or 0) or None
    is_fixed_price = bool(raw.get("isFixedPrice")) or bool(raw.get("isFleamarketItem")) or (
        buy_now_jpy is not None and buy_now_jpy == price_jpy
    )

    # Domestic shipping
    cost_model = cfg.get("cost_model", {})
    default_dom_ship = int(profile.get("default_domestic_shipping_jpy", 1000))
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

    spread = float(cost_model.get("fx_spread_pct", 3.5)) / 100.0
    effective_fx = round(fx_rate_base * (1.0 + spread), 6)

    cur_cost = calc_landed_cost(price_jpy, dom_ship_jpy, profile, cost_model, ssd_gb, effective_fx)
    if buy_now_jpy:
        bn_ship = raw.get("buyNowPriceShippingFee")
        bn_dom_ship = 0 if is_free_shipping else (int(bn_ship) if isinstance(bn_ship, (int, float)) else dom_ship_jpy)
        bn_cost = calc_landed_cost(buy_now_jpy, bn_dom_ship, profile, cost_model, ssd_gb, effective_fx)
    else:
        bn_cost = None

    # End time
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

    # Target & Benchmark Rules (supports per-generation rules for G83 / laptops, or simple profile target)
    lo = profile.get("laptop_options") or {}
    gen_rules = lo.get("generation_rules") or {} if is_laptop else {}
    if gen_rules:
        gen_key = str(gen) if str(gen) in gen_rules else "other"
        rule = gen_rules.get(gen_key, gen_rules.get("other", {}))
        gen_enabled = bool(rule.get("enabled", True))
        target_cny = float(rule.get("max_effective_512_cny", profile.get("target_cny", 2000)))
        ref_cny = float(rule.get("xianyu_ref_cny", profile.get("ref_cny", 2400)))
    else:
        gen_key = "all"
        gen_enabled = True
        target_cny = float(profile.get("target_cny", 1000))
        ref_cny = float(profile.get("ref_cny", round(target_cny * 1.25)))

    eff_512 = cur_cost["effective_512_cny"]
    savings_vs_ref = round(ref_cny - eff_512, 1)
    under_budget = gen_enabled and (eff_512 <= target_cny)
    bn_under_budget = gen_enabled and bool(bn_cost and bn_cost["effective_512_cny"] <= target_cny)

    # Steal Score (0 - 100)
    bid_count = int(raw.get("bidCount") or 0)
    watch_count = int(raw.get("watchCount") or 0)
    rem_min = remaining_sec / 60.0

    # Early low-start detection (relative to target price so cheap 100-RMB figures aren't wrongly penalized!)
    low_start_threshold_jpy = min(5000, max(500, int((target_cny / max(effective_fx, 0.01)) * 0.12)))
    is_early_low_start = (not is_fixed_price) and (
        ("1円起拍(尾盘易涨)" in warnings) or (price_jpy <= low_start_threshold_jpy)
    )
    if is_early_low_start and "1円起拍(尾盘易涨)" not in warnings:
        warnings.append("低价起拍(尾盘易涨)")

    discount_ratio = max(-0.5, min(0.55, (ref_cny - eff_512) / max(ref_cny, 1.0)))
    score = 48.0 + discount_ratio * 78.0

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
    elif rem_min > 1440:
        score -= 12.0

    if is_early_low_start and rem_min > 180:
        score -= 22.0
    elif bid_count == 0 and rem_min <= 240:
        score += 10.0
    elif bid_count <= 3 and rem_min <= 240:
        score += 5.0
    elif bid_count >= 15:
        score -= 10.0

    if watch_count <= 3 and rem_min <= 240:
        score += 4.0

    if not is_store:
        score += 6.0

    # Laptop spec bonuses (strong reward for high-tier i7 / P-series CPUs like i7-1370P, i5-1350P, i5-1340P)
    if is_laptop:
        if is_p_series and cpu_tier == "i7":
            score += 14.0
        elif is_p_series:
            score += 10.0
        elif cpu_tier == "i7":
            score += 7.0
        elif gen >= 13 and cpu_tier == "i5":
            score += 5.0

        if ram_gb and ram_gb >= 24:
            score += 7.0
        elif ram_gb and ram_gb >= 16:
            score += 4.0
        elif ram_gb == 8 and lo.get("require_16gb"):
            score -= 30.0
        if ssd_gb and ssd_gb >= 512:
            score += 4.0
        if cpu_tier == "celeron":
            score -= 35.0
        elif cpu_tier == "i3" and lo.get("exclude_i3"):
            score -= 18.0
        if not gen_enabled:
            score -= 28.0

    score += cond_bonus
    real_defect_count = sum(1 for w in warnings if "起拍" not in w)
    score -= real_defect_count * 12.0

    if not bn_under_budget and not is_fixed_price:
        if is_early_low_start and rem_min > 180:
            score = min(score, 48.0)
        elif rem_min > 1440:
            score = min(score, 58.0)
        elif rem_min > 360:
            score = min(score, 72.0)

    if not under_budget and not bn_under_budget:
        if eff_512 > ref_cny:
            score = min(score, 55.0)
        else:
            score = min(score, 74.0)

    if is_junk:
        score = min(score, 10.0)

    steal_score = int(max(0, min(100, round(score))))

    # Alert eligibility
    alert_reason = ""
    ram_ok = True
    i3_ok = True
    if is_laptop:
        if lo.get("require_16gb"):
            ram_ok = (ram_gb is not None and ram_gb >= 16) or (bool(lo.get("allow_unknown_ram")) and ram_gb is None)
        if lo.get("exclude_i3"):
            i3_ok = cpu_tier not in ("i3", "celeron")

    min_alert_score = int(profile.get("alert_min_steal_score", 55))
    alert_win = float(profile.get("alert_ending_within_minutes", 180))
    if profile.get("alert_enabled", True) and gen_enabled and not is_junk and ram_ok and i3_ok:
        if profile.get("alert_buy_now_immediately", True) and bn_under_budget and steal_score >= min_alert_score:
            alert_reason = "buy_now"
        elif under_budget and 0 < rem_min <= alert_win and steal_score >= min_alert_score:
            alert_reason = "ending_soon"

    is_fleamarket = bool(raw.get("isFleamarketItem")) or auction_id.startswith("z")
    yahoo_url = (
        f"https://paypayfleamarket.yahoo.co.jp/item/{auction_id}"
        if is_fleamarket
        else f"https://auctions.yahoo.co.jp/jp/auction/{auction_id}"
    )
    doorzo_url = make_doorzo_url(yahoo_url, is_fleamarket=is_fleamarket)

    return {
        "item_key": f"{profile['id']}:{auction_id}",
        "profile_id": profile["id"],
        "profile_name": profile["name"],
        "profile_icon": profile.get("icon") or tpl["icon"],
        "category": category,
        "category_name": tpl["name"],
        "tax_included_shipping": bool(profile.get("tax_included_shipping", False)),
        "auction_id": auction_id,
        "title": title,
        "image_url": str(raw.get("imageUrl") or ""),
        "yahoo_url": yahoo_url,
        "doorzo_url": doorzo_url,
        "generation": gen,
        "gen_key": gen_key,
        "gen_label_short": gen_label_short,
        "model_suffix": model_suffix,
        "cpu_tier": cpu_tier or "",
        "cpu_model": cpu_model,
        "is_p_series": is_p_series,
        "ram_gb": ram_gb,
        "ram_label": (f"{ram_gb}GB" if ram_gb else ("内存未标" if is_laptop else "")),
        "ssd_gb": ssd_gb,
        "ssd_label": (
            "1TB" if ssd_gb == 1024 else
            ("2TB" if ssd_gb == 2048 else
            ("无SSD" if ssd_gb == 0 else
            (f"{ssd_gb}GB" if ssd_gb else ("硬盘未标" if is_laptop else ""))))
        ),
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
        "intl_shipping_jpy": int(profile.get("intl_shipping_jpy", 2000)),
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
        "shutter_count": None,
    }


def apply_inspection(
    item: dict[str, Any],
    report: dict[str, Any],
    profile: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Merge category-aware Yahoo description inspection findings into a parsed item and re-score."""
    if not report or not report.get("inspected"):
        return item

    cost_model = cfg.get("cost_model", {})
    is_laptop = item.get("category") == "laptop"
    lo = profile.get("laptop_options") or {}

    recalc_cost = False
    if is_laptop:
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
            profile,
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
        gen_rules = lo.get("generation_rules") or {}
        gen_enabled = bool((gen_rules.get(item["gen_key"]) or {}).get("enabled", True)) if gen_rules else True
        item["under_budget"] = gen_enabled and (cur_cost["effective_512_cny"] <= float(item["target_cny"]))
        if item.get("buy_now_price_jpy"):
            bn_cost = calc_landed_cost(
                int(item["buy_now_price_jpy"]),
                int(item["dom_ship_jpy"]),
                profile,
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
    item["shutter_count"] = report.get("shutter_count")

    has_severe = bool(item.get("is_junk")) or bool(severe_tags)
    item["has_severe_defect"] = has_severe
    if severe_tags or moderate_tags:
        item["has_defect"] = True

    score = float(item["steal_score"])
    if severe_tags:
        score = min(score - 55.0, 18.0)
        item["alert_reason"] = ""
    else:
        if moderate_tags:
            score -= len(moderate_tags) * 14.0
        if minor_tags:
            score -= len(minor_tags) * 4.0
        if not moderate_tags and not item.get("has_defect"):
            score += 4.0
        if is_laptop and item.get("ram_gb") == 8 and lo.get("require_16gb"):
            score -= 25.0
            item["alert_reason"] = ""

        min_score = int(profile.get("alert_min_steal_score", 55))
        if score < min_score:
            item["alert_reason"] = ""
        elif item["alert_reason"] and not (item["under_budget"] or item["buy_now_under_budget"]):
            item["alert_reason"] = ""

    item["steal_score"] = int(max(0, min(100, round(score))))
    return item
