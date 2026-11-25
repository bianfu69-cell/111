"""SQLite storage for snapshots, price history, alert deduplication, and user marks."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from radar.config import DATA_DIR

DB_PATH = DATA_DIR / "radar.db"
LATEST_JSON_PATH = DATA_DIR / "latest.json"
ALERT_STATE_PATH = DATA_DIR / "alert_state.json"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS item_marks (
            auction_id TEXT PRIMARY KEY,
            starred INTEGER DEFAULT 0,
            ignored INTEGER DEFAULT 0,
            note TEXT DEFAULT '',
            updated_at INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS price_history (
            auction_id TEXT NOT NULL,
            recorded_at INTEGER NOT NULL,
            price_jpy INTEGER NOT NULL,
            bid_count INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_price_history_aid ON price_history(auction_id, recorded_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_log (
            auction_id TEXT PRIMARY KEY,
            last_alert_at INTEGER NOT NULL,
            last_price_jpy INTEGER NOT NULL,
            last_reason TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS item_details (
            auction_id TEXT PRIMARY KEY,
            checked_at INTEGER NOT NULL,
            report_json TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def get_cached_inspections(
    auction_ids: list[str],
    ttl_hours: int = 24,
    min_version: int = 3,
    category_map: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return cached detail inspection reports younger than ttl_hours matching inspector version & category."""
    if not auction_ids:
        return {}
    cutoff = int(time.time()) - ttl_hours * 3600
    result: dict[str, dict[str, Any]] = {}
    with _connect() as conn:
        placeholders = ",".join("?" for _ in auction_ids)
        rows = conn.execute(
            f"SELECT auction_id, report_json FROM item_details WHERE checked_at >= ? AND auction_id IN ({placeholders})",
            [cutoff, *auction_ids],
        ).fetchall()
        for r in rows:
            try:
                rep = json.loads(r["report_json"])
                aid = r["auction_id"]
                wanted_cat = (category_map or {}).get(aid)
                if int(rep.get("version") or 1) >= min_version:
                    if not wanted_cat or rep.get("category") == wanted_cat:
                        result[aid] = rep
            except Exception:
                pass
    return result


def save_cached_inspection(auction_id: str, report: dict[str, Any]) -> None:
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO item_details (auction_id, checked_at, report_json)
            VALUES (?, ?, ?)
            ON CONFLICT(auction_id) DO UPDATE SET
                checked_at = excluded.checked_at,
                report_json = excluded.report_json
            """,
            (auction_id, now, json.dumps(report, ensure_ascii=False)),
        )
        conn.execute("DELETE FROM item_details WHERE checked_at < ?", (now - 10 * 86400,))
        conn.commit()


def get_all_marks() -> dict[str, dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT auction_id, starred, ignored, note FROM item_marks").fetchall()
    return {
        r["auction_id"]: {
            "starred": bool(r["starred"]),
            "ignored": bool(r["ignored"]),
            "note": r["note"] or "",
        }
        for r in rows
    }


def set_item_mark(auction_id: str, starred: bool | None = None, ignored: bool | None = None, note: str | None = None) -> dict[str, Any]:
    now = int(time.time())
    with _connect() as conn:
        cur = conn.execute(
            "SELECT starred, ignored, note FROM item_marks WHERE auction_id = ?",
            (auction_id,),
        ).fetchone()
        new_starred = int(starred) if starred is not None else (int(cur["starred"]) if cur else 0)
        new_ignored = int(ignored) if ignored is not None else (int(cur["ignored"]) if cur else 0)
        new_note = note if note is not None else (cur["note"] if cur else "")
        conn.execute(
            """
            INSERT INTO item_marks (auction_id, starred, ignored, note, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(auction_id) DO UPDATE SET
                starred = excluded.starred,
                ignored = excluded.ignored,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (auction_id, new_starred, new_ignored, new_note, now),
        )
        conn.commit()
    return {"auction_id": auction_id, "starred": bool(new_starred), "ignored": bool(new_ignored), "note": new_note}


