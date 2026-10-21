from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.admin_auth import require_admin_api_key
from api.app import create_app
from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner
from services.strategy_driven_paper_service import StrategyDrivenPaperService


STRATEGY_ID = "tpl_supertrend_rsi"
SCAN_RUN_ID = "r7252-scan"
VALIDATION_RUN_ID = "r7253-validation"


class FakeScanner:
    def __init__(self, *, mode="swing", status="completed"):
        self.mode = mode
        self.status_name = status

    def results(self):
        risk = {
            "entry": 100.0,
            "stoploss": 95.0,
            "target2": 110.0,
            "reward_risk": 2.0,
        }
        return {
            "status": "available",
            "scanner_status": "completed",
            "source": "latest_run",
            "last_result": {
                "status": self.status_name,
                "run_id": SCAN_RUN_ID,
                "universe": "NIFTY 100",
                "mode": self.mode,
                "requested_symbols": 100,
                "completed_symbols": 100,
                "error_symbols": 0,
                "candidate_symbols": 1,
                "top_picks": [
                    {
                        "symbol": "TCS",
                        "consensus": "BUY",
                        "consensus_score": 82.5,
                        "buy_strategy_ids": [STRATEGY_ID],
                        "strategy_evaluations": [
                            {
                                "strategy_id": STRATEGY_ID,
                                "name": "Template · Supertrend + RSI",
                                "source": "template",
                                "status": "evaluated",
                                "signal": "BUY",
                                "score": 100.0,
                                "paper_eligible": True,
                                "risk": risk,
                            }
                        ],
                    }
                ],
            },
        }


class FakeAutoEntry:
    def __init__(self, *, enabled=True, paper_ready=True):
        self.calls = []
        self.paper_service = SimpleNamespace(
            can_open_new_positions=paper_ready,
        )
        self.enabled = enabled

    def health(self):
        return {
            "status": "ready" if self.enabled else "disabled",
            "enabled": self.enabled,
            "paper_only": True,
            "broker_orders_allowed": False,
        }

    def evaluate_candidate(self, candidate, now=None):
        signal = candidate["signal"]
        approved = bool(
            candidate.get("execution_eligible")
            and float(signal.get("overall_score") or 0) >= 90
            and float(signal.get("confidence") or 0) >= 60
            and float(signal.get("entry") or 0) > float(signal.get("stoploss") or 0) > 0
            and float(signal.get("target2") or 0) > float(signal.get("entry") or 0)
        )
        return {
            "approved": approved,
            "reasons": [] if approved else ["risk_gate"],
            "quantity": 10 if approved else 0,
        }

    def process_scan(
        self,
        scan_result,
        *,
        run_id,
        execute_requested,
        continuation=False,
        now=None,
    ):
        self.calls.append(
            {
                "scan_result": scan_result,
                "run_id": run_id,
                "execute_requested": execute_requested,
                "continuation": continuation,
            }
        )
        return {
            "status": "executed",
            "opened_count": 1,
            "opened": [{"symbol": "TCS", "trade_id": 77}],
            "evaluations": [],
            "broker_orders_allowed": False,
        }


def validation_status(*, mode="swing", promotion="ELIGIBLE_FOR_REVIEW"):
    return {
        "status": "completed",
        "run_id": VALIDATION_RUN_ID,
        "strategy_validation": [
            {
                "strategy_id": STRATEGY_ID,
                "strategy_name": "Template · Supertrend + RSI",
                "mode": mode,
                "source": "template",
                "registry_paper_eligible": True,
                "promotion_status": promotion,
                "universe_gates": [
                    {"universe": "NIFTY 100", "status": "PASS"},
                ],
            }
        ],
    }


def test_r7254_preview_requires_validated_strategy_and_r672_gate():
    auto = FakeAutoEntry()
    service = StrategyDrivenPaperService(
        scanner_service=FakeScanner(),
        paper_auto_entry=auto,
    )

    preview = service.preview(
        strategy_id=STRATEGY_ID,
        scan_run_id=SCAN_RUN_ID,
        validation_run_id=VALIDATION_RUN_ID,
        validation_status=validation_status(),
        now=datetime(2026, 10, 21, 10, 0),
    )

    assert preview["status"] == "ready"
    assert preview["candidate_count"] == 1
    assert preview["r67_2_approved_count"] == 1
    assert preview["candidates"][0]["strategy_score"] == 100.0
    assert preview["candidates"][0]["consensus_score"] == 82.5
    assert preview["candidates"][0]["entry"] == 100.0
    assert preview["safety"]["broker_orders_allowed"] is False
    assert auto.calls == []


def test_r7254_execute_delegates_to_canonical_auto_entry_once():
    auto = FakeAutoEntry()
    service = StrategyDrivenPaperService(
        scanner_service=FakeScanner(),
        paper_auto_entry=auto,
    )

    result = service.execute(
        strategy_id=STRATEGY_ID,
        scan_run_id=SCAN_RUN_ID,
        validation_run_id=VALIDATION_RUN_ID,
        validation_status=validation_status(),
        now=datetime(2026, 10, 21, 10, 0),
    )

    assert result["status"] == "executed"
    assert result["paper_result"]["opened_count"] == 1
    assert result["safety"]["broker_orders_created"] == 0
    assert len(auto.calls) == 1
    call = auto.calls[0]
    assert call["execute_requested"] is True
    assert call["continuation"] is False
    assert call["scan_result"]["outcome"] == "completed"
    adapted = call["scan_result"]["top_picks"][0]
    assert adapted["strategy_id"] == STRATEGY_ID
    assert adapted["technical_mode"] == "swing"
    assert adapted["execution_eligible"] is True
    assert adapted["signal"]["overall_score"] == 100.0
    assert adapted["signal"]["confidence"] == 82.5

    duplicate = service.execute(
        strategy_id=STRATEGY_ID,
        scan_run_id=SCAN_RUN_ID,
        validation_run_id=VALIDATION_RUN_ID,
        validation_status=validation_status(),
        now=datetime(2026, 10, 21, 10, 1),
    )
    assert duplicate["status"] == "blocked"
    assert "execution_already_requested_for_lineage" in duplicate["blockers"]
    assert len(auto.calls) == 1


