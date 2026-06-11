"""Unit tests for data models and utilities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pistomp_recovery.items import Action, Item
from pistomp_recovery.util import human_time


class TestHumanTime:
    def test_just_now(self) -> None:
        now: datetime = datetime.now(timezone.utc)
        assert human_time(now) == "just now"

    def test_seconds_ago(self) -> None:
        now: datetime = datetime.now(timezone.utc)
        ts: datetime = now - timedelta(seconds=30)
        assert human_time(ts) == "just now"

    def test_minutes_ago(self) -> None:
        now: datetime = datetime.now(timezone.utc)
        ts: datetime = now - timedelta(minutes=42)
        assert human_time(ts) == "42m ago"

    def test_hours_ago(self) -> None:
        now: datetime = datetime.now(timezone.utc)
        ts: datetime = now - timedelta(hours=3)
        assert human_time(ts) == "3h ago"

    def test_days_ago(self) -> None:
        now: datetime = datetime.now(timezone.utc)
        ts: datetime = now - timedelta(days=2)
        assert human_time(ts) == "2 days ago"

    def test_one_day_ago(self) -> None:
        now: datetime = datetime.now(timezone.utc)
        ts: datetime = now - timedelta(days=1)
        assert human_time(ts) == "1 day ago"

    def test_weeks_ago_same_year(self) -> None:
        ts: datetime = datetime(2026, 5, 20, tzinfo=timezone.utc)
        result: str = human_time(ts)
        assert "May" in result
        assert "2026" not in result

    def test_weeks_ago_different_year(self) -> None:
        ts: datetime = datetime(2024, 12, 25, tzinfo=timezone.utc)
        result: str = human_time(ts)
        assert "Dec" in result
        assert "2024" in result

    def test_naive_datetime_treated_as_utc(self) -> None:
        ts: datetime = datetime(2026, 6, 9, 12, 0, 0)
        result: str = human_time(ts)
        assert isinstance(result, str)

    def test_future_time_treated_as_just_now(self) -> None:
        now: datetime = datetime.now(timezone.utc)
        ts: datetime = now + timedelta(minutes=5)
        assert human_time(ts) == "just now"


class TestItem:
    def test_item_attributes(self) -> None:
        item: Item = Item(
            name="jack2-pistomp",
            label="jack2-pistomp *",
            dirty=True,
            right="↑1.9.13",
            actions=[Action("Update", lambda: None)],
        )
        assert item.name == "jack2-pistomp"
        assert item.dirty is True
        assert "*" in item.label

    def test_action_confirm(self) -> None:
        action: Action = Action("Rollback", lambda: None, confirm="Sure?")
        assert action.confirm == "Sure?"

    def test_action_no_confirm(self) -> None:
        action: Action = Action("Rollback", lambda: None)
        assert action.confirm is None