def record_price_snapshot(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Store price point if changed since last seen, and return first/previous price metadata."""
    now = int(time.time())
    delta_map: dict[str, dict[str, Any]] = {}
    with _connect() as conn:
        for it in items:
            aid = it["auction_id"]
            price = int(it["price_jpy"])
            bids = int(it["bid_count"])
            rows = conn.execute(
                "SELECT price_jpy, bid_count, recorded_at FROM price_history WHERE auction_id = ? ORDER BY recorded_at ASC",
                (aid,),
            ).fetchall()
            if not rows:
                conn.execute(
                    "INSERT INTO price_history (auction_id, recorded_at, price_jpy, bid_count) VALUES (?, ?, ?, ?)",
                    (aid, now, price, bids),
                )
                delta_map[aid] = {"first_price_jpy": price, "price_delta_jpy": 0, "is_new_seen": True}
            else:
                first_price = int(rows[0]["price_jpy"])
                last_price = int(rows[-1]["price_jpy"])
                last_bids = int(rows[-1]["bid_count"])
                if price != last_price or bids != last_bids:
                    conn.execute(
                        "INSERT INTO price_history (auction_id, recorded_at, price_jpy, bid_count) VALUES (?, ?, ?, ?)",
                        (aid, now, price, bids),
                    )
                delta_map[aid] = {
                    "first_price_jpy": first_price,
                    "price_delta_jpy": price - first_price,
                    "is_new_seen": False,
                }
        # Clean up price history older than 14 days
        conn.execute("DELETE FROM price_history WHERE recorded_at < ?", (now - 14 * 86400,))
        conn.commit()
    return delta_map


def _load_json_alert_state() -> dict[str, dict[str, Any]]:
    if ALERT_STATE_PATH.exists():
        try:
            with ALERT_STATE_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _save_json_alert_state(state: dict[str, dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Prune entries older than 7 days
    cutoff = int(time.time()) - 7 * 86400
    pruned = {k: v for k, v in state.items() if int(v.get("last_alert_at", 0)) >= cutoff}
    with ALERT_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)


def filter_new_alerts(candidates: list[dict[str, Any]], cooldown_minutes: int = 120) -> list[dict[str, Any]]:
    """Deduplicate alerts using both SQLite and portable alert_state.json (for GitHub Actions)."""
    now = int(time.time())
    cooldown_sec = max(10, cooldown_minutes) * 60
    json_state = _load_json_alert_state()
    to_notify: list[dict[str, Any]] = []

    with _connect() as conn:
        for it in candidates:
            aid = it["auction_id"]
            price = int(it["buy_now_price_jpy"] if it.get("alert_reason") == "buy_now" else it["price_jpy"])
            reason = str(it.get("alert_reason") or "ending_soon")
            rem_sec = int(it.get("remaining_sec") or 0)

            row = conn.execute(
                "SELECT last_alert_at, last_price_jpy, last_reason FROM alert_log WHERE auction_id = ?",
                (aid,),
            ).fetchone()
            prev = dict(row) if row else json_state.get(aid)

            should_alert = False
            if not prev:
                should_alert = True
            else:
                elapsed = now - int(prev.get("last_alert_at", 0))
                prev_price = int(prev.get("last_price_jpy", 0))
                # Re-alert if price dropped, or entered final 25-min snipe window after >20min, or cooldown expired
                if price < prev_price:
                    should_alert = True
                elif 0 < rem_sec <= 1500 and elapsed >= 1200:
                    should_alert = True
                elif elapsed >= cooldown_sec:
                    should_alert = True

            if should_alert:
                to_notify.append(it)
                conn.execute(
                    """
                    INSERT INTO alert_log (auction_id, last_alert_at, last_price_jpy, last_reason)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(auction_id) DO UPDATE SET
                        last_alert_at = excluded.last_alert_at,
                        last_price_jpy = excluded.last_price_jpy,
                        last_reason = excluded.last_reason
                    """,
                    (aid, now, price, reason),
                )
                json_state[aid] = {
                    "last_alert_at": now,
                    "last_price_jpy": price,
                    "last_reason": reason,
                }
        conn.commit()

    if to_notify:
        _save_json_alert_state(json_state)
    return to_notify


def save_latest_snapshot(snapshot: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LATEST_JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)


def load_latest_snapshot() -> dict[str, Any] | None:
    if not LATEST_JSON_PATH.exists():
        return None
    try:
        with LATEST_JSON_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
