"""Synthetic public disclosures; no owner portfolios or live broker clients."""

import copy
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from api.big_shark_router import big_shark_router
from core.database import initialize_database
from database.repositories.big_shark_repository import (
    BigSharkRepository,
    BigSharkSnapshotConflict,
)
from database.repositories.trade_repository import TradeRepository
from providers.big_shark_public import (
    HOLDINGS,
    MAX_BYTES,
    MONEYCONTROL,
    BigSharkPublicProvider,
    PublicFeedError,
    parse_moneycontrol_catalog,
    parse_moneycontrol_holdings,
    parse_nse_deals,
)
from services.big_shark_portfolio import read_portfolio, workbook_bytes
from services.big_shark_public_feed import refresh_public_sources, source_view
from services.big_shark_source_scheduler import refresh_if_due
from tests.test_big_shark_portfolio import workbook

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)
CATALOG = b"""<h2>Individual Investors</h2><table><tr><td>
<h3><a href="/india-investors-portfolio/fund-a">Fund A</a></h3>
#Company Holdings: 2</td><td>123.45</td></tr></table>"""
HOLDING = b"""<p>As on quarter Sep 2026</p><table><tr>
<th>Stock Name</th><th>Investor Name</th><th>Action</th><th>Holding%</th>
<th>Change From Prev. Qtr.</th><th>Holding Value (Crs)</th><th>Quantity Held</th></tr>
<tr><td>Example</td><td>Fund A</td><td>BOUGHT</td><td>5.25 %</td>
<td>New</td><td>125.20</td><td>1,00,000</td></tr></table>"""


def trade(investor="Fund A", side="BUY", quantity=100):
    return {
        "BD_DT_DATE": "19-NOV-2026",
        "BD_DT_ORDER": "2026-11-18T18:30:00+00:00",
        "BD_SYMBOL": "EXAMPLE",
        "BD_SCRIP_NAME": "Example",
        "BD_CLIENT_NAME": investor,
        "BD_BUY_SELL": side,
        "BD_QTY_TRD": quantity,
        "BD_TP_WATP": "20.50",
    }


class Feed:
    def __init__(self, rows=None, failures=()):
        self.rows = rows if rows is not None else [trade()]
        self.failures = failures
        self.calls = []
        self.callback = None

    def holdings(self, *, now):
        self.calls.append("holdings")
        if "holdings" in self.failures:
            raise PublicFeedError("SOURCE_ACCESS_UNAVAILABLE")
        return {
            **parse_moneycontrol_holdings(HOLDING, now=now),
            "investors": parse_moneycontrol_catalog(CATALOG),
            "document_sha256": "a" * 64,
        }

    def trades(self, *, source, start, end, now):
        self.calls.append("trades")
        if self.callback:
            self.callback()
        if "trades" in self.failures:
            raise PublicFeedError("SOURCE_NETWORK_UNAVAILABLE")
        return {
            "rows": parse_nse_deals(json.dumps(self.rows).encode(), now=now),
            "source": source,
            "source_url": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals",
            "coverage": "DISCLOSED_ONLY",
            "document_sha256": "b" * 64,
        }


@pytest.fixture
def owner(tmp_path, monkeypatch):
    path = str(tmp_path / "private.db")
    monkeypatch.setenv("DATABASE_PATH", path)
    monkeypatch.setenv("TRENDFORGE_PRODUCTION_RUNTIME", "false")
    monkeypatch.setenv("RENDER", "false")
    initialize_database(path)
    repo = BigSharkRepository(path)
    repo.save(read_portfolio(workbook()))
    yield SimpleNamespace(repo=repo, path=path)
    repo.close()


def test_moneycontrol_reports_holdings_without_inventing_transactions():
    catalog = parse_moneycontrol_catalog(CATALOG)
    assert catalog[0]["company_holdings"] == 2
    assert catalog[0]["networth_cr"] == 123.45
    result = parse_moneycontrol_holdings(HOLDING, now=NOW)
    assert result["rows"][0]["quantity_held"] == 100000
    assert result["rows"][0]["holding_percent"] == 5.25
    assert result["rows"][0]["is_actual_trade"] is False
    assert result["rows"][0]["disclosed_at"] is None
    assert result["coverage"] == "VISIBLE_PUBLIC_ROWS_ONLY"
    future = parse_moneycontrol_holdings(
        HOLDING.replace(b"Sep 2026", b"Dec 2026"), now=NOW
    )
    assert future["period_status"] == "OPEN_OR_FUTURE_QUARTER"


