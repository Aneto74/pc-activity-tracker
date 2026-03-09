"""Tests for pure functions in database module — no Windows dependencies."""
import pytest
from agent.database import _classify_with, _extract_domain, _is_domain, _is_internal, _aggregate_stats


# ─── _classify_with ───────────────────────────────────────────────────────

RULES = [
    {"rule_type": "app_contains", "value": "code", "category_id": 1},
    {"rule_type": "app_contains", "value": "slack", "category_id": 2},
    {"rule_type": "app_exact", "value": "telegram.exe", "category_id": 3},
    {"rule_type": "url_contains", "value": "github", "category_id": 4},
    {"rule_type": "url_domain", "value": "youtube.com", "category_id": 5},
]
DEFAULT_CAT = 99


class TestClassifyWith:
    def test_app_contains(self):
        assert _classify_with("Code.exe", None, RULES, DEFAULT_CAT) == 1

    def test_app_contains_case_insensitive(self):
        assert _classify_with("SLACK.EXE", None, RULES, DEFAULT_CAT) == 2

    def test_app_exact(self):
        assert _classify_with("Telegram.exe", None, RULES, DEFAULT_CAT) == 3

    def test_app_exact_no_partial_match(self):
        # "telegram_desktop.exe" should NOT match app_exact "telegram.exe"
        assert _classify_with("telegram_desktop.exe", None, RULES, DEFAULT_CAT) != 3

    def test_url_contains(self):
        assert _classify_with("chrome.exe", "https://github.com/repo", RULES, DEFAULT_CAT) == 4

    def test_url_domain(self):
        assert _classify_with("chrome.exe", "https://youtube.com/watch?v=123", RULES, DEFAULT_CAT) == 5

    def test_url_domain_with_subdomain(self):
        assert _classify_with("chrome.exe", "https://music.youtube.com/", RULES, DEFAULT_CAT) == 5

    def test_no_match_returns_default(self):
        assert _classify_with("notepad.exe", None, RULES, DEFAULT_CAT) == DEFAULT_CAT

    def test_no_match_no_default(self):
        assert _classify_with("notepad.exe", None, RULES, None) is None

    def test_empty_rules(self):
        assert _classify_with("code.exe", None, [], DEFAULT_CAT) == DEFAULT_CAT

    def test_priority_first_rule_wins(self):
        # "code" matches rule 1 (app_contains "code"), should not fall through
        assert _classify_with("code.exe", "https://github.com/vscode", RULES, DEFAULT_CAT) == 1

    def test_url_ignored_when_none(self):
        assert _classify_with("chrome.exe", None, RULES, DEFAULT_CAT) == DEFAULT_CAT


# ─── _extract_domain ─────────────────────────────────────────────────────

class TestExtractDomain:
    def test_basic_url(self):
        assert _extract_domain("https://github.com/repo") == "github.com"

    def test_strips_www(self):
        assert _extract_domain("https://www.youtube.com/watch") == "youtube.com"

    def test_strips_query(self):
        assert _extract_domain("https://example.com?q=test") == "example.com"

    def test_no_scheme(self):
        assert _extract_domain("github.com/path") == "github.com"

    def test_none(self):
        assert _extract_domain(None) is None

    def test_empty(self):
        assert _extract_domain("") is None


# ─── _is_internal / _is_domain ───────────────────────────────────────────

class TestIsInternal:
    def test_localhost(self):
        assert _is_internal("localhost") is True

    def test_loopback(self):
        assert _is_internal("127.0.0.1") is True

    def test_loopback_with_port(self):
        assert _is_internal("127.0.0.1:27420") is True

    def test_regular_domain(self):
        assert _is_internal("github.com") is False


class TestIsDomain:
    def test_domain(self):
        assert _is_domain("github.com") is True

    def test_exe(self):
        assert _is_domain("chrome.exe") is False

    def test_localhost(self):
        assert _is_domain("localhost") is False

    def test_loopback(self):
        assert _is_domain("127.0.0.1") is False

    def test_subdomain(self):
        assert _is_domain("docs.google.com") is True


# ─── _aggregate_stats ────────────────────────────────────────────────────

class TestAggregateStats:
    def _make_event(self, ts, app, idle=0, source="agent", url=None,
                    cat_name="Работа", cat_color="#4A90E2"):
        return {
            "timestamp": ts,
            "app_name": app,
            "is_idle": idle,
            "source": source,
            "url": url,
            "category_name": cat_name,
            "category_color": cat_color,
        }

    def test_basic_active_time(self):
        events = [
            self._make_event(1000, "code.exe"),
            self._make_event(1010, "code.exe"),
            self._make_event(1020, "code.exe"),
        ]
        result = _aggregate_stats(events)
        assert result["active_seconds"] == 30  # 10 + 10 + fallback 10
        assert result["idle_seconds"] == 0

    def test_idle_events_separated(self):
        events = [
            self._make_event(1000, "code.exe", idle=0),
            self._make_event(1010, "code.exe", idle=1),
            self._make_event(1020, "code.exe", idle=0),
        ]
        result = _aggregate_stats(events)
        assert result["idle_seconds"] == 10
        assert result["active_seconds"] == 20  # 10 + fallback 10

    def test_gap_capped_at_60(self):
        events = [
            self._make_event(1000, "code.exe"),
            self._make_event(2000, "code.exe"),  # 1000s gap → capped to 60
        ]
        result = _aggregate_stats(events)
        assert result["active_seconds"] == 60 + 10  # capped + fallback

    def test_extension_dedup_skips_agent_browser_events(self):
        events = [
            self._make_event(1000, "chrome.exe", source="agent"),
            self._make_event(1005, "chrome.exe", source="extension", url="https://github.com"),
            self._make_event(1010, "code.exe"),
        ]
        result = _aggregate_stats(events)
        # agent chrome event at 1000 should be skipped (extension at 1005 within ±15s)
        # only extension(1005→1010=5s) + code(1010→fallback=10s)
        assert result["active_seconds"] == 5 + 10

    def test_browser_url_grouped_by_domain(self):
        events = [
            self._make_event(1000, "chrome.exe", source="extension",
                             url="https://github.com/repo1"),
            self._make_event(1010, "chrome.exe", source="extension",
                             url="https://github.com/repo2"),
        ]
        result = _aggregate_stats(events)
        assert "github.com" in result["by_app"]

    def test_empty_events(self):
        result = _aggregate_stats([])
        assert result["active_seconds"] == 0
        assert result["idle_seconds"] == 0
        assert result["total_events"] == 0
