"""Safe persisted errors and explicit at-most-once historical retry."""

import json
import os
from types import SimpleNamespace

from database.repositories.research_batches import ResearchBatchRepository
from providers.market_data_provider import ProviderAuthenticationError
from services.research_batches import ResearchBatchManager
from services.research_failure import failure_diagnostic
from services.research_retry import request_research_retry
from tests import test_research_batches as support

technical = support.technical


def test_diagnostic_never_includes_exception_messages_or_locals():
    private_fixture = "private-token-and-account-body"
    try:
        raise KeyError(private_fixture)
    except KeyError as error:
        diagnostic = failure_diagnostic(error, "simulation")
    assert private_fixture not in json.dumps(diagnostic)
    assert diagnostic["error_type"] == "KeyError"
    assert diagnostic["frames"][-1]["file"].endswith(
        "test_research_failure_diagnostics.py"
    )
    assert diagnostic["phase"] == "simulation"
    assert len(diagnostic["reference"]) == 12


def test_factory_failure_is_saved_with_auth_action_not_generic_failure(
    technical, monkeypatch
):
    from services.research_worker import main

    monkeypatch.setattr(os, "nice", lambda value: 0, raising=False)

    repository = ResearchBatchRepository(technical.repository.db)
    request = support.request()
    repository.create("batch-test-auth", "backtest", request)
    repository.start("batch-test-auth")
    monkeypatch.setattr(
        "sys.argv",
        [
            "research-worker",
            "--database",
            str(technical.repository.db.db_path),
            "--batch-id",
            "batch-test-auth",
            "--parent-pid",
            str(os.getppid()),
        ],
    )

    def denied(database):
        raise ProviderAuthenticationError("secret-provider-body")

    assert main(denied) == 1
    failed = repository.get("batch-test-auth")
    assert failed["error_code"] == "research_kite_authentication_failed"
    assert failed["diagnostic"]["phase"] == "starting"
    assert "secret-provider-body" not in json.dumps(failed)
    import logging

    logging.disable(logging.NOTSET)


def test_isolated_programming_failure_keeps_safe_phase_and_reference(
    technical, monkeypatch
):
    monkeypatch.setattr(
        "services.research_execution.execute_research",
        lambda *args: (_ for _ in ()).throw(KeyError("PRIVATE")),
    )
    manager = ResearchBatchManager(technical, import_history=False, isolated=False)
    try:
        batch = manager.submit("backtest", support.request())
        manager.futures[batch["batch_id"]].result(timeout=15)
        failed = manager.repository.get(batch["batch_id"])
        assert failed["status"] == "failed"
        assert failed["diagnostic"]["error_type"] == "KeyError"
        assert "PRIVATE" not in json.dumps(failed)
    finally:
        manager.close(wait=True)


def test_explicit_failed_weekly_retry_is_consumed_once_across_restarts(
    technical, monkeypatch
):
    from scanner.weekly_floor import STRATEGY_ID
    from tests.support.weekly_floor_candles import NOW, ExampleMarket

    technical.market_data = ExampleMarket()
    monkeypatch.setattr(
        "services.weekly_account_research.local_now", lambda now=None: NOW
    )
    monkeypatch.setattr(
        "services.weekly_floor_research.local_now", lambda now=None: NOW
    )
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-db1tb7jncjis73c994e0")
    manager = ResearchBatchManager(technical, import_history=False, isolated=False)
    previous = support.request(
        symbols=["EXAMPLE"], horizon="long_term", strategy_id=STRATEGY_ID, period="2y"
    )
    manager.repository.create("batch-" + "a" * 32, "backtest", previous)
    manager.repository.fail("batch-" + "a" * 32, "research_batch_failed")
    intent = {
        "request_id": "repair-test-1",
        "source_batch_id": "latest_failed_weekly_nifty100",
    }
    # The fixture stock list must match the narrowly scoped production selector.
    manager.repository.db.execute("UPDATE research_batches SET stock_list='NIFTY 100'")
    monkeypatch.setenv("TRENDFORGE_RESEARCH_RETRY", json.dumps(intent))
    app = SimpleNamespace(
        state=SimpleNamespace(research_manager_getter=lambda: manager)
    )
    try:
        retry = request_research_retry(app)
        assert retry
        manager.futures[retry].result(timeout=45)
        assert manager.repository.get(retry)["status"] == "completed"
        assert (
            manager.repository.get(retry)["request"]["retry_of"] == "batch-" + "a" * 32
        )
        assert request_research_retry(app) is None
        assert len(manager.futures) == 1
    finally:
        manager.close(wait=True)


def test_retry_requires_operator_intent_and_exact_render_service(
    technical, monkeypatch
):
    monkeypatch.setenv(
        "TRENDFORGE_RESEARCH_RETRY",
        '{"request_id":"x","source_batch_id":"latest_failed_weekly_nifty100"}',
    )
    monkeypatch.setenv("RENDER_SERVICE_ID", "different-service")
    assert request_research_retry(None) is None
