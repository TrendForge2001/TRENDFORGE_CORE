"""Cloud access failures must not prevent independent NSE reads or owner recovery."""

import base64
import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from core.database import initialize_database
from database.repositories.big_shark_repository import (
    BigSharkRepository,
    BigSharkSnapshotConflict,
)
from database.repositories.trade_repository import TradeRepository
from services import big_shark_portfolio, big_shark_source_scheduler
from services.big_shark_activity import import_records
from services.big_shark_portfolio import bootstrap_from_environment, read_portfolio
from services.big_shark_public_feed import refresh_public_sources
from services.big_shark_source_scheduler import refresh_requested
from tests.test_big_shark_portfolio import workbook
from tests.test_big_shark_public_feeds import NOW, Feed, trade


@pytest.fixture
def empty_owner(tmp_path, monkeypatch):
    path = str(tmp_path / "private.db")
    monkeypatch.setenv("DATABASE_PATH", path)
    monkeypatch.setenv("TRENDFORGE_PRODUCTION_RUNTIME", "false")
    monkeypatch.setenv("RENDER", "false")
    monkeypatch.delenv("TRENDFORGE_BIG_SHARK_WORKBOOK_B64", raising=False)
    monkeypatch.delenv("TRENDFORGE_BIG_SHARK_REFRESH_REQUEST", raising=False)
    initialize_database(path)
    repo = BigSharkRepository(path)
    yield SimpleNamespace(repo=repo, path=path)
    repo.close()


def test_empty_scanner_still_fetches_nse_when_moneycontrol_denies_access(empty_owner):
    feed = Feed(failures=("holdings",))
    state = refresh_public_sources(empty_owner.repo, provider=feed, now=NOW)
    assert feed.calls == ["holdings", "trades"]
    assert state["status"] == "partial"
    assert state["failures"] == {"MONEYCONTROL": "SOURCE_ACCESS_UNAVAILABLE"}
    assert state["trades"]["records_received"] == 1
    assert state["trades"]["preview_rows"][0]["symbol"] == "EXAMPLE"
    assert state["portfolio_loaded"] is False
    assert state["snapshot_id"] is None
    assert empty_owner.repo.latest() is None
    assert state["paper_orders_allowed"] is state["broker_orders_allowed"] is False


def test_both_sources_are_attempted_and_reported_without_a_portfolio(empty_owner):
    feed = Feed(failures=("holdings", "trades"))
    state = refresh_public_sources(empty_owner.repo, provider=feed, now=NOW)
    assert feed.calls == ["holdings", "trades"]
    assert state["status"] == "unavailable"
    assert set(state["failures"]) == {"MONEYCONTROL", "NSE_BULK"}
    assert state.get("last_success_at") is None
    assert empty_owner.repo.latest() is None


def test_import_after_ist_midnight_accepts_the_current_ist_reporting_day():
    now = datetime(2026, 11, 20, 19, 30, tzinfo=UTC)
    end = date(2026, 11, 21)
    start = date(2026, 11, 15)
    rows = Feed().trades(source="NSE_BULK", start=start, end=end, now=now)["rows"]
    result = import_records(
        read_portfolio(workbook()),
        rows,
        source="NSE_BULK",
        metric="quantity",
        period_start=start,
        period_end=end,
        now=now,
    )
    assert result["activity_window"]["end"] == "2026-11-21"
    assert result["signals"][0]["activity_signal"] == "BUY"
    with pytest.raises(ValueError, match="future"):
        import_records(
            read_portfolio(workbook()),
            rows,
            source="NSE_BULK",
            metric="quantity",
            period_start=start,
            period_end=date(2026, 11, 22),
            now=now,
        )


def test_public_preview_does_not_create_signals_until_owner_investors_are_known(
    empty_owner,
):
    feed = Feed(failures=("holdings",))
    refresh_public_sources(empty_owner.repo, provider=feed, now=NOW)
    empty_owner.repo.save(read_portfolio(workbook()))
    state = refresh_public_sources(empty_owner.repo, provider=feed, now=NOW)
    assert state["portfolio_loaded"] is True
    assert state["trades"]["matched_records"] == 1
    assert empty_owner.repo.latest()["signals"][0]["activity_signal"] == "BUY"


def test_public_preview_is_bounded_without_claiming_complete_coverage(empty_owner):
    feed = Feed([trade(quantity=i + 1) for i in range(101)], failures=("holdings",))
    state = refresh_public_sources(empty_owner.repo, provider=feed, now=NOW)
    assert state["trades"]["records_received"] == 101
    assert len(state["trades"]["preview_rows"]) == 100
    assert state["trades"]["coverage"] == "DISCLOSED_ONLY"
    assert empty_owner.repo.latest() is None


