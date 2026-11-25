"""Independent fill arithmetic, causal identities and atomic paper recovery."""

import copy
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from core.database import initialize_database
from database.database import Database
from database.repositories.trade_repository import TradeRepository
from scanner.strategy_registry import REGISTRY_VERSION
from services.evaluation_diagnostics import diagnostics
from services.execution_costs import VERSION, model
from services.paper_trade_audit import audit
from services.paper_trade_reports import PaperTradeReports
from services.paper_trading_runtime import PaperTradingRuntime
from services.paper_trading_service import PaperTradingService
from services.research_report import build_report
from services.strategy_provenance import identity

NOW = datetime(2026, 11, 25, 11, 30, tzinfo=ZoneInfo("Asia/Kolkata"))


def example_fill():
    # Entirely synthetic prices, independent of the execution-cost implementation.
    return {
        "symbol": "EXAMPLE",
        "side": "BUY",
        "quantity": 5,
        "entry_price": 1000.5,
        "exit_price": 979.51,
        "stoploss": 995.0,
        "exit_raw_price": 980.0,
        "pnl": -132.17006,
        "gross_pnl": -104.95,
        "transaction_costs": 27.22006,
        "delivery_charge": 15.34,
        "slippage_impact_estimate": 4.95,
        "cost_model_version": VERSION,
        "strategy_id": "example-saved-strategy",
        "created_at": "2026-11-20T10:00:00+05:30",
        "closed_at": "2026-11-23T15:30:44+05:30",
        "exit_reason": "STRATEGY_EXIT",
        "exit_signal": "EMA20_TRAILING_EXIT",
        "exit_signal_at": "2026-11-23T15:30:00+05:30",
        "paper_plan": {
            "strategy_id": "example-saved-strategy",
            "policy_version": "saved-rules-v1",
            "stop_is_resting_order": False,
            "strategy_provenance": {"registry_version": "saved-registry-v1"},
            "execution_economics": {"costs": model("swing"), "entry_raw_price": 1000.0},
        },
    }


def test_visible_stop_gap_is_explained_and_net_pnl_is_independently_reconciled():
    row = example_fill()
    original = copy.deepcopy(row)
    result = audit(row)
    assert result["status"] == "VERIFIED"
    assert result["computed_gross_pnl"] == pytest.approx(-104.95)
    assert result["computed_net_pnl"] == pytest.approx(-132.17006)
    assert result["adverse_distance_from_stop"] == pytest.approx(15.49)
    assert result["exit_code"] == "EMA20_TRAILING_EXIT"
    assert result["stop_basis"] == "conditional_reference"
    assert "EMA20 profit trail" in result["exit_explanation"]
    assert row == original


@pytest.mark.parametrize(
    "field,delta",
    [
        ("pnl", 1),
        ("exit_price", 1),
        ("transaction_costs", 1),
        ("slippage_impact_estimate", 1),
        ("delivery_charge", 1),
    ],
)
def test_inconsistent_saved_money_or_fill_never_passes_reconciliation(field, delta):
    row = example_fill()
    row[field] += delta
    result = audit(row)
    assert result["status"] == "MISMATCH"
    assert result["failures"]


def test_short_fill_and_target_price_clamp_are_reconciled_in_the_correct_direction():
    row = example_fill()
    row.update(
        side="SHORT",
        quantity=2,
        entry_price=99.95,
        exit_price=90,
        exit_raw_price=90,
        pnl=19.44412,
        gross_pnl=19.9,
        transaction_costs=0.45588,
        delivery_charge=0,
        slippage_impact_estimate=0.1,
        exit_reason="TARGET",
        exit_signal=None,
    )
    row["paper_plan"].update(target2=90, stop_is_resting_order=True)
    row["paper_plan"]["execution_economics"]["entry_raw_price"] = 100
    result = audit(row)
    assert result["status"] == "VERIFIED"
    assert result["computed_net_pnl"] == pytest.approx(19.44412)


def test_legacy_fill_is_visible_without_invented_fees_reason_or_versions():
    row = {
        "side": "BUY",
        "quantity": 2,
        "entry_price": 100,
        "exit_price": 110,
        "pnl": 20,
    }
    result = audit(row)
    assert result["status"] == "LIMITED_EVIDENCE"
    assert result["recorded_charges"] is None
    assert {"fee_and_slippage_basis", "exit_reason", "registry_version"} <= set(
        result["missing"]
    )
    assert result["strategy"]["registry_version"] == "unrecorded"
    assert "no recorded exit reason" in result["exit_explanation"]