def test_nse_sort_date_is_not_disclosure_time_and_truncation_is_rejected():
    rows = parse_nse_deals(json.dumps([trade()]).encode(), now=NOW)
    assert rows[0]["trade_date"] == "2026-11-19"
    assert rows[0]["disclosed_at"] is None
    with pytest.raises(PublicFeedError, match="TRUNCATED"):
        parse_nse_deals(
            json.dumps({"data": [trade()], "totalRecords": 70}).encode(), now=NOW
        )
    with pytest.raises(PublicFeedError):
        parse_nse_deals(json.dumps([trade(quantity=-1)]).encode(), now=NOW)
    assert parse_nse_deals(b"[]", now=NOW) == []


def test_refresh_populates_actual_trade_signal_and_preserves_three_paper_positions(
    owner,
):
    trades = TradeRepository(db=owner.repo.db)
    for symbol in ("ONE", "TWO", "THREE"):
        trades.save(symbol, "BUY", 5, 100, stoploss=90, target=130)
    positions = [dict(row) for row in trades.open_trades()]
    original = copy.deepcopy(owner.repo.latest())
    state = refresh_public_sources(owner.repo, provider=Feed(), now=NOW)
    latest = owner.repo.latest()
    assert state["status"] == "refreshed"
    assert latest["signals"][0]["activity_signal"] == "BUY"
    assert latest["signals"][0]["avg_buy"] == 100
    assert latest["signals"][0]["data_coverage"] == "DISCLOSED_ONLY"
    assert latest["signals"][0]["technical_confirmation"] == "NOT_CHECKED"
    assert latest["stock_rows"] == original["stock_rows"]
    assert latest["execution_enabled"] is False
    assert [dict(row) for row in trades.open_trades()] == positions
    assert state["paper_orders_allowed"] is state["broker_orders_allowed"] is False


def test_side_means_not_side_totals_drive_public_feed_signal(owner):
    base = owner.repo.latest()
    base["investor_rows"].extend(
        [
            ["Individual", "Fund B", 1, 1, "Public"],
            ["Individual", "Fund C", 1, 1, "Public"],
        ]
    )
    base["source_sha256"] = "new-owner-content"
    owner.repo.save(base)
    refresh_public_sources(
        owner.repo,
        provider=Feed(
            [
                trade(quantity=80),
                trade("Fund B", quantity=120),
                trade("Fund C", "SELL", 150),
            ]
        ),
        now=NOW,
    )
    signal = owner.repo.latest()["signals"][0]
    assert (signal["avg_buy"], signal["avg_sell"], signal["activity_signal"]) == (
        100,
        150,
        "SELL",
    )


def test_exact_aliases_only_and_invalid_aliases_cause_no_outbound_request(owner):
    feed = Feed([trade("Fund-A")])
    refresh_public_sources(owner.repo, provider=feed, now=NOW)
    assert owner.repo.latest()["signals"][0]["activity_signal"] == "NO_DATA"
    refresh_public_sources(
        owner.repo, provider=feed, now=NOW, aliases={"Fund-A": "Fund A"}
    )
    assert owner.repo.latest()["signals"][0]["activity_signal"] == "BUY"
    invalid = Feed()
    with pytest.raises(ValueError, match="tracked"):
        refresh_public_sources(
            owner.repo, provider=invalid, now=NOW, aliases={"Unknown": "Not Tracked"}
        )
    assert invalid.calls == []


def test_empty_successful_window_clears_old_buy_but_retains_history(owner):
    refresh_public_sources(owner.repo, provider=Feed(), now=NOW)
    previous = owner.repo.latest()
    refresh_public_sources(owner.repo, provider=Feed([]), now=NOW + timedelta(days=1))
    latest = owner.repo.latest()
    assert previous["signals"][0]["activity_signal"] == "BUY"
    assert latest["signals"][0]["activity_signal"] == "NO_DATA"
    assert latest["signals"][0]["data_coverage"] == "NO_MATCHING_DISCLOSURE"
    assert latest["trade_records"] == []
    assert owner.repo.has_source(previous["source_sha256"])


def test_upstream_failure_preserves_last_good_data_and_date(owner):
    state = refresh_public_sources(owner.repo, provider=Feed(), now=NOW)
    original = copy.deepcopy(owner.repo.latest())
    failed = refresh_public_sources(
        owner.repo,
        provider=Feed(failures=("holdings", "trades")),
        now=NOW + timedelta(hours=1),
    )
    assert failed["status"] == "unavailable"
    assert owner.repo.latest() == original
    assert failed["holdings"]["fetched_at"] == state["holdings"]["fetched_at"]
    assert failed["last_success_at"] == state["last_success_at"]


