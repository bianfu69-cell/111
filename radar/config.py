"""Configuration loading, merging, and environment secret overrides."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.default.json"
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

    return cfg


def save_config(new_cfg: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as f:
        default_cfg = json.load(f)
    merged = deep_merge(default_cfg, new_cfg)
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
