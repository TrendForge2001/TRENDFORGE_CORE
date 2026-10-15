from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from models.signal import Signal
from services.paper_auto_entry_service import PaperAutoEntryService


class FakeTrades:
    def __init__(self, daily_pnl=0.0, traded=None):
        self.daily_pnl = daily_pnl
        self.traded = set(traded or [])

    def realized_pnl_for_entry_date(self, entry_date):
        return self.daily_pnl

    def has_trade_on_entry_date(self, symbol, entry_date):
        return symbol in self.traded


class FakePaper:
    def __init__(
        self,
        *,
        can_open=True,
        positions=None,
        daily_pnl=0.0,
        traded=None,
    ):
        self.can_open_new_positions = can_open
        self.open_calls = []
        self.runtime = SimpleNamespace(
            portfolio=SimpleNamespace(
                positions=dict(positions or {})
            ),
            trades=FakeTrades(
                daily_pnl=daily_pnl,
                traded=traded,
            ),
            _can_open=lambda now: (
                now.weekday() < 5
                and now.hour >= 10
                and now.hour < 15
            ),
        )

    def open(self, order, now=None):
        self.open_calls.append((order, now))
        self.runtime.portfolio.positions[order.symbol] = order
        return {"trade_id": len(self.open_calls)}


def candidate(
    *,
    symbol="TCS",
    signal_name="BUY",
    score=92.0,
    confidence=80.0,
    entry=3000.0,
    stoploss=2950.0,
    target2=3100.0,
    eligible=True,
):
    return {
        "symbol": symbol,
        "eligible": eligible,
        "ranking_score": score,
        "signal": Signal(
            symbol=symbol,
            signal=signal_name,
            confidence=confidence,
            overall_score=score,
            entry=entry,
            stoploss=stoploss,
            target1=entry + (entry - stoploss),
            target2=target2,
            target3=entry + 3 * (entry - stoploss),
            risk_reward=2.0,
            quantity=1,
        ),
    }


def completed_scan(*items):
    return {
        "outcome": "completed",
        "top_picks": list(items),
    }


def service(paper=None, monkeypatch=None):
    if monkeypatch is not None:
        for key in (
            "TRENDFORGE_PAPER_CAPITAL",
            "TRENDFORGE_PAPER_RISK_PER_TRADE_PERCENT",
            "TRENDFORGE_PAPER_MAX_DAILY_LOSS_PERCENT",
            "TRENDFORGE_PAPER_MAX_OPEN_POSITIONS",
            "TRENDFORGE_PAPER_MAX_CAPITAL_PER_TRADE_PERCENT",
            "TRENDFORGE_PAPER_MINIMUM_RR",
            "TRENDFORGE_PAPER_AUTO_ENTRY_MIN_SCORE",
            "TRENDFORGE_PAPER_AUTO_ENTRY_MIN_CONFIDENCE",
            "TRENDFORGE_PAPER_AUTO_ENTRY_MAX_PER_SCAN",
            "TRENDFORGE_PAPER_AUTO_ENTRY_SIGNALS",
        ):
            monkeypatch.delenv(key, raising=False)
    return PaperAutoEntryService(
        paper or FakePaper(),
        enabled=True,
    )


def test_valid_buy_is_sized_by_risk_and_opened(monkeypatch):
    paper = FakePaper()
    auto = service(paper, monkeypatch)

    result = auto.process_scan(
        completed_scan(candidate()),
        run_id="run-1",
        execute_requested=True,
        now=datetime(2026, 10, 16, 10, 0),
    )

    assert result["status"] == "executed"
    assert result["opened_count"] == 1
    opened = result["opened"][0]
    # 1% of 100k = 1000 risk; 50/share => 20 shares.
    # Capital cap is 20k / 3000 => 6 shares, so cap wins.
    assert opened["quantity"] == 6
    assert opened["reward_risk"] == 2.0
    assert len(paper.open_calls) == 1
    assert result["broker_orders_allowed"] is False


def test_disabled_feature_never_opens():
    paper = FakePaper()
    auto = PaperAutoEntryService(
        paper,
        enabled=False,
    )

    result = auto.process_scan(
        completed_scan(candidate()),
        run_id="run-disabled",
        execute_requested=True,
        now=datetime(2026, 10, 16, 10, 0),
    )

    assert result["status"] == "disabled"
    assert paper.open_calls == []


