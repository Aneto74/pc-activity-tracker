"""
Active window polling + idle detection for Windows.
"""
import ctypes
import threading
import time
import logging
import webbrowser
from typing import Optional

import win32gui
import win32process
import win32api
import win32con
import psutil

from . import database

logger = logging.getLogger(__name__)

BROWSER_APPS = {"chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe"}


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

_EXT_CHECK_INTERVAL = 600       # check every 10 minutes
_EXT_MISSING_THRESHOLD = 600    # alert if no extension events for 10 min
_CHROME_ACTIVE_THRESHOLD = 120  # Chrome must be active for 2+ min to trigger


class Tracker:
    def __init__(self, poll_interval: int = 10, idle_threshold: int = 300, api_port: int = 27420):
        self.poll_interval = poll_interval
        self.idle_threshold = idle_threshold
        self.api_port = api_port
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._ext_alert_shown = False       # only show once per session
        self._chrome_active_since: float = 0.0  # when Chrome became active
        self._last_ext_check: float = 0.0

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
        if app_name.lower() not in BROWSER_APPS:
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

        # Extension health-check
        self._check_extension_health(app_name)

    def _check_extension_health(self, app_name: str) -> None:
        """Open help page if Chrome is active but extension is not sending events."""
        if self._ext_alert_shown:
            return

        now = time.time()
        is_chrome = app_name.lower() in BROWSER_APPS

        # Track how long Chrome has been the active window
        if is_chrome:
            if self._chrome_active_since == 0:
                self._chrome_active_since = now
        else:
            self._chrome_active_since = 0
            return

        # Only check periodically
        if now - self._last_ext_check < _EXT_CHECK_INTERVAL:
            return
        self._last_ext_check = now

        # Chrome must be active for a while (avoid false positives on quick tab switches)
        if now - self._chrome_active_since < _CHROME_ACTIVE_THRESHOLD:
            return

        # Check if extension has sent events recently
        from . import api
        last_ext = api.get_last_extension_event()
        if last_ext > 0 and (now - last_ext) < _EXT_MISSING_THRESHOLD:
            return  # extension is working

        # No extension events — open help page
        self._ext_alert_shown = True
        help_url = f"http://127.0.0.1:{self.api_port}/extension-help.html"
        logger.warning("Chrome extension not detected — opening help page: %s", help_url)
        try:
            webbrowser.open(help_url)
        except Exception as e:
            logger.error("Failed to open extension help page: %s", e)
