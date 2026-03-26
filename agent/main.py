"""
Entry point for PC Activity Tracker Desktop Agent.
Run: python -m agent.main
"""
import datetime
import logging
import threading
import time
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config as cfg_module, database, api
from agent.tracker import Tracker
from agent.tray import TrayApp

LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "agent.log",
)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

from logging.handlers import RotatingFileHandler

_file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), _file_handler],
)
logger = logging.getLogger(__name__)


def _auto_export_loop(cfg: dict) -> None:
    """Background thread: export yesterday on startup (if missing), then at 00:02 and 12:02."""
    export_dir = cfg.get("export_dir", "").strip()
    if not export_dir:
        return

    def try_yesterday() -> None:
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        date_compact = yesterday.replace("-", "")

        # Markdown
        md_path = os.path.join(export_dir, f"{date_compact}-activity.md")
        if not os.path.exists(md_path):
            try:
                result = database.generate_daily_export(yesterday, export_dir)
                if result:
                    logger.info("Auto-export MD created: %s", result)
                else:
                    logger.info("Auto-export MD skipped for %s — no data", yesterday)
            except Exception as exc:
                logger.error("Auto-export MD failed for %s: %s", yesterday, exc)

        # CSV
        csv_dir = os.path.join(export_dir, "CSV")
        csv_path = os.path.join(csv_dir, f"activity_{yesterday}_{yesterday}.csv")
        if not os.path.exists(csv_path):
            try:
                result = database.generate_daily_csv(yesterday, csv_dir)
                if result:
                    logger.info("Auto-export CSV created: %s", result)
                else:
                    logger.info("Auto-export CSV skipped for %s — no data", yesterday)
            except Exception as exc:
                logger.error("Auto-export CSV failed for %s: %s", yesterday, exc)

    # Check immediately at startup
    try_yesterday()

    # Then wake up at 00:02 and 12:02 local time each day
    while True:
        now = datetime.datetime.now()
        candidates = [
            now.replace(hour=0,  minute=2, second=0, microsecond=0),
            now.replace(hour=12, minute=2, second=0, microsecond=0),
            now.replace(hour=0,  minute=2, second=0, microsecond=0) + datetime.timedelta(days=1),
        ]
        next_run = min(t for t in candidates if t > now)
        time.sleep((next_run - now).total_seconds())
        try_yesterday()


def main():
    parser = argparse.ArgumentParser(description="PC Activity Tracker")
    parser.add_argument("--no-tray", action="store_true", help="Run without system tray")
    args = parser.parse_args()

    cfg = cfg_module.load()
    db_path = cfg["db_path"]
    port = cfg["api_port"]

    logger.info("Initialising database: %s", db_path)
    database.init(db_path)

    tracker = Tracker(
        poll_interval=cfg["poll_interval"],
        idle_threshold=cfg["idle_threshold"],
        api_port=port,
    )

    api.set_tracker(tracker)
    api.set_config(cfg)

    tracker.start()
    logger.info("Tracker started (interval=%ds)", cfg["poll_interval"])

    # Run Flask API in background thread
    api_thread = threading.Thread(
        target=lambda: api.run(host="127.0.0.1", port=port),
        daemon=True,
        name="api-server",
    )
    api_thread.start()
    logger.info("API server started on http://127.0.0.1:%d", port)

    # Auto-export background thread
    export_thread = threading.Thread(
        target=_auto_export_loop,
        args=(cfg,),
        daemon=True,
        name="auto-export",
    )
    export_thread.start()

    if args.no_tray:
        logger.info("Running without tray (Ctrl+C to stop)")
        try:
            api_thread.join()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            tracker.stop()
    else:
        # Tray blocks main thread (required by pystray on Windows)
        tray = TrayApp(tracker, port=port)
        try:
            tray.run()
        except KeyboardInterrupt:
            pass
        finally:
            tracker.stop()
            logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
