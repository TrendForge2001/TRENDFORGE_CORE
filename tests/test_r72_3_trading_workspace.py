from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.trading_workspace_router import attach_trading_workspace_routes
from services.technical_auto_scanner import TechnicalAutoScanner
from webapp.navigation import NAVIGATION_SPEC


class FakeUniverse:
    def load(self, index_name, *, force_refresh=False):
        assert index_name == "NIFTY 500"
        return {
            "members": [
                {"symbol": f"S{i:03d}"}
                for i in range(500)
            ]
        }


class FakeTechnical:
    def __init__(self):
        self.calls = []

    def scan(
        self,
        *,
        symbols,
        mode,
        top_n,
        execute_paper,
        run_id,
    ):
        self.calls.append(
            {
                "symbols": list(symbols),
                "mode": mode,
                "execute_paper": execute_paper,
                "run_id": run_id,
            }
        )
        first = symbols[0]
        pick = {
            "symbol": first,
            "mode": mode,
            "signal": "BUY",
            "score": 95.0,
            "confidence": 80.0,
            "trigger": "TEST",
            "execution_eligible": True,
            "entry": 100.0,
            "stoploss": 95.0,
            "target2": 110.0,
            "reward_risk": 2.0,
        }
        return {
            "results": [pick],
            "top_picks": [pick],
        }


class FakeAutoEntry:
    def __init__(self):
        self.calls = []

    def process_scan(self, payload, **kwargs):
        self.calls.append((payload, kwargs))
        return {
            "status": "executed",
            "opened_count": 1,
            "opened": [{"symbol": payload["top_picks"][0]["symbol"]}],
            "broker_orders_allowed": False,
        }


class FakePaper:
    def snapshot(self):
        return {
            "open_positions": 1,
            "positions": [{"symbol": "RELIANCE"}],
            "unrealized_pnl": 100.0,
            "realized_pnl": 50.0,
            "total_pnl": 150.0,
        }

    runtime = SimpleNamespace(
        trades=SimpleNamespace(
            closed_trades=lambda: [
                {"symbol": "TCS", "pnl": 50.0, "status": "CLOSED"}
            ]
        )
    )


def test_navigation_is_reduced_to_requested_workspace():
    assert list(NAVIGATION_SPEC) == [
        "Watchlist",
        "Portfolio",
        "Fundamentals",
        "Technicals",
        "Corporate Actions",
    ]
    paths = [
        spec.path
        for group in NAVIGATION_SPEC.values()
        for spec in group
    ]
    assert "pages/watchlists.py" in paths
    assert "pages/portfolio_workspace.py" in paths
    assert "pages/technical_workspace.py" in paths
    assert "pages/dashboard.py" not in paths
    assert "pages/scanner.py" not in paths


def test_nifty500_auto_scanner_batches_then_paper_ranks_globally():
    technical = FakeTechnical()
    auto = FakeAutoEntry()
    runner = TechnicalAutoScanner(
        technical_service=technical,
        paper_auto_entry=auto,
        universe_provider=FakeUniverse(),
    )
    runner.chunk_size = 100
    runner.top_n = 20

    result = runner.run_once("intraday", execute_paper=True)

    assert result["status"] == "completed"
    assert result["requested_symbols"] == 500
    assert len(technical.calls) == 5
    assert all(call["execute_paper"] is False for call in technical.calls)
    assert len(auto.calls) == 1
    payload, kwargs = auto.calls[0]
    assert len(payload["top_picks"]) == 5
    assert kwargs["execute_requested"] is True
    assert result["safety"]["broker_orders_allowed"] is False
    assert result["safety"]["fundamentals_used"] is False


def test_workspace_paper_portfolio_is_separate_and_read_only():
    app = FastAPI()
    attach_trading_workspace_routes(
        app,
        intelligence_getter=lambda: None,
        paper_getter=lambda: FakePaper(),
    )
    client = TestClient(app)

    response = client.get("/workspace/paper-portfolio")

    assert response.status_code == 200
    payload = response.json()
    assert payload["portfolio"]["open_positions"] == 1
    assert payload["closed_trades"][0]["symbol"] == "TCS"
    assert payload["safety"]["paper_only"] is True
    assert payload["safety"]["broker_orders_allowed"] is False
