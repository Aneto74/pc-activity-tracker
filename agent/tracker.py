"""
Active window polling + idle detection for Windows.
"""
import ctypes
import threading
import time
import logging
from typing import Optional

import win32gui
import win32process
import win32api
import win32con
import psutil

from . import database

logger = logging.getLogger(__name__)


# ─── Idle detection ────────────────────────────────────────────────────────

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def get_idle_seconds() -> float:
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
    millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
    return millis / 1000.0


# ─── Active window ─────────────────────────────────────────────────────────

def get_active_window() -> tuple[Optional[str], Optional[str]]:
    """Return (app_name, window_title) or (None, None) on failure."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None, None
        window_title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        app_name = proc.name()
        return app_name, window_title
    except Exception as e:
        logger.debug("get_active_window error: %s", e)
        return None, None


# ─── URL state shared with Chrome Extension ───────────────────────────────

_browser_state: dict = {"url": None, "page_title": None}
_browser_lock = threading.Lock()


def update_browser_state(url: str, page_title: str) -> None:
    with _browser_lock:
        _browser_state["url"] = url
        _browser_state["page_title"] = page_title


def _get_browser_state() -> tuple[Optional[str], Optional[str]]:
    with _browser_lock:
        return _browser_state["url"], _browser_state["page_title"]


# ─── Tracker loop ──────────────────────────────────────────────────────────

class Tracker:
    def __init__(self, poll_interval: int = 10, idle_threshold: int = 300):
        self.poll_interval = poll_interval
        self.idle_threshold = idle_threshold
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="tracker")
        self._thread.start()
        logger.info("Tracker started (interval=%ds, idle_threshold=%ds)",
                    self.poll_interval, self.idle_threshold)

    def stop(self) -> None:
        self._running = False

    def pause(self) -> None:
        self._paused = True
        logger.info("Tracker paused")

    def resume(self) -> None:
        self._paused = False
        logger.info("Tracker resumed")

    @property
    def is_paused(self) -> bool:
        return self._paused

    def _loop(self) -> None:
        while self._running:
            try:
                if not self._paused:
                    self._tick()
            except Exception as e:
                logger.error("Tracker tick error: %s", e)
            time.sleep(self.poll_interval)

    def _tick(self) -> None:
        idle_secs = get_idle_seconds()
        is_idle = idle_secs >= self.idle_threshold

        app_name, window_title = get_active_window()
        if not app_name:
            return

        url, page_title = _get_browser_state()

        # Only attach URL if active app is a browser
        browser_names = {"chrome.exe", "firefox.exe", "msedge.exe", "opera.exe"}
        if app_name.lower() not in browser_names:
            url = None
            page_title = None

        database.insert_event(
            app_name=app_name,
            window_title=window_title,
            url=url,
            page_title=page_title,
            is_idle=is_idle,
            source="agent",
        )
        logger.debug("Event: app=%s idle=%s", app_name, is_idle)
