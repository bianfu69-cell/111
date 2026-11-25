"""Local Web Dashboard & Background Auto-Polling Server (pure Python stdlib)."""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from radar.config import ROOT_DIR, load_config, save_config
from radar.engine import run_scan
from radar.inspector import fetch_and_inspect_item
from radar.notifier import send_notification
from radar.parser import apply_inspection
from radar.storage import load_latest_snapshot, save_cached_inspection, save_latest_snapshot, set_item_mark

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


def _background_poller(stop_event: threading.Event) -> None:
    # Run an initial scan right after server startup if snapshot is missing or older than 5 min
    snap = STATE.snapshot
    need_now = (not snap) or (time.time() - int(snap.get("scanned_ts", 0)) > 300)
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
        # Keep terminal clean; only log errors or API mutations
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
        self.send_header("Content-Type", f"{mime or 'application/octet-stream'}; charset=utf-8" if (mime or "").startswith(("text/", "application/javascript")) else (mime or "application/octet-stream"))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

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
            cfg = load_config(apply_env=True)
            self._send_json(cfg)
            return

        if path == "/api/health":
            self._send_json({"ok": True, "scanning": STATE.scanning})
            return

        self._serve_static(path)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/scan":
            body = self._read_json_body()
            send_alerts = bool(body.get("send_alerts", True))
            res = STATE.trigger_scan(send_alerts=send_alerts, export_static=True)
            self._send_json(res, status=200 if res.get("status") != "error" else 500)
            return

        if path == "/api/config":
            try:
                body = self._read_json_body()
                saved = save_config(body)
                # Trigger background rescan with new pricing/rules if not currently scanning
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
                # Patch in-memory snapshot immediately so reload reflects it
                with STATE.lock:
                    if STATE.snapshot and isinstance(STATE.snapshot.get("items"), list):
                        for it in STATE.snapshot["items"]:
                            if it.get("auction_id") == aid:
                                it["starred"] = res["starred"]
                                it["ignored"] = res["ignored"]
                                it["note"] = res["note"]
                                break
                self._send_json({"ok": True, "mark": res})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if path == "/api/inspect":
            try:
                body = self._read_json_body()
                aid = str(body.get("auction_id") or "").strip()
                if not aid:
                    self._send_json({"ok": False, "error": "Missing auction_id"}, status=400)
                    return
                report = fetch_and_inspect_item(aid)
                if not report.get("inspected"):
                    self._send_json({"ok": False, "error": report.get("error") or "Inspect failed"}, status=502)
                    return
                save_cached_inspection(aid, report)
                cfg = load_config(apply_env=True)
                updated_item = None
                with STATE.lock:
                    if STATE.snapshot and isinstance(STATE.snapshot.get("items"), list):
                        for it in STATE.snapshot["items"]:
                            if it.get("auction_id") == aid:
                                apply_inspection(it, report, cfg)
                                updated_item = it
                                break
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
                title = "🔔 Dynabook G83 捡漏雷达测试推送"
                md = (
                    "#### 测试成功！你的推送通道已连通\n"
                    "- 当雅虎日拍出现 **低于预算的 13代/12代/11代 G83 快结拍或一口价好机** 时，你会第一时间收到类似通知。\n"
                    "- 示例：[打开任意门官网](https://www.doorzo.com/)"
                )
                plain = "测试成功！当雅虎日拍出现达标低价 G83 时，你会第一时间收到提醒。"
                results = send_notification(cfg, title, md, plain, link_url="https://www.doorzo.com/")
                self._send_json({"ok": True, "results": results})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dynabook G83 Yahoo Auctions Radar Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8783, help="Bind port (default: 8783)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    stop_event = threading.Event()
    poller = threading.Thread(target=_background_poller, args=(stop_event,), daemon=True)
    poller.start()

    httpd = ThreadingHTTPServer((args.host, args.port), RadarHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"============================================================")
    print(f"  Dynabook G83 雅虎日拍捡漏雷达已启动!")
    print(f"  看板地址: {url}")
    print(f"  按 Ctrl+C 停止服务")
    print(f"============================================================", flush=True)

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