def test_returning_disclosures_restore_signal_after_empty_response(owner):
    refresh_public_sources(owner.repo, provider=Feed(), now=NOW)
    refresh_public_sources(owner.repo, provider=Feed([]), now=NOW)
    assert owner.repo.latest()["signals"][0]["activity_signal"] == "NO_DATA"
    refresh_public_sources(owner.repo, provider=Feed(), now=NOW)
    assert owner.repo.latest()["signals"][0]["activity_signal"] == "BUY"


def test_repeat_holdings_fetch_retains_true_first_seen_time(owner):
    first = refresh_public_sources(owner.repo, provider=Feed(), now=NOW)
    second = refresh_public_sources(
        owner.repo, provider=Feed(), now=NOW + timedelta(hours=1)
    )
    assert (
        second["holdings"]["rows"][0]["first_seen_at"]
        == first["holdings"]["rows"][0]["first_seen_at"]
    )
    assert second["holdings"]["fetched_at"] != first["holdings"]["fetched_at"]


def test_bootstrap_without_workbook_never_treats_holdings_as_buys(
    tmp_path,
):
    path = str(tmp_path / "empty.db")
    initialize_database(path)
    repo = BigSharkRepository(path)
    try:
        refresh_public_sources(repo, provider=Feed([]), now=NOW)
        latest = repo.latest()
        assert latest["portfolio_origin"] == "MONEYCONTROL_PUBLIC"
        assert latest["stock_rows"][0][-1] == 100000
        assert latest["signals"][0]["activity_signal"] == "NO_DATA"
    finally:
        repo.close()


def test_concurrent_owner_import_wins_over_slow_public_refresh(owner):
    original = owner.repo.latest()
    feed = Feed()

    def change():
        changed = read_portfolio(workbook(stock="Owner New Stock"))
        owner.repo.save(changed)

    feed.callback = change
    with pytest.raises(BigSharkSnapshotConflict):
        refresh_public_sources(owner.repo, provider=feed, now=NOW)
    assert owner.repo.latest()["snapshot_id"] != original["snapshot_id"]
    assert owner.repo.latest()["stock_rows"][0][0] == "Owner New Stock"


def test_daily_schedule_is_owner_enabled_and_does_not_repeat(owner):
    def factory():
        return BigSharkRepository(owner.path)

    feed = Feed()
    assert (
        refresh_if_due(now=NOW, provider=feed, repository_factory=factory)["status"]
        == "disabled"
    )
    owner.repo.save_source_state({"enabled": True}, "config")
    assert (
        refresh_if_due(now=NOW, provider=feed, repository_factory=factory)["status"]
        == "refreshed"
    )

    count = len(feed.calls)
    assert (
        refresh_if_due(
            now=NOW + timedelta(hours=1), provider=feed, repository_factory=factory
        )["status"]
        == "not_due"
    )
    assert len(feed.calls) == count
    state = owner.repo.source_state()
    state["checked_at"] = (NOW - timedelta(hours=25)).isoformat()
    owner.repo.save_source_state(state)
    assert (
        refresh_if_due(now=NOW, provider=feed, repository_factory=factory)["status"]
        == "refreshed"
    )


def test_owner_import_wins_even_when_both_public_sources_fail(owner):
    feed = Feed(failures=("holdings", "trades"))

    def change():
        owner.repo.save(read_portfolio(workbook(stock="Replacement Stock")))

    feed.callback = change
    with pytest.raises(BigSharkSnapshotConflict):
        refresh_public_sources(owner.repo, provider=feed, now=NOW)
    assert owner.repo.latest()["stock_rows"][0][0] == "Replacement Stock"


def test_exports_keep_holdings_and_actual_trades_separate(owner):
    refresh_public_sources(owner.repo, provider=Feed(), now=NOW)
    data = workbook_bytes(owner.repo.latest(), public_sources=source_view(owner.repo))
    book = load_workbook(BytesIO(data), data_only=False)
    try:
        assert "PUBLIC HOLDINGS" in book.sheetnames
        assert book["PUBLIC INVESTORS"]["D2"].value == 123.45
        assert book["BIG SHARK"]["D2"].value == 100
        assert "TRADE DISCLOSURES" in book.sheetnames
        assert book["PUBLIC SOURCE STATUS"]["B11"].data_type != "f"
        assert list(book["PUBLIC HOLDINGS"].values)[1][2] == 100000
        assert list(book["TRADE DISCLOSURES"].values)[1][5] == 100
    finally:
        book.close()


class Response:
    def __init__(self, data=b"", status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, size):
        yield self.data


