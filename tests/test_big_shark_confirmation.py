"""Independent evidence, completed candles and guarded matching confirmation."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from services.big_shark_activity import activity_view, import_records
from services.big_shark_confirmation import evaluate_daily, refresh_confirmations
from services.big_shark_portfolio import read_portfolio
from tests.test_big_shark_activity import NOW, trade
from tests.test_big_shark_portfolio import workbook
from tests.test_vwma_yearly_research import execution_frame, history


def test_fresh_daily_buy_and_separate_sell_rule(monkeypatch):
    frame = execution_frame().iloc[:2].copy()
    monkeypatch.setattr(
        "services.big_shark_confirmation.prepare_daily", lambda *a, **kw: frame
    )
    now = datetime(2026, 3, 3, 12, tzinfo=UTC)
    assert evaluate_daily(frame, now=now)["price_signal"] == "BUY"
    frame.loc[frame.index[-1], "RSI_WILDER_14"] = 49
    frame.loc[frame.index[-1], "close"] = 90
    assert evaluate_daily(frame, now=now)["price_signal"] == "SELL_EXIT"
    assert evaluate_daily(frame, now=NOW)["price_signal"] == "STALE_DATA"


@pytest.mark.parametrize(
    "column,value", [("RSI_WILDER_14", 76), ("volume", 1600), ("VWMA_20", 105)]
)
def test_failed_daily_buy_check_stays_wait(monkeypatch, column, value):
    frame = execution_frame().iloc[:2].copy()
    frame.loc[frame.index[-1], column] = value
    monkeypatch.setattr(
        "services.big_shark_confirmation.prepare_daily", lambda *a, **kw: frame
    )
    assert (
        evaluate_daily(frame, now=datetime(2026, 3, 3, 12, tzinfo=UTC))["price_signal"]
        == "WAIT"
    )


def test_real_history_excludes_partial_and_future_bars():
    raw = history()
    now = pd.Timestamp("2026-11-13T14:00:00+05:30").to_pydatetime()
    result = evaluate_daily(raw, now=now)
    assert result["bar_closed_at"].startswith("2026-11-12")
    raw.loc[pd.Timestamp("2026-11-16", tz="Asia/Kolkata")] = [
        900,
        950,
        890,
        920,
        100000,
    ]
    assert evaluate_daily(raw, now=now) == result


def test_old_confirmation_is_marked_stale_without_fetching_candles():
    snapshot = read_portfolio(workbook())
    snapshot["signals"][0].update(
        {
            "technical_confirmation": "BUY_CONFIRMED",
            "technical_evidence": {"bar_closed_at": "2026-11-12T15:30:00+05:30"},
        }
    )
    assert (
        activity_view(snapshot, now=NOW)["signals"][0]["technical_confirmation"]
        == "STALE_DATA"
    )
    assert snapshot["signals"][0]["technical_confirmation"] == "BUY_CONFIRMED"


def test_activity_disagreement_no_data_and_provider_failure_never_confirm(monkeypatch):
    snapshot = import_records(
        read_portfolio(workbook()),
        [trade()],
        source="NSE_BULK",
        metric="quantity",
        now=NOW,
    )
    calls = []
    provider = SimpleNamespace(candles=lambda symbol, **kw: calls.append((symbol, kw)))
    monkeypatch.setattr(
        "services.big_shark_confirmation.evaluate_daily",
        lambda *a, **kw: {"price_signal": "BUY"},
    )
    result = refresh_confirmations(snapshot, provider, ["EXAMPLE"], now=NOW)
    assert result["signals"][0]["technical_confirmation"] == "BUY_CONFIRMED"
    assert calls == [("EXAMPLE", {"period": "5y", "interval": "1d"})]
    assert not result["execution_enabled"]
    assert snapshot["signals"][0]["technical_confirmation"] == "NOT_CHECKED"
    monkeypatch.setattr(
        "services.big_shark_confirmation.evaluate_daily",
        lambda *a, **kw: {"price_signal": "SELL_EXIT"},
    )
    assert (
        refresh_confirmations(snapshot, provider, ["EXAMPLE"], now=NOW)["signals"][0][
            "technical_confirmation"
        ]
        == "WAIT"
    )

    def failed(*args, **kwargs):
        raise RuntimeError("private-provider-credential")

    provider.candles = failed
    result = refresh_confirmations(snapshot, provider, ["EXAMPLE"], now=NOW)
    assert result["signals"][0]["technical_confirmation"] == "NO_DATA"
    assert "private-provider" not in str(result)
    with pytest.raises(ValueError):
        refresh_confirmations(snapshot, provider, ["UNKNOWN"], now=NOW)


def test_first_import_replaces_empty_picker_and_submits_current_snapshot(monkeypatch):
    import copy
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    original = read_portfolio(workbook())
    original["snapshot_id"] = "a" * 32
    imported = import_records(
        original, [trade()], source="NSE_BULK", metric="quantity", now=NOW
    )
    imported["snapshot_id"] = "b" * 32

    class Client:
        current = original
        calls = []

        def get_json(self, *args, **kwargs):
            return copy.deepcopy(self.current)

        def post_json(self, path, payload, **kwargs):
            self.calls.append((path, payload))
            result = copy.deepcopy(self.current)
            result["signals"][0]["technical_confirmation"] = "WAIT"
            return result

    client = Client()
    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: client)
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "webapp/pages/institutional_scanner.py").run(
        timeout=15
    )
    picker = next(v for v in app.selectbox if v.label == "Stock to confirm")
    assert picker.value is None
    client.current = imported
    app.run(timeout=15)
    picker = next(v for v in app.selectbox if v.label == "Stock to confirm")
    assert picker.value == "EXAMPLE"
    next(v for v in app.button if v.label == "Check daily confirmation").click().run(
        timeout=15
    )
    assert client.calls == [
        (
            "/institutional/big-shark/confirm",
            {"snapshot_id": "b" * 32, "symbols": ["EXAMPLE"]},
        )
    ]
    assert not app.exception
    assert {
        "Activity Signal",
        "Technical Confirmation",
        "Data Coverage",
        "Disclosure Time",
    }.issubset(app.dataframe[0].value.columns)
