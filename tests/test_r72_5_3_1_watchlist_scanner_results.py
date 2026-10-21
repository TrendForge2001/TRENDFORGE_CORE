from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app import create_app
from api.trading_workspace_router import attach_trading_workspace_routes
from providers.nse_broad_market_constituents import (
    NSEBroadMarketConstituentProvider,
)
from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner
from services.trading_workspace_service import TradingWorkspaceService
from webapp.navigation import NAVIGATION_SPEC


class FakeUniverse:
    def load(self, name):
        assert name == "NIFTY 100"
        return {
            "index": name,
            "source": "NSE_NIFTY100_CSV",
            "count": 2,
            "fetched_at": "2026-10-20T09:30:00Z",
            "members": [
                {"symbol": "RELIANCE", "name": "Reliance Industries"},
                {"symbol": "TCS", "name": "Tata Consultancy Services"},
            ],
        }


class FailingQuoteProvider:
    def safe_quote(self, instruments):
        raise RuntimeError("Kite session expired")


class FakeProviderFactory:
    def quote(self):
        return FailingQuoteProvider()


def _workspace():
    return TradingWorkspaceService(
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        universe_provider=FakeUniverse(),
        provider_factory=FakeProviderFactory(),
    )


def test_watchlist_constituents_do_not_require_kite_token():
    service = _workspace()
    payload = service.constituents("NIFTY100")
    assert payload["count"] == 2
    assert [row["symbol"] for row in payload["rows"]] == ["RELIANCE", "TCS"]
    assert payload["rows"][0]["stock_name"] == "Reliance Industries"


def test_watchlist_retains_members_when_quote_provider_fails():
    service = _workspace()
    payload = service.watchlist("NIFTY 100")
    assert payload["count"] == 2
    assert payload["status"] == "degraded"
    assert payload["quote_status"] == "unavailable"
    assert "Kite session expired" in payload["quote_error"]
    assert all(row["ltp"] is None for row in payload["rows"])
    assert all(row["day_change_rs"] is None for row in payload["rows"])
    assert all(row["day_change_pct"] is None for row in payload["rows"])


def test_watchlist_constituent_endpoint_is_read_only_and_stable(monkeypatch):
    app = FastAPI()
    attach_trading_workspace_routes(
        app,
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        provider_factory=FakeProviderFactory(),
    )
    from services import trading_workspace_service
    monkeypatch.setattr(
        trading_workspace_service.NSEBroadMarketConstituentProvider,
        "load",
        lambda self, name: FakeUniverse().load(name),
    )
    client = TestClient(app)
    response = client.get("/workspace/watchlist/NIFTY%20100/constituents")
    assert response.status_code == 200
    assert response.json()["count"] == 2


class NeverMarket:
    def batch_candles_with_errors(self, *args, **kwargs):
        raise AssertionError("Reading scanner results must never fetch candles")


def test_scanner_results_snapshot_loads_without_running_scan(tmp_path, monkeypatch):
    path = tmp_path / "last_result.json"
    monkeypatch.setenv("TRENDFORGE_MULTI_STRATEGY_RESULTS_PATH", str(path))
    scanner = MultiStrategyNiftyScanner(market_data=NeverMarket())
    assert scanner.results()["status"] == "not_started"
    payload = {
        "run_id": "historical-test",
        "results": [{"symbol": "TCS", "consensus": "NEUTRAL"}],
        "strategy_summary": [{"strategy_id": "test", "buy": 0}],
        "top_picks": [],
        "candidate_symbols": 0,
        "completed_symbols": 1,
    }
    scanner._store_snapshot(payload)

    reloaded = MultiStrategyNiftyScanner(market_data=NeverMarket())
    results = reloaded.results()
    assert results["status"] == "available"
    assert results["source"] == "instance_snapshot"
    assert results["last_result"]["candidate_symbols"] == 0
    assert results["safety"]["paper_execution_allowed"] is False


def test_scanner_result_api_does_not_trigger_work():
    class FakeScanner:
        def results(self):
            return {
                "status": "available",
                "last_result": {
                    "results": [{"symbol": "SBIN", "consensus": "WATCH"}],
                    "top_picks": [],
                },
            }

        def trigger(self, **kwargs):
            raise AssertionError("GET must never start a scanner")

    class Factory:
        def multi_strategy_scanner_service(self):
            return FakeScanner()

    client = TestClient(create_app(Factory()))
    response = client.get("/technical/multi-strategy/results")
    assert response.status_code == 200
    assert response.json()["last_result"]["results"][0]["symbol"] == "SBIN"