def test_missing_old_registry_is_separate_from_reproducible_financial_arithmetic():
    row = example_fill()
    row["paper_plan"].pop("strategy_provenance")
    result = audit(row)
    assert result["status"] == "LIMITED_EVIDENCE"
    assert result["accounting_status"] == "VERIFIED"
    assert result["missing"] == ["registry_version"]


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "paper.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("TRENDFORGE_PRODUCTION_RUNTIME", "false")
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "false")
    initialize_database(str(path))
    db = Database(str(path))
    repo = TradeRepository(db)
    yield repo
    db.close()


@pytest.mark.parametrize("corrupt", ["fractional_quantity", "duplicate_symbol"])
def test_bad_later_saved_position_never_leaves_a_partially_restored_book(
    ledger, corrupt
):
    ledger.save("ABC", "BUY", 1, 100, stoploss=90, target=120, trade_mode="swing")
    ledger.save(
        "XYZ" if corrupt == "fractional_quantity" else "ABC",
        "BUY",
        1.5 if corrupt == "fractional_quantity" else 1,
        100,
        stoploss=90,
        target=120,
        trade_mode="swing",
    )
    runtime = PaperTradingRuntime(trades=ledger)
    paper = PaperTradingService(runtime, enabled=True, environment_kill_switch=False)
    with pytest.raises(RuntimeError, match="restoration is unavailable"):
        paper.restore_open()
    assert runtime.portfolio.positions == {}
    assert runtime._trade_ids == {}
    assert paper.health()["position_restore"]["status"] == "unavailable"
    assert paper.can_open_new_positions is False
    assert len(ledger.open_trades()) == 2


def test_restart_restores_monitorable_positions_without_enabling_entries(ledger):
    ledger.save(
        "ABC",
        "BUY",
        2,
        100,
        stoploss=90,
        target=120,
        trade_mode="swing",
        created_at=NOW.isoformat(),
    )
    paper = PaperTradingService(
        PaperTradingRuntime(trades=ledger), enabled=False, environment_kill_switch=True
    )
    assert paper.restore_open() == 1
    assert paper.restore_open() == 0  # Idempotent; no duplicate position.
    assert paper.health()["position_restore"]["open_trades"] == 1
    assert paper.can_open_new_positions is False
    closed = paper.monitor({"ABC": 89}, now=NOW)["closed"]
    assert len(closed) == 1
    report = PaperTradeReports(paper).statement(now=NOW)
    assert report["closed_trades"][0]["audit"]["exit_code"] == "STOPLOSS"
    assert report["portfolio"]["open_positions"] == 0
    assert paper.can_open_new_positions is False


def test_new_paper_rules_and_registry_identity_survive_restart_and_close(ledger):
    from tests.test_approved_horizon_strategies import pair

    key, context, _, row = pair(3)
    from scanner.approved_strategies import plan_for

    plan = plan_for(key, row, context)
    runtime = PaperTradingRuntime(trades=ledger)
    runtime.open(
        SimpleNamespace(
            symbol="ABC",
            side="BUY",
            price=plan["entry"],
            quantity=1,
            stoploss=plan["stoploss"],
            target2=0,
            trade_mode="swing",
            strategy_id=key,
            paper_plan=plan,
        ),
        now=NOW,
    )
    recovered = PaperTradingRuntime(trades=ledger)
    assert recovered.restore_open() == 1
    recovered.close_strategy_exit(
        "ABC",
        109,
        exit_signal="EMA20_TRAILING_EXIT",
        exit_signal_at=NOW.isoformat(),
        now=NOW,
    )
    stored = dict(ledger.closed_trades()[0])
    assert identity(stored)["registry_version"] == REGISTRY_VERSION
    assert identity(stored)["policy_version"] == plan["policy_version"]
    assert (
        json.loads(stored["paper_plan_json"])["strategy_provenance"]["registry_version"]
        == REGISTRY_VERSION
    )


