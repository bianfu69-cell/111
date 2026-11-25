"""Local Multi-Category Web Dashboard, Profile CRUD, GitHub Sync & Auto-Polling Server."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from radar.config import ROOT_DIR, load_config, load_profiles, save_config, save_profiles
from radar.engine import run_scan
from radar.inspector import fetch_and_inspect_item
from radar.notifier import send_notification
from radar.parser import apply_inspection
from radar.storage import load_latest_snapshot, save_cached_inspection, save_latest_snapshot, set_item_mark
from radar.templates import list_templates_public

WEB_DIR = ROOT_DIR / "web"


class RadarState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.scanning = False
        self.last_error = ""
        self.next_scan_ts = 0
        self.snapshot: dict[str, Any] | None = load_latest_snapshot()

    def trigger_scan(self, send_alerts: bool = True, export_static: bool = True) -> dict[str, Any]:
        with self.lock:
            if self.scanning:
                return {"status": "already_scanning", "snapshot": self.snapshot}
            self.scanning = True
            self.last_error = ""

        try:
            cfg = load_config(apply_env=True)
            snap = run_scan(cfg=cfg, send_alerts=send_alerts, export_static=export_static)
            interval_min = max(2, int(cfg.get("poll_interval_minutes", 10)))
            with self.lock:
                self.snapshot = snap
                self.next_scan_ts = int(time.time()) + interval_min * 60
            return {"status": "ok", "snapshot": snap}
        except Exception as exc:
            with self.lock:
                self.last_error = str(exc)
            return {"status": "error", "error": str(exc), "snapshot": self.snapshot}
        finally:
            with self.lock:
                self.scanning = False


STATE = RadarState()


def _sync_profiles_to_github() -> tuple[bool, str]:
    """Commit profiles.json (and docs/) and push cleanly to origin/main."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_EDITOR"] = "true"

    def _git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(ROOT_DIR),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=35,
        )

    try:
        _git("add", "profiles.json", "docs/")
        diff = _git("diff", "--staged", "--quiet")
        if diff.returncode != 0:
            c = _git("commit", "-m", "chore: update monitored product profiles")
            if c.returncode != 0:
                return False, (c.stderr or c.stdout or "git commit failed")[:220]

        pull = _git("pull", "--rebase", "--autostash", "origin", "main")
        if pull.returncode != 0:
            _git("checkout", "--theirs", "docs/data.json", "docs/index.html")
            _git("add", "docs/data.json", "docs/index.html")
            _git("rebase", "--continue")

        push = _git("push", "origin", "main")
        if push.returncode != 0:
            return False, (push.stderr or push.stdout or "git push failed")[:260]
        return True, "已成功同步到 GitHub 云端！云端定时巡检与手机榜单将自动生效。"
    except Exception as exc:
        return False, str(exc)


def _background_poller(stop_event: threading.Event) -> None:
    snap = STATE.snapshot
    need_now = (not snap) or (int(snap.get("version") or 1) < 2) or (time.time() - int(snap.get("scanned_ts", 0)) > 300)
    if need_now:
        STATE.trigger_scan(send_alerts=True, export_static=True)
    else:
        cfg = load_config(apply_env=True)
        interval_min = max(2, int(cfg.get("poll_interval_minutes", 10)))
        STATE.next_scan_ts = int(time.time()) + interval_min * 60

    while not stop_event.is_set():
        stop_event.wait(5.0)
        if stop_event.is_set():
            break
        if STATE.next_scan_ts and time.time() >= STATE.next_scan_ts and not STATE.scanning:
            STATE.trigger_scan(send_alerts=True, export_static=True)


class RadarHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else {}

    def _serve_static(self, rel_path: str) -> None:
        clean = rel_path.lstrip("/") or "index.html"
        target = (WEB_DIR / clean).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        mime, _ = mimetypes.guess_type(str(target))
        content = target.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            f"{mime or 'application/octet-stream'}; charset=utf-8"
            if (mime or "").startswith(("text/", "application/javascript"))
            else (mime or "application/octet-stream"),
        )
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/snapshot":
            with STATE.lock:
                snap = STATE.snapshot
                meta = {
                    "mode": "local_server",
                    "scanning": STATE.scanning,
                    "last_error": STATE.last_error,
                    "next_scan_ts": STATE.next_scan_ts,
                }
            self._send_json({"meta": meta, "snapshot": snap})
            return

        if path == "/api/config":
            self._send_json(load_config(apply_env=True))
            return

        if path == "/api/profiles":
            self._send_json({"profiles": load_profiles(), "templates": list_templates_public()})
            return

        if path == "/api/health":
            self._send_json({"ok": True, "scanning": STATE.scanning})
            return

        self._serve_static(path)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/scan":
            body = self._read_json_body()
            send_alerts = bool(body.get("send_alerts", True))
            res = STATE.trigger_scan(send_alerts=send_alerts, export_static=True)
            self._send_json(res, status=200 if res.get("status") != "error" else 500)
            return

        if path == "/api/profiles":
            try:
                body = self._read_json_body()
                raw_profiles = body.get("profiles")
                if not isinstance(raw_profiles, list) or not raw_profiles:
                    self._send_json({"ok": False, "error": "至少保留 1 个监控商品"}, status=400)
                    return
                saved = save_profiles(raw_profiles)
                sync_gh = bool(body.get("sync_github", False))
                run_now = bool(body.get("scan_now", True))
                sync_res = {"ok": None, "message": ""}
                if run_now:
                    res = STATE.trigger_scan(send_alerts=False, export_static=True)
                    if res.get("status") == "error":
                        self._send_json({"ok": False, "error": res.get("error"), "profiles": saved}, status=500)
                        return
                if sync_gh:
                    ok_gh, msg_gh = _sync_profiles_to_github()
                    sync_res = {"ok": ok_gh, "message": msg_gh}
                self._send_json({"ok": True, "profiles": saved, "snapshot": STATE.snapshot, "sync": sync_res})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if path == "/api/sync-github":
            ok_gh, msg_gh = _sync_profiles_to_github()
            self._send_json({"ok": ok_gh, "message": msg_gh}, status=200 if ok_gh else 500)
            return

        if path == "/api/config":
            try:
                body = self._read_json_body()
                saved = save_config(body)
                threading.Thread(
                    target=STATE.trigger_scan,
                    kwargs={"send_alerts": False, "export_static": True},
                    daemon=True,
                ).start()
                self._send_json({"ok": True, "config": saved})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if path == "/api/mark":
            try:
                body = self._read_json_body()
                aid = str(body.get("auction_id") or "").strip()
                if not aid:
                    self._send_json({"ok": False, "error": "Missing auction_id"}, status=400)
                    return
                res = set_item_mark(
                    aid,
                    starred=body.get("starred"),
                    ignored=body.get("ignored"),
                    note=body.get("note"),
                )
                with STATE.lock:
                    if STATE.snapshot and isinstance(STATE.snapshot.get("items"), list):
                        for it in STATE.snapshot["items"]:
                            if it.get("auction_id") == aid:
                                it["starred"] = res["starred"]
                                it["ignored"] = res["ignored"]
                                it["note"] = res["note"]
                self._send_json({"ok": True, "mark": res})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if path == "/api/inspect":
            try:
                body = self._read_json_body()
                aid = str(body.get("auction_id") or "").strip()
                category = str(body.get("category") or "general").strip()
                profile_id = str(body.get("profile_id") or "").strip()
                if not aid:
                    self._send_json({"ok": False, "error": "Missing auction_id"}, status=400)
                    return
                report = fetch_and_inspect_item(aid, category=category)
                if not report.get("inspected"):
                    self._send_json({"ok": False, "error": report.get("error") or "Inspect failed"}, status=502)
                    return
                save_cached_inspection(aid, report)
                cfg = load_config(apply_env=True)
                prof_map = {p["id"]: p for p in (cfg.get("profiles") or [])}
                updated_item = None
                with STATE.lock:
                    if STATE.snapshot and isinstance(STATE.snapshot.get("items"), list):
                        for it in STATE.snapshot["items"]:
                            if it.get("auction_id") == aid and (not profile_id or it.get("profile_id") == profile_id):
                                prof = prof_map.get(it.get("profile_id"), {"category": category})
                                apply_inspection(it, report, prof, cfg)
                                updated_item = it
                        STATE.snapshot["items"].sort(
                            key=lambda x: (-x["steal_score"], x["effective_512_cny"], x["remaining_sec"])
                        )
                        save_latest_snapshot(STATE.snapshot)
                self._send_json({"ok": True, "report": report, "item": updated_item})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        if path == "/api/test-notify":
            try:
                body = self._read_json_body()
                cfg = load_config(apply_env=True)
                if isinstance(body.get("notifications"), dict):
                    cfg["notifications"].update(body["notifications"])
                title = "🔔 万能日淘捡漏雷达测试推送"
                md = (
                    "#### 测试成功！你的推送通道已连通\n"
                    "- 当雅虎日拍出现 **你监控商品的低于预算好价（且通过正文排雷）** 时，你会第一时间收到提醒。\n"
                    "- 示例：[打开任意门官网](https://www.doorzo.com/)"
                )
                plain = "测试成功！当雅虎日拍出现你监控商品的达标低价好物时，你会第一时间收到提醒。"
                results = send_notification(cfg, title, md, plain, link_url="https://www.doorzo.com/")
                self._send_json({"ok": True, "results": results})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Category Yahoo Auctions Doorzo Radar Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8783, help="Bind port (default: 8783)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    stop_event = threading.Event()
    poller = threading.Thread(target=_background_poller, args=(stop_event,), daemon=True)
    poller.start()

    httpd = ThreadingHTTPServer((args.host, args.port), RadarHandler)
    url = f"http://{args.host}:{args.port}"
    print("============================================================")
    print("  万能日淘任意门多品类捡漏雷达已启动!")
    print(f"  看板地址: {url}")
    print("  按 Ctrl+C 停止服务")
    print("============================================================", flush=True)

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务...")
    finally:
        stop_event.set()
        httpd.server_close()


if __name__ == "__main__":
    main()