def test_navigation_has_dedicated_scanner_results_under_technicals():
    assert list(NAVIGATION_SPEC) == [
        "Watchlist", "Portfolio", "Fundamentals", "Technicals", "Corporate Actions"
    ]
    paths = [spec.path for spec in NAVIGATION_SPEC["Technicals"]]
    assert "pages/technical_workspace.py" in paths
    from webapp.workspace_tabs import WORKSPACE_TABS
    assert ("Scanner & Backtesting", "technicals.py") in WORKSPACE_TABS["technicals"]
    assert ("Scanner Results", "scanner_results.py") in WORKSPACE_TABS["technicals"]
    page = Path("webapp/pages/scanner_results.py").read_text(encoding="utf-8")
    assert '/technical/multi-strategy/results' in page
    assert 'post_json(' not in page
    assert 'trigger(' not in page


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.headers = {"content-type": "text/csv"}

    def raise_for_status(self):
        pass


class OfficialSession:
    def __init__(self, csv_text):
        self.csv_text = csv_text
        self.headers = {}
        self.urls = []
        self.fail = False

    def get(self, url, **kwargs):
        self.urls.append(url)
        if self.fail:
            raise RuntimeError("NSE temporarily blocked cloud instance")
        if "nsearchives" in url:
            raise RuntimeError("archive unavailable")
        return FakeResponse(self.csv_text)


class AlwaysFailSession:
    def __init__(self):
        self.headers = {}
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        raise RuntimeError("NSE cloud access blocked")


def test_packaged_nifty100_fallback_keeps_watchlist_and_scanner_universe_ready(tmp_path):
    session = AlwaysFailSession()
    provider = NSEBroadMarketConstituentProvider(
        session=session,
        cache_ttl=0,
        cache_dir=tmp_path,
    )

    data = provider.load("NIFTY 100", force_refresh=True)
    assert data["count"] == 100
    assert data["security_count"] == 100
    assert data["stale"] is True
    assert data["snapshot_storage"] == "package"
    assert data["snapshot_as_of"] == "2026-10-14"
    assert data["source"] == "NSE_NIFTY100_CSV"
    assert "Live NSE refresh unavailable" in data["source_warning"]
    symbols = [row["symbol"] for row in data["members"]]
    assert len(symbols) == len(set(symbols)) == 100
    assert {"RELIANCE", "TCS", "SBIN"}.issubset(symbols)
    assert len(session.urls) == 2

    workspace = TradingWorkspaceService(
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        universe_provider=provider,
        provider_factory=FakeProviderFactory(),
    )
    watch = workspace.constituents("NIFTY 100")
    assert watch["count"] == 100
    assert watch["snapshot_storage"] == "package"
    assert watch["snapshot_as_of"] == "2026-10-14"

    scanner = MultiStrategyNiftyScanner(
        market_data=NeverMarket(),
        universe_provider=provider,
    )
    name, scanner_symbols, metadata = scanner._universe(
        "NIFTY 100",
        limit=5,
        force_refresh=True,
    )
    assert name == "NIFTY 100"
    assert len(scanner_symbols) == 5
    assert metadata["snapshot_storage"] == "package"


def test_scanner_pages_make_zero_candidate_results_visible():
    technicals = Path("webapp/pages/technicals.py").read_text(encoding="utf-8")
    results = Path("webapp/pages/scanner_results.py").read_text(encoding="utf-8")
    assert "no BUY / STRONG_BUY candidates" in technicals
    assert "All evaluated stocks" in results
    assert "/technical/multi-strategy/readiness" in results


def test_official_nse_secondary_url_and_stale_cache(tmp_path):
    csv_text = "Company Name,Industry,Symbol\\n" + "".join(
        f"Company {i},Industry,S{i:03d}\\n" for i in range(100)
    )
    # CSV template intentionally uses explicit newlines.
    csv_text = csv_text.replace("\\n", "\n")
    session = OfficialSession(csv_text)
    provider = NSEBroadMarketConstituentProvider(
        session=session, cache_ttl=0, cache_dir=tmp_path,
    )
    data = provider.load("NIFTY 100")
    assert data["count"] == 100
    assert "niftyindices.com" in data["source_url"]
    assert len(session.urls) == 2

    session.fail = True
    stale = provider.load("NIFTY 100", force_refresh=True)
    assert stale["count"] == 100
    assert stale["stale"] is True
    assert "source_warning" in stale

    another = NSEBroadMarketConstituentProvider(
        session=session, cache_ttl=0, cache_dir=tmp_path,
    )
    stored = another.load("NIFTY 100", force_refresh=True)
    assert stored["count"] == 100
    assert stored["stale"] is True
    assert stored["source"] == "NSE_NIFTY100_CSV"