def test_owner_import_wins_while_empty_scanner_fetches_nse(empty_owner):
    feed = Feed(failures=("holdings",))
    feed.callback = lambda: empty_owner.repo.save(
        read_portfolio(workbook(stock="Owner Replacement"))
    )
    with pytest.raises(BigSharkSnapshotConflict):
        refresh_public_sources(empty_owner.repo, provider=feed, now=NOW)
    assert empty_owner.repo.latest()["stock_rows"][0][0] == "Owner Replacement"


def test_seed_cannot_replace_an_existing_owner_workbook(empty_owner, monkeypatch):
    current = empty_owner.repo.save(read_portfolio(workbook(stock="Owner Updated")))
    monkeypatch.setenv(
        "TRENDFORGE_BIG_SHARK_WORKBOOK_B64", base64.b64encode(workbook()).decode()
    )
    bootstrap_from_environment(empty_owner.repo)
    assert empty_owner.repo.latest() == current


def test_owner_import_wins_while_private_seed_is_being_parsed(empty_owner, monkeypatch):
    monkeypatch.setenv(
        "TRENDFORGE_BIG_SHARK_WORKBOOK_B64", base64.b64encode(workbook()).decode()
    )
    parse = big_shark_portfolio.read_portfolio

    def owner_imports(data):
        empty_owner.repo.save(parse(workbook(stock="Owner Updated")))
        return parse(data)

    monkeypatch.setattr(big_shark_portfolio, "read_portfolio", owner_imports)
    bootstrap_from_environment(empty_owner.repo)
    assert empty_owner.repo.latest()["stock_rows"][0][0] == "Owner Updated"


def test_requested_refresh_is_once_only_private_and_preserves_paper_book(
    empty_owner, monkeypatch
):
    monkeypatch.setenv("TRENDFORGE_BIG_SHARK_REFRESH_REQUEST", "a" * 32)
    monkeypatch.setenv(
        "TRENDFORGE_BIG_SHARK_WORKBOOK_B64", base64.b64encode(workbook()).decode()
    )
    paper = TradeRepository(db=empty_owner.repo.db)
    for symbol in ("PAPER_A", "PAPER_B", "PAPER_C"):
        paper.save(symbol, "BUY", 3, 100, stoploss=90, target=130)
    positions = [dict(row) for row in paper.open_trades()]
    empty_owner.repo.save_source_state({"enabled": False}, "config")
    feed = Feed(failures=("holdings",))

    def factory():
        return BigSharkRepository(empty_owner.path)

    result = refresh_requested(now=NOW, provider=feed, repository_factory=factory)
    assert result["status"] == "partial"
    assert result["portfolio_loaded"] is True
    assert result["matched_records"] == result["stocks"] == 1
    assert empty_owner.repo.latest()["signals"][0]["activity_signal"] == "BUY"
    assert "Fund A" not in json.dumps(result) and "EXAMPLE" not in json.dumps(result)
    assert empty_owner.repo.source_state("config")["enabled"] is False
    assert refresh_requested(now=NOW, provider=feed, repository_factory=factory) == {
        "status": "already_consumed"
    }
    assert feed.calls == ["holdings", "trades"]
    assert result["paper_automation_changed"] is False
    assert result["broker_orders_allowed"] is False
    assert [dict(row) for row in paper.open_trades()] == positions


def test_requested_refresh_requires_verified_production_storage(
    empty_owner, monkeypatch
):
    monkeypatch.setenv("TRENDFORGE_BIG_SHARK_REFRESH_REQUEST", "a" * 32)
    monkeypatch.setattr(
        big_shark_source_scheduler, "production_runtime_enabled", lambda: True
    )
    monkeypatch.setattr(big_shark_source_scheduler, "storage_health", lambda: {})
    feed = Feed()
    assert refresh_requested(now=NOW, provider=feed) == {"status": "storage_unverified"}
    assert feed.calls == []


def test_unavailable_feeds_leave_seeded_holdings_as_no_data(empty_owner, monkeypatch):
    monkeypatch.setenv("TRENDFORGE_BIG_SHARK_REFRESH_REQUEST", "a" * 32)
    monkeypatch.setenv(
        "TRENDFORGE_BIG_SHARK_WORKBOOK_B64", base64.b64encode(workbook()).decode()
    )
    result = refresh_requested(
        now=NOW,
        provider=Feed(failures=("holdings", "trades")),
        repository_factory=lambda: BigSharkRepository(empty_owner.path),
    )
    assert result["status"] == "unavailable"
    assert result["portfolio_loaded"] is True
    assert empty_owner.repo.latest()["signals"][0]["signal"] == "NO_DATA"