def test_fetcher_does_not_send_private_data_and_rejects_redirect_to_internal_host():
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(CATALOG if url == MONEYCONTROL else HOLDING)

    feed = BigSharkPublicProvider(SimpleNamespace(get=get))
    assert feed.holdings(now=NOW)["rows"][0]["quantity_held"] == 100000
    assert [c[0] for c in calls] == [MONEYCONTROL, HOLDINGS]
    assert all(
        "Authorization" not in c[1]["headers"] and "params" not in c[1] for c in calls
    )
    unsafe = BigSharkPublicProvider(
        SimpleNamespace(
            get=lambda *a, **k: Response(
                status=302, headers={"Location": "http://127.0.0.1/private"}
            )
        )
    )
    with pytest.raises(PublicFeedError, match="URL_REJECTED"):
        unsafe.holdings(now=NOW)
    huge = BigSharkPublicProvider(
        SimpleNamespace(get=lambda *a, **k: Response(b"x" * (MAX_BYTES + 1)))
    )
    with pytest.raises(PublicFeedError, match="TOO_LARGE"):
        huge.holdings(now=NOW)
    assert str(PublicFeedError("private upstream credential")) == "SOURCE_UNAVAILABLE"


def test_archive_fallback_reports_actual_day_and_keeps_publication_unknown(owner):
    csv_data = (
        b"Date,Symbol,Security Name,Client Name,Buy / Sell,Quantity Traded,"
        b"Trade Price / Wght. Avg. Price\n"
        b"19-Nov-2026,EXAMPLE,Example,Fund A,BUY,100,20.50\n"
    )
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if url == MONEYCONTROL:
            return Response(CATALOG)
        if url == HOLDINGS:
            return Response(HOLDING)
        if "nsearchives.nseindia.com" in url:
            return Response(csv_data)
        return Response(status=403)

    state = refresh_public_sources(
        owner.repo, provider=BigSharkPublicProvider(SimpleNamespace(get=get)), now=NOW
    )
    assert state["trades"]["coverage"] == "SINGLE_DAILY_REPORT"
    assert (
        state["trades"]["actual_start"] == state["trades"]["actual_end"] == "2026-11-19"
    )
    assert owner.repo.latest()["signals"][0]["disclosure_time"] is None
    assert owner.repo.latest()["signals"][0]["activity_signal"] == "BUY"
    assert not any("Fund A" in url or "EXAMPLE" in url for url in calls)


def test_nse_redirect_keeps_historical_request_on_official_current_origin():
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if url.startswith("https://www.nseindia.com/report-detail/"):
            return Response(
                status=302,
                headers={
                    "Location": "https://www.nseindia.in/report-detail/display-bulk-and-block-deals"
                },
            )
        if "/api/historicalOR/" in url:
            assert url.startswith("https://www.nseindia.in/")
            return Response(json.dumps([trade()]).encode())
        return Response(b"report")

    data = BigSharkPublicProvider(SimpleNamespace(get=get)).trades(
        source="NSE_BULK",
        start=NOW.date() - timedelta(days=6),
        end=NOW.date(),
        now=NOW,
    )
    assert len(data["rows"]) == 1 and data["coverage"] == "DISCLOSED_ONLY"


def test_public_availability_observation_contains_counts_without_investor_data():
    from scripts.check_big_shark_public_sources import observe

    report = observe(provider=Feed(), now=NOW)
    assert all(row["status"] == "available" for row in report["sources"].values())
    assert "Fund A" not in json.dumps(report) and "EXAMPLE" not in json.dumps(report)
    assert report["owner_data_used"] is False


def test_owner_refresh_and_feed_credential_cannot_read_or_control_sources(
    owner, monkeypatch
):
    key = "owner-public-source-test-" * 3
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", key)
    monkeypatch.setenv("TRENDFORGE_BIG_SHARK_FEED_KEY", "write-only-feed-test-" * 3)
    app = FastAPI()
    app.include_router(big_shark_router(public_provider_getter=Feed))
    with TestClient(app) as client:
        headers = {"X-TrendForge-Admin-Key": key}
        assert client.get("/institutional/big-shark/sources").status_code == 401
        assert (
            client.post(
                "/institutional/big-shark/sources/refresh",
                headers={"X-TrendForge-Feed-Key": "write-only-feed-test-" * 3},
                json={},
            ).status_code
            == 401
        )
        result = client.post(
            "/institutional/big-shark/sources/refresh", headers=headers, json={}
        )
        assert result.status_code == 200, result.text
        assert result.headers["cache-control"] == "private, no-store"
        assert result.json()["status"] == "refreshed"
        saved = client.put(
            "/institutional/big-shark/sources/config",
            headers=headers,
            json={"enabled": True},
        )
        assert saved.status_code == 200 and saved.json()["config"]["enabled"] is True
        assert (
            client.get("/institutional/big-shark", headers=headers).json()["signals"][
                0
            ]["activity_signal"]
            == "BUY"
        )
