# PC Activity Tracker

Lightweight, privacy-first Windows activity tracker that runs in the background and keeps all data local. No subscriptions, no cloud — your data stays on your machine.

![Platform: Windows](https://img.shields.io/badge/platform-Windows-blue)
![Python 3.10+](https://img.shields.io/badge/python-3.10+-green)
![License: MIT](https://img.shields.io/badge/license-MIT-yellow)

## What it does

- Tracks active applications, window titles, and Chrome browsing activity
- Categorizes time automatically using customizable rules
- Exports daily reports as Markdown and CSV
- Generates ready-to-use prompts for AI productivity analysis (Claude, ChatGPT, etc.)

## Architecture

Three components communicating via local HTTP server on `localhost:27420`:

| Component | Tech | Role |
|-----------|------|------|
| Desktop Agent | Python (pystray, psutil, Flask) | Polls active window every N seconds, writes to SQLite, serves HTTP API |
| Chrome Extension | Manifest V3 | Captures URL and page title of active tab, sends to agent |
| Web UI | HTML + Vanilla JS + Canvas | Dashboard, category editor, history charts, export tools |

```
Desktop Agent (window polling) ──→ SQLite ──→ HTTP API (:27420)
Chrome Extension (URL + title) ──→ HTTP API ──→ SQLite
Web UI ↔ HTTP API (stats, categories, export)
```

## Features

- **Background tracking** — runs in system tray, minimal CPU/RAM usage
- **Idle detection** — pauses tracking after configurable inactivity period
- **Smart categorization** — rule-based system (app name, URL domain, etc.) with drag-and-drop priority
- **Daily dashboard** — pie chart, timeline, app table with live category assignment
- **History view** — stacked bar charts for any date range
- **Auto-export** — daily Markdown + CSV reports generated automatically
- **AI-ready export** — one-click prompt generation with embedded activity data
- **Windows autostart** — toggle from Web UI, uses Windows Registry

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the agent

```bash
python run.py
```

Or run without console window:

```bash
pythonw run_tray.pyw
```

The agent starts in the system tray. Open the dashboard at [http://127.0.0.1:27420](http://127.0.0.1:27420).

### 3. Install Chrome Extension (optional)

1. Open `chrome://extensions/`
2. Enable "Developer mode"
3. Click "Load unpacked" → select the `extension/` folder

## Configuration

Settings are available in Web UI → Settings tab, or in `data/config.json`:

| Setting | Default | Description |
|---------|---------|-------------|
| `poll_interval` | 10 | Window polling interval (seconds) |
| `idle_threshold` | 300 | Idle timeout (seconds) |
| `api_port` | 27420 | HTTP server port |
| `export_dir` | `data/export` | Directory for Markdown/CSV reports |

## Privacy

- All data stored locally in SQLite (`data/activity.db`)
- HTTP server listens only on `127.0.0.1` — not accessible from network
- Incognito tabs are not tracked by default
- No telemetry, no external API calls

## License

MIT
