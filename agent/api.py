"""
Flask HTTP API — localhost:27420
"""
import csv
import io
import json
import logging
import os
import threading
import time
import datetime
from typing import Optional

from flask import Flask, jsonify, request, Response, send_from_directory

try:
    import winreg as _winreg
    _WINREG_OK = True
except ImportError:
    _WINREG_OK = False

from . import database, config as cfg_module
from .tracker import Tracker, update_browser_state

logger = logging.getLogger(__name__)

UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")

app = Flask(__name__, static_folder=UI_DIR, static_url_path="")
app.config["JSON_SORT_KEYS"] = False

_tracker: Optional[Tracker] = None
_cfg: dict = {}


def set_tracker(tracker: Tracker) -> None:
    global _tracker
    _tracker = tracker


def set_config(cfg: dict) -> None:
    global _cfg
    _cfg = cfg


# ─── CORS for Web UI ───────────────────────────────────────────────────────

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options_handler(path):
    return Response(status=204)


# ─── Web UI ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(UI_DIR, "index.html")


# ─── Logs ──────────────────────────────────────────────────────────────────

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "agent.log")


@app.route("/logs")
def get_logs():
    n = int(request.args.get("n", 100))
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return jsonify({"lines": [l.rstrip() for l in lines[-n:]]})
    except FileNotFoundError:
        return jsonify({"lines": []})


# ─── Status ────────────────────────────────────────────────────────────────

@app.route("/status")
def status():
    return jsonify({
        "running": True,
        "paused": _tracker.is_paused if _tracker else False,
        "events_today": database.count_today(),
    })


# ─── Pause / Resume ────────────────────────────────────────────────────────

@app.route("/pause", methods=["POST"])
def pause():
    if _tracker:
        _tracker.pause()
    return jsonify({"ok": True})


@app.route("/resume", methods=["POST"])
def resume():
    if _tracker:
        _tracker.resume()
    return jsonify({"ok": True})


# ─── Chrome Extension event ────────────────────────────────────────────────

@app.route("/event", methods=["POST"])
def receive_event():
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    title = data.get("title")
    if not url:
        return jsonify({"error": "url required"}), 400

    # Update shared state for tracker
    update_browser_state(url, title)

    # Also record directly as extension event
    database.insert_event(
        app_name="chrome.exe",
        window_title=title,
        url=url,
        page_title=title,
        is_idle=False,
        source="extension",
    )
    return jsonify({"ok": True})


# ─── Stats ─────────────────────────────────────────────────────────────────

@app.route("/stats")
def stats():
    date_str = request.args.get("date", datetime.date.today().isoformat())
    try:
        data = database.get_stats(date_str)
        # events list can be large; keep it but convert timestamps to ISO
        for ev in data.get("events", []):
            ev["time_iso"] = datetime.datetime.fromtimestamp(
                ev["timestamp"]
            ).isoformat()
        return jsonify(data)
    except Exception as e:
        logger.error("stats error: %s", e)
        return jsonify({"error": str(e)}), 500


# ─── Categories ────────────────────────────────────────────────────────────

@app.route("/categories", methods=["GET"])
def get_categories():
    return jsonify(database.get_categories())


@app.route("/categories", methods=["POST"])
def save_categories():
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify({"error": "expected list"}), 400
    try:
        database.save_categories(data)
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("save_categories error: %s", e)
        return jsonify({"error": str(e)}), 500


# ─── Config ────────────────────────────────────────────────────────────────

@app.route("/config", methods=["GET"])
def get_config():
    return jsonify(_cfg)


_ALLOWED_CONFIG_KEYS = {"poll_interval", "idle_threshold", "api_port", "export_dir"}


@app.route("/config", methods=["POST"])
def save_config():
    data = request.get_json(silent=True) or {}
    filtered = {k: v for k, v in data.items() if k in _ALLOWED_CONFIG_KEYS}
    _cfg.update(filtered)
    cfg_module.save(_cfg)
    if _tracker and "poll_interval" in filtered:
        _tracker.poll_interval = int(filtered["poll_interval"])
    if _tracker and "idle_threshold" in filtered:
        _tracker.idle_threshold = int(filtered["idle_threshold"])
    return jsonify({"ok": True})


# ─── Export ────────────────────────────────────────────────────────────────

@app.route("/export")
def export():
    fmt = request.args.get("format", "json")
    from_str = request.args.get("from", datetime.date.today().isoformat())
    to_str = request.args.get("to", datetime.date.today().isoformat())

    try:
        from_dt = datetime.datetime.fromisoformat(from_str)
        to_dt = datetime.datetime.fromisoformat(to_str) + datetime.timedelta(days=1)
        events = database.get_events_range(int(from_dt.timestamp()), int(to_dt.timestamp()))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            "timestamp", "app_name", "window_title",
            "url", "page_title", "category_name", "is_idle", "source"
        ])
        writer.writeheader()
        for ev in events:
            writer.writerow({k: ev.get(k, "") for k in writer.fieldnames})
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=activity_{from_str}_{to_str}.csv"},
        )
    else:
        # JSON optimised for Claude
        summary = _build_claude_summary(events, from_str, to_str)
        return jsonify(summary)


