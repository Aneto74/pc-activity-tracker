"""
System tray icon using pystray + Pillow.
"""
import logging
import threading
import webbrowser
from typing import Optional

import pystray
from PIL import Image, ImageDraw

from . import database
from .tracker import Tracker

logger = logging.getLogger(__name__)


def _make_icon(color: str = "#4A90E2") -> Image.Image:
    """Create a simple circle icon."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=color)
    return img


class TrayApp:
    def __init__(self, tracker: Tracker, port: int = 27420):
        self._tracker = tracker
        self._port = port
        self._icon: Optional[pystray.Icon] = None

    def _dashboard_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def _open_dashboard(self, icon, item):
        webbrowser.open(self._dashboard_url())

    def _toggle_pause(self, icon, item):
        if self._tracker.is_paused:
            self._tracker.resume()
        else:
            self._tracker.pause()
        self._update_menu()

    def _quit(self, icon, item):
        self._tracker.stop()
        icon.stop()

    def _update_menu(self):
        if not self._icon:
            return
        color = "#F5A623" if self._tracker.is_paused else "#4A90E2"
        self._icon.icon = _make_icon(color)
        self._icon.update_menu()

    def _build_menu(self) -> pystray.Menu:
        def pause_label(item):
            return "Возобновить" if self._tracker.is_paused else "Пауза"

        def status_label(item):
            n = database.count_today()
            state = "⏸ Пауза" if self._tracker.is_paused else "▶ Работает"
            return f"{state} | Сегодня: {n} событий"

        return pystray.Menu(
            pystray.MenuItem(status_label, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(pause_label, self._toggle_pause),
            pystray.MenuItem("Открыть Dashboard", self._open_dashboard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", self._quit),
        )

    def run(self) -> None:
        self._icon = pystray.Icon(
            name="pc-activity-tracker",
            icon=_make_icon(),
            title="PC Activity Tracker",
            menu=self._build_menu(),
        )
        logger.info("Tray icon starting")
        self._icon.run()  # blocks until quit