def test_r7254_fails_closed_for_unvalidated_or_unsupported_mode():
    unvalidated = StrategyDrivenPaperService(
        scanner_service=FakeScanner(),
        paper_auto_entry=FakeAutoEntry(),
    ).preview(
        strategy_id=STRATEGY_ID,
        scan_run_id=SCAN_RUN_ID,
        validation_run_id=VALIDATION_RUN_ID,
        validation_status=validation_status(promotion="NOT_ELIGIBLE"),
    )
    assert unvalidated["status"] == "blocked"
    assert "strategy_not_validation_eligible" in unvalidated["blockers"]

    positional = StrategyDrivenPaperService(
        scanner_service=FakeScanner(mode="positional"),
        paper_auto_entry=FakeAutoEntry(),
    ).preview(
        strategy_id=STRATEGY_ID,
        scan_run_id=SCAN_RUN_ID,
        validation_run_id=VALIDATION_RUN_ID,
        validation_status=validation_status(mode="positional"),
    )
    assert positional["status"] == "blocked"
    assert "paper_mode_not_supported" in positional["blockers"]


def test_r7254_fails_closed_when_r672_or_paper_runtime_is_disabled():
    disabled = StrategyDrivenPaperService(
        scanner_service=FakeScanner(),
        paper_auto_entry=FakeAutoEntry(enabled=False),
    ).preview(
        strategy_id=STRATEGY_ID,
        scan_run_id=SCAN_RUN_ID,
        validation_run_id=VALIDATION_RUN_ID,
        validation_status=validation_status(),
    )
    assert "r67_2_auto_entry_disabled" in disabled["blockers"]

    locked = StrategyDrivenPaperService(
        scanner_service=FakeScanner(),
        paper_auto_entry=FakeAutoEntry(paper_ready=False),
    ).preview(
        strategy_id=STRATEGY_ID,
        scan_run_id=SCAN_RUN_ID,
        validation_run_id=VALIDATION_RUN_ID,
        validation_status=validation_status(),
    )
    assert "paper_trading_not_ready" in locked["blockers"]


def test_multi_strategy_scan_retains_per_strategy_risk_for_paper_lineage():
    compact = MultiStrategyNiftyScanner._compact_evaluation(
        {
            "strategy_id": STRATEGY_ID,
            "name": "Template · Supertrend + RSI",
            "source": "template",
            "family": "trend",
            "status": "evaluated",
            "signal": "BUY",
            "score": 100.0,
            "paper_eligible": True,
            "risk": {
                "entry": 100.0,
                "stoploss": 95.0,
                "target2": 110.0,
            },
        }
    )
    assert compact["paper_eligible"] is True
    assert compact["risk"]["entry"] == 100.0
    assert compact["risk"]["stoploss"] == 95.0


class FakeStrategyPaperApi:
    def __init__(self):
        self.preview_calls = []
        self.execute_calls = []

    def readiness(self, *, validation_status=None):
        return {
            "status": "ready",
            "version": "R72.5.4-v1",
            "validation_status": (validation_status or {}).get("status"),
            "safety": {"broker_orders_allowed": False},
        }

    def preview(self, **kwargs):
        self.preview_calls.append(kwargs)
        return {
            "status": "ready",
            "version": "R72.5.4-v1",
            "strategy_id": kwargs["strategy_id"],
            "safety": {"broker_orders_allowed": False},
        }

    def execute(self, **kwargs):
        self.execute_calls.append(kwargs)
        return {
            "status": "executed",
            "version": "R72.5.4-v1",
            "strategy_id": kwargs["strategy_id"],
            "paper_result": {"opened_count": 1},
            "safety": {"broker_orders_allowed": False},
        }


class ApiFactory:
    def __init__(self):
        self.paper = FakeStrategyPaperApi()

    def strategy_driven_paper_service(self):
        return self.paper


def _api_client():
    factory = ApiFactory()
    app = create_app(factory)
    app.dependency_overrides[require_admin_api_key] = lambda: True
    app.state.r7253_validation = validation_status()
    return TestClient(app), factory


def test_r7254_api_readiness_preview_and_execute_use_validation_lineage():
    client, factory = _api_client()

    readiness = client.get("/paper/strategy-driven/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["version"] == "R72.5.4-v1"
    assert readiness.json()["validation_status"] == "completed"

    request = {
        "strategy_id": STRATEGY_ID.upper(),
        "scan_run_id": SCAN_RUN_ID,
        "validation_run_id": VALIDATION_RUN_ID,
    }
    preview = client.post(
        "/paper/strategy-driven/preview",
        json=request,
    )
    execute = client.post(
        "/paper/strategy-driven/execute",
        json=request,
    )

    assert preview.status_code == 200
    assert execute.status_code == 200
    assert factory.paper.preview_calls[0]["strategy_id"] == STRATEGY_ID
    assert factory.paper.preview_calls[0]["validation_status"]["status"] == "completed"
    assert factory.paper.execute_calls[0]["validation_status"]["run_id"] == VALIDATION_RUN_ID
    assert execute.json()["safety"]["broker_orders_allowed"] is False
