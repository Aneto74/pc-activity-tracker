import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

_db_path: str = ""


def init(db_path: str) -> None:
    global _db_path
    _db_path = db_path
    with _conn() as conn:
        _create_schema(conn)
        _seed_categories(conn)


@contextmanager
def _conn():
    conn = sqlite3.connect(_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id         INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            color      TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS rules (
            id          INTEGER PRIMARY KEY,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            rule_type   TEXT NOT NULL,
            value       TEXT NOT NULL,
            sort_order  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY,
            timestamp    INTEGER NOT NULL,
            app_name     TEXT NOT NULL,
            window_title TEXT,
            url          TEXT,
            page_title   TEXT,
            category_id  INTEGER REFERENCES categories(id),
            is_idle      INTEGER DEFAULT 0,
            source       TEXT DEFAULT 'agent'
        );

        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_app ON events(app_name);
    """)


def _seed_categories(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) FROM categories").fetchone()
    if row[0] > 0:
        return

    presets = [
        ("Работа",         "#4A90E2", 0, 1),
        ("Браузер (рабочий)", "#5BA85A", 0, 2),
        ("Коммуникации",   "#F5A623", 0, 3),
        ("Учёба",          "#9B59B6", 0, 4),
        ("Отдых",          "#E74C3C", 0, 5),
        ("Прочее",         "#95A5A6", 1, 6),
    ]
    conn.executemany(
        "INSERT INTO categories (name, color, is_default, sort_order) VALUES (?,?,?,?)",
        presets,
    )

    # Get IDs by name
    cats = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}

    rules = [
        # Работа
        (cats["Работа"], "app_contains", "slack", 1),
        (cats["Работа"], "app_contains", "zoom", 2),
        (cats["Работа"], "app_contains", "notion", 3),
        (cats["Работа"], "app_contains", "code", 4),
        (cats["Работа"], "app_contains", "figma", 5),
        (cats["Работа"], "app_contains", "word", 6),
        (cats["Работа"], "app_contains", "excel", 7),
        # Браузер рабочий
        (cats["Браузер (рабочий)"], "url_domain", "github.com", 1),
        (cats["Браузер (рабочий)"], "url_domain", "docs.google.com", 2),
        (cats["Браузер (рабочий)"], "url_domain", "linear.app", 3),
        # Коммуникации
        (cats["Коммуникации"], "app_contains", "telegram", 1),
        (cats["Коммуникации"], "app_contains", "whatsapp", 2),
        (cats["Коммуникации"], "app_contains", "outlook", 3),
        (cats["Коммуникации"], "app_contains", "thunderbird", 4),
        # Учёба
        (cats["Учёба"], "url_domain", "lingq.com", 1),
        (cats["Учёба"], "app_contains", "anki", 2),
        # Отдых
        (cats["Отдых"], "url_domain", "youtube.com", 1),
        (cats["Отдых"], "url_domain", "netflix.com", 2),
        (cats["Отдых"], "url_domain", "vk.com", 3),
    ]
    conn.executemany(
        "INSERT INTO rules (category_id, rule_type, value, sort_order) VALUES (?,?,?,?)",
        rules,
    )


# ─── Events ────────────────────────────────────────────────────────────────

def insert_event(
    app_name: str,
    window_title: Optional[str],
    url: Optional[str],
    page_title: Optional[str],
    is_idle: bool,
    source: str = "agent",
) -> None:
    category_id = _classify(app_name, url)
    with _conn() as conn:
        conn.execute(
            """INSERT INTO events
               (timestamp, app_name, window_title, url, page_title, category_id, is_idle, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (int(time.time()), app_name, window_title, url, page_title,
             category_id, int(is_idle), source),
        )


def _classify(app_name: str, url: Optional[str]) -> Optional[int]:
    with _conn() as conn:
        rules = conn.execute(
            """SELECT r.rule_type, r.value, r.category_id
               FROM rules r
               JOIN categories c ON c.id = r.category_id
               ORDER BY c.sort_order, r.sort_order"""
        ).fetchall()
        default_cat = conn.execute(
            "SELECT id FROM categories WHERE is_default=1 LIMIT 1"
        ).fetchone()

    default_cat_id = default_cat["id"] if default_cat else None
    return _classify_with(app_name, url, [dict(r) for r in rules], default_cat_id)


def _classify_with(
    app_name: str,
    url: Optional[str],
    rules: list,
    default_cat_id: Optional[int],
) -> Optional[int]:
    """Classify using pre-loaded rules list (no DB access)."""
    app_lower = (app_name or "").lower()
    url_lower = (url or "").lower()

    for rule in rules:
        rt, val, cat_id = rule["rule_type"], rule["value"].lower(), rule["category_id"]
        if rt == "app_contains" and val in app_lower:
            return cat_id
        if rt == "app_exact" and app_lower == val:
            return cat_id
        if rt == "url_contains" and url_lower and val in url_lower:
            return cat_id
        if rt == "url_domain" and url_lower:
            # strip scheme
            domain_part = url_lower.split("//")[-1].split("/")[0]
            if val in domain_part:
                return cat_id

    return default_cat_id


# ─── Stats ─────────────────────────────────────────────────────────────────

def get_stats(date_str: str) -> dict:
    import datetime
    day = datetime.date.fromisoformat(date_str)
    ts_start = int(datetime.datetime(day.year, day.month, day.day).timestamp())
    ts_end = ts_start + 86400

    with _conn() as conn:
        rows = conn.execute(
            """SELECT e.app_name, e.window_title, e.url, e.page_title,
                      e.is_idle, e.timestamp, e.source
               FROM events e
               WHERE e.timestamp >= ? AND e.timestamp < ?
               ORDER BY e.timestamp""",
            (ts_start, ts_end),
        ).fetchall()

        # Load current rules and categories for live re-classification
        rules_rows = conn.execute(
            """SELECT r.rule_type, r.value, r.category_id
               FROM rules r
               JOIN categories c ON c.id = r.category_id
               ORDER BY c.sort_order, r.sort_order"""
        ).fetchall()
        cats_map = {
            r["id"]: {"name": r["name"], "color": r["color"]}
            for r in conn.execute("SELECT id, name, color FROM categories")
        }
        default_row = conn.execute(
            "SELECT id FROM categories WHERE is_default=1 LIMIT 1"
        ).fetchone()
        default_cat_id = default_row["id"] if default_row else None

    rules_list = [dict(r) for r in rules_rows]

    # Re-classify each event using current rules (ignores stale stored category_id)
    events = []
    for r in rows:
        ev = dict(r)
        cat_id = _classify_with(ev["app_name"], ev.get("url"), rules_list, default_cat_id)
        cat_info = cats_map.get(cat_id) if cat_id is not None else None
        ev["category_name"] = cat_info["name"] if cat_info else "Прочее"
        ev["category_color"] = cat_info["color"] if cat_info else "#95A5A6"
        events.append(ev)

    return _aggregate_stats(events)


_BROWSER_APPS = {"chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe"}


def _extract_domain(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        # strip scheme and path: "https://github.com/foo" → "github.com"
        domain = url.split("//")[-1].split("/")[0].split("?")[0]
        # strip "www."
        if domain.startswith("www."):
            domain = domain[4:]
        return domain or None
    except Exception:
        return None


def _aggregate_stats(events: list) -> dict:
    from collections import defaultdict
    poll = 10

    by_app: dict = defaultdict(int)
    app_category: dict = {}
    by_category: dict = defaultdict(lambda: {"name": "", "color": "", "seconds": 0})
    idle_seconds = 0
    active_seconds = 0

    # Build set of timestamps with extension events to skip duplicate agent events
    ext_timestamps = {
        ev["timestamp"] for ev in events if ev.get("source") == "extension"
    }

    for i, ev in enumerate(events):
        if i + 1 < len(events):
            gap = min(events[i + 1]["timestamp"] - ev["timestamp"], 60)
        else:
            gap = poll

        if ev["is_idle"]:
            idle_seconds += gap
            continue

        # Skip agent-polled browser events when extension event exists within ±15s
        # to avoid double-counting the same browsing session
        if (ev.get("source") == "agent"
                and ev["app_name"].lower() in _BROWSER_APPS):
            ts = ev["timestamp"]
            if any(abs(ts - ext_ts) <= 15 for ext_ts in ext_timestamps):
                continue

        active_seconds += gap

        # Use domain as display key for browser events with URL
        url = ev.get("url")
        domain = _extract_domain(url) if ev["app_name"].lower() in _BROWSER_APPS else None
        display_key = domain if domain else ev["app_name"]

        by_app[display_key] += gap
        cat = ev.get("category_name") or "Прочее"
        color = ev.get("category_color") or "#95A5A6"
        app_category[display_key] = {"name": cat, "color": color}
        by_category[cat]["name"] = cat
        by_category[cat]["color"] = color
        by_category[cat]["seconds"] += gap

    return {
        "events": events,
        "by_app": dict(by_app),
        "app_category": app_category,
        "by_category": dict(by_category),
        "active_seconds": active_seconds,
        "idle_seconds": idle_seconds,
        "total_events": len(events),
    }


def count_today() -> int:
    import datetime, time as _time
    today = datetime.date.today()
    ts_start = int(datetime.datetime(today.year, today.month, today.day).timestamp())
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE timestamp >= ?", (ts_start,)
        ).fetchone()
    return row[0]


# ─── Categories CRUD ───────────────────────────────────────────────────────

def get_categories() -> list:
    with _conn() as conn:
        cats = conn.execute(
            "SELECT * FROM categories ORDER BY sort_order"
        ).fetchall()
        result = []
        for c in cats:
            rules = conn.execute(
                "SELECT * FROM rules WHERE category_id=? ORDER BY sort_order",
                (c["id"],),
            ).fetchall()
            result.append({**dict(c), "rules": [dict(r) for r in rules]})
    return result


def save_categories(categories: list) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM rules")
        conn.execute("DELETE FROM categories")
        for cat in categories:
            conn.execute(
                "INSERT INTO categories (id, name, color, is_default, sort_order) VALUES (?,?,?,?,?)",
                (cat["id"], cat["name"], cat["color"],
                 cat.get("is_default", 0), cat.get("sort_order", 0)),
            )
            for rule in cat.get("rules", []):
                conn.execute(
                    "INSERT INTO rules (id, category_id, rule_type, value, sort_order) VALUES (?,?,?,?,?)",
                    (rule["id"], cat["id"], rule["rule_type"],
                     rule["value"], rule.get("sort_order", 0)),
                )


# ─── Daily Markdown Export ─────────────────────────────────────────────────

_INTERNAL_KEYS = {"127.0.0.1", "localhost"}


def _is_internal(key: str) -> bool:
    return any(key.startswith(h) for h in _INTERNAL_KEYS)


def _is_domain(key: str) -> bool:
    """True if key looks like a web domain (not an .exe / internal address)."""
    if _is_internal(key):
        return False
    return "." in key and not key.lower().endswith(".exe")


def generate_daily_export(date_str: str, export_dir: str):
    """Build a Markdown daily report and write it to export_dir/YYYY-MM-DD.md.
    Returns the absolute path of the written file, or None if no data for the day."""
    import os

    stats = get_stats(date_str)
    n_ev = stats["total_events"]

    # Don't create a file for days with no recorded activity
    if n_ev == 0:
        return None

    active  = stats["active_seconds"]
    idle    = stats["idle_seconds"]
    total_t = active + idle

    def fmt(sec: float) -> str:
        sec = int(sec)
        if sec < 60:   return f"{sec}с"
        if sec < 3600: return f"{sec // 60}м"
        return f"{sec // 3600}ч {(sec % 3600) // 60}м"

    lines = [
        f"# Активность — {date_str}",
        "",
        f"**Активно:** {fmt(active)}  ·  **Неактивен:** {fmt(idle)}  ·  **Событий:** {n_ev}",
        "",
        "---",
        "",
        "## По категориям",
        "",
        "| Категория | Время | % от активного |",
        "|-----------|-------|----------------|",
    ]

    by_cat = sorted(stats["by_category"].items(), key=lambda x: -x[1]["seconds"])
    for cat_name, info in by_cat:
        pct = round(info["seconds"] / active * 100) if active else 0
        lines.append(f"| {cat_name} | {fmt(info['seconds'])} | {pct}% |")

    # Split by_app into desktop apps vs web domains
    by_app  = sorted(stats["by_app"].items(), key=lambda x: -x[1])
    app_cat = stats.get("app_category", {})

    exe_rows = [(k, v) for k, v in by_app if not _is_domain(k) and not _is_internal(k)]
    web_rows = [(k, v) for k, v in by_app if _is_domain(k)]

    def _app_table(rows: list) -> list:
        out = [
            "| Приложение | Категория | Время | % |",
            "|-----------|-----------|-------|---|",
        ]
        for app_key, sec in rows:
            cat_name = app_cat.get(app_key, {}).get("name", "Прочее")
            pct = round(sec / active * 100) if active else 0
            out.append(f"| {app_key} | {cat_name} | {fmt(sec)} | {pct}% |")
        return out

    if exe_rows:
        lines += ["", "---", "", "## По приложениям", ""]
        lines += _app_table(exe_rows)

    if web_rows:
        lines += ["", "---", "", "## По сайтам", ""]
        lines += _app_table(web_rows)

    if idle > 0:
        idle_pct = round(idle / total_t * 100) if total_t else 0
        lines += ["", f"> ⏸ Неактивен: {fmt(idle)} ({idle_pct}% от всего времени)"]

    lines.append("")

    os.makedirs(export_dir, exist_ok=True)
    date_compact = date_str.replace("-", "")
    file_path = os.path.join(export_dir, f"{date_compact}-activity.md")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return file_path


# ─── CSV daily export ──────────────────────────────────────────────────────

def generate_daily_csv(date_str: str, export_dir: str):
    """Write activity_YYYY-MM-DD_YYYY-MM-DD.csv for the given day.
    Returns the file path, or None if there are no events."""
    import csv
    import datetime
    import os

    day = datetime.date.fromisoformat(date_str)
    ts_start = int(datetime.datetime(day.year, day.month, day.day).timestamp())
    ts_end = ts_start + 86400

    with _conn() as conn:
        rows = conn.execute(
            """SELECT e.timestamp, e.app_name, e.window_title, e.url,
                      e.page_title, e.is_idle, e.source
               FROM events e
               WHERE e.timestamp >= ? AND e.timestamp < ?
               ORDER BY e.timestamp""",
            (ts_start, ts_end),
        ).fetchall()

        rules_rows = conn.execute(
            """SELECT r.rule_type, r.value, r.category_id
               FROM rules r
               JOIN categories c ON c.id = r.category_id
               ORDER BY c.sort_order, r.sort_order"""
        ).fetchall()
        cats_map = {
            r["id"]: r["name"]
            for r in conn.execute("SELECT id, name FROM categories")
        }
        default_row = conn.execute(
            "SELECT id FROM categories WHERE is_default=1 LIMIT 1"
        ).fetchone()
        default_cat_id = default_row["id"] if default_row else None

    if not rows:
        return None

    rules_list = [dict(r) for r in rules_rows]

    os.makedirs(export_dir, exist_ok=True)
    file_name = f"activity_{date_str}_{date_str}.csv"
    file_path = os.path.join(export_dir, file_name)

    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["datetime", "app_name", "window_title",
                          "url", "page_title", "category", "is_idle", "source"])
        for r in rows:
            ev = dict(r)
            cat_id = _classify_with(ev["app_name"], ev.get("url"), rules_list, default_cat_id)
            cat_name = cats_map.get(cat_id, "Прочее") if cat_id is not None else "Прочее"
            dt_str = datetime.datetime.fromtimestamp(ev["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([
                dt_str,
                ev["app_name"],
                ev.get("window_title") or "",
                ev.get("url") or "",
                ev.get("page_title") or "",
                cat_name,
                ev["is_idle"],
                ev["source"],
            ])

    return file_path


# ─── Export ────────────────────────────────────────────────────────────────

def get_events_range(from_ts: int, to_ts: int) -> list:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT e.*, c.name as category_name, c.color as category_color
               FROM events e
               LEFT JOIN categories c ON c.id = e.category_id
               WHERE e.timestamp >= ? AND e.timestamp < ?
               ORDER BY e.timestamp""",
            (from_ts, to_ts),
        ).fetchall()
    return [dict(r) for r in rows]