@pytest.mark.parametrize(
    "code",
    [
        "KITE_AUTH_REQUIRED",
        "DATA_RATE_LIMITED",
        "SYMBOL_NOT_RESOLVED",
        "DAILY_WARMUP_NOT_READY",
        "ANNUAL_REFERENCE_MISSING",
        "CANDLES_STALE",
        None,
    ],
)
def test_unavailable_components_have_specific_safe_reasons(code):
    evidence = diagnostics(
        {
            "data_status": "UNAVAILABLE",
            "data_code": code,
            "error": "PRIVATE_UPSTREAM_BODY",
        }
    )
    assert all(item["code"] and item["reason"] for item in evidence)
    assert all(item["status"] == "UNAVAILABLE" for item in evidence)
    assert "PRIVATE_UPSTREAM_BODY" not in json.dumps(evidence)


def test_scan_and_export_share_recorded_versions_without_upgrading_old_evidence():
    result = {
        "run_id": "example",
        "registry_version": "saved-registry",
        "exit_policy_version": "saved-rules",
        "results": [
            {
                "symbol": "ABC",
                "signal": "WAIT",
                "data_status": "UNAVAILABLE",
                "data_code": "KITE_AUTH_REQUIRED",
            }
        ],
    }
    report = build_report(result, kind="scan")
    assert identity(report)["registry_version"] == "saved-registry"
    assert identity(report)["policy_version"] == "saved-rules"
    assert identity(report["rows"][0]) == identity(report)
    assert (
        json.loads(report["rows"][0]["evaluation_diagnostics"])[0]["code"]
        == "KITE_AUTH_REQUIRED"
    )
    assert "saved-registry" in report["csv"]
    assert identity({})["registry_version"] == "unrecorded"


def test_unavailable_report_explains_components_without_leaking_source_errors():
    from services.stock_report_service import StockReportService

    def unavailable():
        raise RuntimeError("PRIVATE_SOURCE_DETAIL")

    report = StockReportService(
        unavailable,
        company_provider=SimpleNamespace(
            get=lambda *a, **k: {"status": "unavailable", "metrics": {}}
        ),
    ).build("EXAMPLE", now=NOW)
    diagnostics = report["evaluation_diagnostics"]
    assert {row["component"] for row in diagnostics} == {
        "Technical data",
        "Combined rating",
        "LTP",
        "Company data",
        "News",
    }
    assert all(row["reason"] and row["code"] for row in diagnostics)
    assert all(row["status"] == "UNAVAILABLE" for row in diagnostics)
    assert "PRIVATE_SOURCE_DETAIL" not in json.dumps(report)
    assert report["strategy_provenance"]["policy_version"] == "unrecorded"
    assert report["trade_plan"]["execution_enabled"] is False


def test_backtest_ui_returns_saved_version_identity_without_large_workbook(ledger):
    from database.repositories.research_batches import ResearchBatchRepository
    from services.scanner_workflow import ScannerWorkflow
    from services.scanner_workflow_export import backtest_view
    from tests.test_scanner_workflow import STRATEGY, backtest

    repository = ResearchBatchRepository(ledger.db)
    workflow = ScannerWorkflow(repository)
    batch = backtest(
        repository,
        "versioned-backtest",
        {
            "strategy_id": STRATEGY,
            "horizon": "short_term",
            "stock_list": "NIFTY 50",
            "symbols": ["EXAMPLE"],
        },
    )
    report = batch["report"]
    report.update(
        registry_version="saved-old-registry", exit_policy_version="saved-old-rules"
    )
    ledger.db.execute(
        "UPDATE research_batches SET report_json=? WHERE batch_id=?",
        (json.dumps(report), batch["batch_id"]),
    )
    ledger.db.execute(
        "INSERT INTO scanner_backtest_jobs VALUES(?,?,?,?,?,'completed',?,NULL)",
        ("job", STRATEGY, "short_term", "2y", NOW.isoformat(), batch["batch_id"]),
    )
    result = backtest_view(workflow)
    assert (
        result["jobs"][0]["strategy_provenance"]["registry_version"]
        == "saved-old-registry"
    )
    assert (
        result["jobs"][0]["strategy_provenance"]["policy_version"] == "saved-old-rules"
    )
    assert "xlsx_base64" not in json.dumps(result)