def test_explicit_scan_opt_in_is_required(monkeypatch):
    paper = FakePaper()
    auto = service(paper, monkeypatch)

    result = auto.process_scan(
        completed_scan(candidate()),
        run_id="run-not-requested",
        execute_requested=False,
        now=datetime(2026, 10, 16, 10, 0),
    )

    assert result["status"] == "not_requested"
    assert paper.open_calls == []


def test_partial_and_continuation_scans_are_never_execution_eligible(
    monkeypatch,
):
    paper = FakePaper()
    auto = service(paper, monkeypatch)

    partial = auto.process_scan(
        {
            "outcome": "partial",
            "top_picks": [candidate()],
        },
        run_id="partial",
        execute_requested=True,
        now=datetime(2026, 10, 16, 10, 0),
    )
    continuation = auto.process_scan(
        completed_scan(candidate()),
        run_id="child",
        execute_requested=True,
        continuation=True,
        now=datetime(2026, 10, 16, 10, 0),
    )

    assert partial["reason"] == "scan_not_completed"
    assert continuation["reason"] == (
        "continuation_scan_not_execution_eligible"
    )
    assert paper.open_calls == []


def test_candidate_must_be_high_conviction_and_scanner_eligible(
    monkeypatch,
):
    paper = FakePaper()
    auto = service(paper, monkeypatch)

    evaluation = auto.evaluate_candidate(
        candidate(
            signal_name="ACCUMULATE",
            score=89.0,
            confidence=50.0,
            eligible=False,
        ),
        now=datetime(2026, 10, 16, 10, 0),
    )

    assert evaluation["approved"] is False
    assert "scanner_not_eligible" in evaluation["reasons"]
    assert "signal_not_allowed" in evaluation["reasons"]
    assert "score_below_minimum" in evaluation["reasons"]
    assert "confidence_below_minimum" in evaluation["reasons"]


def test_invalid_risk_geometry_and_rr_are_rejected(monkeypatch):
    auto = service(FakePaper(), monkeypatch)

    evaluation = auto.evaluate_candidate(
        candidate(
            entry=100.0,
            stoploss=99.0,
            target2=101.5,
        ),
        now=datetime(2026, 10, 16, 10, 0),
    )

    assert evaluation["approved"] is False
    assert "reward_risk_below_minimum" in evaluation["reasons"]


def test_duplicate_open_or_same_day_symbol_is_rejected(monkeypatch):
    paper = FakePaper(
        positions={"TCS": object()},
        traded={"INFY"},
    )
    auto = service(paper, monkeypatch)

    open_eval = auto.evaluate_candidate(
        candidate(symbol="TCS"),
        now=datetime(2026, 10, 16, 10, 0),
    )
    day_eval = auto.evaluate_candidate(
        candidate(symbol="INFY"),
        now=datetime(2026, 10, 16, 10, 0),
    )

    assert "position_already_open" in open_eval["reasons"]
    assert "symbol_already_traded_today" in day_eval["reasons"]


def test_daily_loss_limit_blocks_entry(monkeypatch):
    paper = FakePaper(daily_pnl=-3000.0)
    auto = service(paper, monkeypatch)

    evaluation = auto.evaluate_candidate(
        candidate(),
        now=datetime(2026, 10, 16, 10, 0),
    )

    assert evaluation["approved"] is False
    assert "maximum_daily_loss_reached" in evaluation["reasons"]


def test_outside_market_window_is_rejected(monkeypatch):
    auto = service(FakePaper(), monkeypatch)

    evaluation = auto.evaluate_candidate(
        candidate(),
        now=datetime(2026, 10, 16, 15, 1),
    )

    assert evaluation["approved"] is False
    assert "outside_nse_entry_window" in evaluation["reasons"]


def test_only_one_entry_per_scan_by_default(monkeypatch):
    paper = FakePaper()
    auto = service(paper, monkeypatch)

    result = auto.process_scan(
        completed_scan(
            candidate(symbol="TCS"),
            candidate(
                symbol="INFY",
                entry=1500.0,
                stoploss=1475.0,
                target2=1550.0,
            ),
        ),
        run_id="one-entry",
        execute_requested=True,
        now=datetime(2026, 10, 16, 10, 0),
    )

    assert result["opened_count"] == 1
    assert len(paper.open_calls) == 1
    assert result["opened"][0]["symbol"] == "TCS"