def _build_claude_summary(events: list, from_str: str, to_str: str) -> dict:
    from collections import defaultdict
    by_cat: dict = defaultdict(int)
    by_app: dict = defaultdict(int)

    for i, ev in enumerate(events):
        if ev["is_idle"]:
            continue
        gap = min(
            (events[i + 1]["timestamp"] - ev["timestamp"]) if i + 1 < len(events) else 10,
            60,
        )
        cat = ev.get("category_name") or "Прочее"
        by_cat[cat] += gap
        by_app[ev["app_name"]] += gap

    total = sum(by_cat.values())
    return {
        "period": {"from": from_str, "to": to_str},
        "total_active_seconds": total,
        "by_category": [
            {"name": k, "seconds": v, "percent": round(v / total * 100, 1) if total else 0}
            for k, v in sorted(by_cat.items(), key=lambda x: -x[1])
        ],
        "top_apps": [
            {"app": k, "seconds": v}
            for k, v in sorted(by_app.items(), key=lambda x: -x[1])[:15]
        ],
        "total_events": len(events),
    }


@app.route("/export/day", methods=["POST"])
def export_day():
    data = request.get_json(silent=True) or {}
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    date_str = data.get("date", yesterday)
    export_dir = _cfg.get("export_dir", "")
    if not export_dir:
        return jsonify({"error": "export_dir not configured"}), 400
    try:
        path = database.generate_daily_export(date_str, export_dir)
        if path is None:
            return jsonify({"ok": True, "skipped": True, "date": date_str,
                            "reason": "Нет данных за этот день"})
        logger.info("Daily export written: %s", path)
        return jsonify({"ok": True, "skipped": False, "path": path, "date": date_str})
    except Exception as e:
        logger.error("export_day error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/export/day-csv", methods=["POST"])
def export_day_csv():
    data = request.get_json(silent=True) or {}
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    date_str = data.get("date", yesterday)
    export_dir = _cfg.get("export_dir", "")
    if not export_dir:
        return jsonify({"error": "export_dir not configured"}), 400
    csv_dir = os.path.join(export_dir, "CSV")
    try:
        path = database.generate_daily_csv(date_str, csv_dir)
        if path is None:
            return jsonify({"ok": True, "skipped": True, "date": date_str,
                            "reason": "Нет данных за этот день"})
        logger.info("Day CSV export written: %s", path)
        return jsonify({"ok": True, "skipped": False, "path": path, "date": date_str})
    except Exception as e:
        logger.error("export_day_csv error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/export/range", methods=["POST"])
def export_range():
    data = request.get_json(silent=True) or {}
    from_str = data.get("from")
    to_str = data.get("to")
    export_dir = _cfg.get("export_dir", "")
    if not from_str or not to_str:
        return jsonify({"error": "from and to required"}), 400
    if not export_dir:
        return jsonify({"error": "export_dir not configured"}), 400
    try:
        from_dt = datetime.date.fromisoformat(from_str)
        to_dt = datetime.date.fromisoformat(to_str)
        written = 0
        skipped = 0
        cur = from_dt
        while cur <= to_dt:
            path = database.generate_daily_export(cur.isoformat(), export_dir)
            if path:
                written += 1
            else:
                skipped += 1
            cur += datetime.timedelta(days=1)
        return jsonify({"ok": True, "written": written, "skipped": skipped})
    except Exception as e:
        logger.error("export_range error: %s", e)
        return jsonify({"error": str(e)}), 500


# ─── Autostart ─────────────────────────────────────────────────────────────

_AUTOSTART_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "PCActivityTracker"


def _vbs_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "start_tray.vbs")


def _autostart_cmd() -> str:
    return f'wscript.exe "{_vbs_path()}"'


def _get_autostart() -> bool:
    if not _WINREG_OK:
        return False
    try:
        key = _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, _winreg.KEY_READ)
        _winreg.QueryValueEx(key, _AUTOSTART_NAME)
        _winreg.CloseKey(key)
        return True
    except OSError:
        return False


def _set_autostart(enable: bool) -> None:
    if not _WINREG_OK:
        raise RuntimeError("winreg not available (not Windows?)")
    key = _winreg.OpenKey(
        _winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, _winreg.KEY_SET_VALUE
    )
    if enable:
        _winreg.SetValueEx(key, _AUTOSTART_NAME, 0, _winreg.REG_SZ, _autostart_cmd())
    else:
        try:
            _winreg.DeleteValue(key, _AUTOSTART_NAME)
        except OSError:
            pass
    _winreg.CloseKey(key)


@app.route("/autostart", methods=["GET"])
def get_autostart():
    return jsonify({"enabled": _get_autostart()})


@app.route("/autostart", methods=["POST"])
def set_autostart():
    data = request.get_json(silent=True) or {}
    enable = bool(data.get("enabled", False))
    try:
        _set_autostart(enable)
        logger.info("Autostart %s", "enabled" if enable else "disabled")
        return jsonify({"ok": True, "enabled": enable})
    except Exception as e:
        logger.error("autostart error: %s", e)
        return jsonify({"error": str(e)}), 500


def run(host: str = "127.0.0.1", port: int = 27420) -> None:
    app.run(host=host, port=port, use_reloader=False, threaded=True)
