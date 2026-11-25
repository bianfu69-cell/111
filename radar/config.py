"""Configuration & multi-product profiles loading, saving, and secret env overrides."""

from __future__ import annotations

import copy
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from radar.templates import get_template

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.default.json"
PROFILES_PATH = ROOT_DIR / "profiles.json"
DATA_DIR = ROOT_DIR / "data"
USER_CONFIG_PATH = DATA_DIR / "config.json"

ENV_NOTIFICATION_MAP = {
    "pushplus_token": "PUSHPLUS_TOKEN",
    "serverchan_key": "SERVERCHAN_KEY",
    "bark_url": "BARK_URL",
    "feishu_webhook": "FEISHU_WEBHOOK",
    "dingtalk_webhook": "DINGTALK_WEBHOOK",
    "ntfy_topic": "NTFY_TOPIC",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def normalize_profile(raw: dict[str, Any], fallback_idx: int = 1) -> dict[str, Any]:
    """Ensure every user-submitted or loaded product profile has clean, valid defaults."""
    cat_id = str(raw.get("category") or "general").strip()
    tpl = get_template(cat_id)

    name = str(raw.get("name") or f"商品 {fallback_idx}").strip()
    pid = str(raw.get("id") or "").strip()
    if not pid:
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        pid = slug or f"item_{int(time.time())}_{fallback_idx}"

    queries_raw = raw.get("queries")
    if isinstance(queries_raw, str):
        queries = [q.strip() for q in queries_raw.splitlines() if q.strip()]
    elif isinstance(queries_raw, list):
        queries = [str(q).strip() for q in queries_raw if str(q).strip()]
    else:
        queries = [name]

    def _str_list(val: Any) -> list[str]:
        if isinstance(val, str):
            return [s.strip() for s in re.split(r"[,，\n]+", val) if s.strip()]
        if isinstance(val, list):
            return [str(s).strip() for s in val if str(s).strip()]
        return []

    target_cny = max(10.0, float(raw.get("target_cny") or 1000))
    ref_cny = max(target_cny, float(raw.get("ref_cny") or round(target_cny * 1.25)))

    tax_incl = bool(raw.get("tax_included_shipping", tpl["tax_included_shipping"]))
    customs_rate = 0.0 if tax_incl else float(
        raw.get("customs_tax_rate") if raw.get("customs_tax_rate") is not None else tpl["customs_tax_rate"]
    )

    profile: dict[str, Any] = {
        "id": pid,
        "name": name,
        "icon": str(raw.get("icon") or tpl["icon"]),
        "category": tpl["id"],
        "special_preset": str(raw.get("special_preset") or ""),
        "enabled": bool(raw.get("enabled", True)),
        "queries": queries or [name],
        "extra_low_price_queries": _str_list(raw.get("extra_low_price_queries")),
        "must_include": _str_list(raw.get("must_include")),
        "exclude_keywords": _str_list(raw.get("exclude_keywords")),
        "yahoo_category_id": str(
            raw.get("yahoo_category_id") if raw.get("yahoo_category_id") is not None else tpl["yahoo_category_id"]
        ).strip(),
        "max_items_per_query": max(15, min(60, int(raw.get("max_items_per_query") or (50 if pid == "dynabook_g83" else 35)))),
        "target_cny": target_cny,
        "ref_cny": ref_cny,
        "intl_shipping_jpy": max(0, int(raw.get("intl_shipping_jpy") if raw.get("intl_shipping_jpy") is not None else tpl["intl_shipping_jpy"])),
        "default_domestic_shipping_jpy": max(0, int(raw.get("default_domestic_shipping_jpy") if raw.get("default_domestic_shipping_jpy") is not None else tpl["default_domestic_shipping_jpy"])),
        "customs_tax_rate": customs_rate,
        "tax_included_shipping": tax_incl,
        "alert_enabled": bool(raw.get("alert_enabled", True)),
        "alert_ending_within_minutes": max(15, int(raw.get("alert_ending_within_minutes") or 180)),
        "alert_buy_now_immediately": bool(raw.get("alert_buy_now_immediately", True)),
        "alert_min_steal_score": max(20, min(95, int(raw.get("alert_min_steal_score") or 55))),
    }

    if tpl["id"] == "laptop":
        lo = raw.get("laptop_options") or {}
        profile["laptop_options"] = {
            "require_16gb": bool(lo.get("require_16gb", False)),
            "allow_unknown_ram": bool(lo.get("allow_unknown_ram", True)),
            "exclude_i3": bool(lo.get("exclude_i3", False)),
            "ssd_upgrade_256_to_512_cny": float(lo.get("ssd_upgrade_256_to_512_cny") or 0),
            "generation_rules": lo.get("generation_rules") or {},
        }

    return profile


def load_profiles() -> list[dict[str, Any]]:
    if PROFILES_PATH.exists():
        try:
            with PROFILES_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            raw_list = data.get("profiles") if isinstance(data, dict) else data
            if isinstance(raw_list, list) and raw_list:
                return [normalize_profile(p, i + 1) for i, p in enumerate(raw_list) if isinstance(p, dict)]
        except Exception:
            pass
    return []


def save_profiles(profiles_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for idx, p in enumerate(profiles_list, 1):
        norm = normalize_profile(p, idx)
        base_id = norm["id"]
        cand = base_id
        suffix = 2
        while cand in seen_ids:
            cand = f"{base_id}_{suffix}"
            suffix += 1
        norm["id"] = cand
        seen_ids.add(cand)
        cleaned.append(norm)

    payload = {"version": 2, "profiles": cleaned}
    with PROFILES_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return cleaned


def load_config(apply_env: bool = True) -> dict[str, Any]:
    with DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    if USER_CONFIG_PATH.exists():
        try:
            with USER_CONFIG_PATH.open("r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                cfg = deep_merge(cfg, user_cfg)
        except Exception:
            pass

    if apply_env:
        notif = cfg.setdefault("notifications", {})
        for cfg_key, env_name in ENV_NOTIFICATION_MAP.items():
            env_val = os.environ.get(env_name, "").strip()
            if env_val:
                notif[cfg_key] = env_val
        if os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true":
            notif["windows_toast"] = False

    # Always attach active profiles from profiles.json
    cfg["profiles"] = load_profiles()
    return cfg


def save_config(new_cfg: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as f:
        default_cfg = json.load(f)
    clean_new = {k: v for k, v in new_cfg.items() if k != "profiles"}
    merged = deep_merge(default_cfg, clean_new)
    with USER_CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return load_config(apply_env=True)


def mask_secrets(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a safe copy for static public exports (strips push tokens)."""
    safe = copy.deepcopy(cfg)
    notif = safe.get("notifications", {})
    for key in ENV_NOTIFICATION_MAP:
        if notif.get(key):
            notif[key] = "***"
    return safe
