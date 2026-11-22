"""Actual-flow confluence, abstention and causal daily evidence; no broker calls."""

import copy
import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from services.institutional_stock_rating import RULE, rate, technical_evidence, view
from services.research_report import build_report

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_calendar(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "calendar.db"))


def activity(**changes):
    return dict(
        stock="Example",
        symbol="EXAMPLE",
        avg_buy=200.0,
        avg_sell=100.0,
        observations=3,
        missing_or_invalid=0,
        buyers=2,
        sellers=1,
        metric="quantity",
        units="shares",
        activity_signal="BUY",
        period_start="2026-11-16",
        period_end="2026-11-20",
        data_coverage="DISCLOSED_ONLY",
        first_seen_at="2026-11-20T11:00:00+00:00",
        disclosure_time=None,
        **changes,
    )


def evidence(horizon="short_term", bearish=False, **changes):
    values = dict(
        close=120.0,
        EMA_20=110.0,
        EMA_50=100.0,
        EMA_100=90.0,
        EMA_200=80.0,
        VWMA_20=115.0,
        VWMA_50=105.0,
        RSI_WILDER_14=60.0,
        volume=200.0,
        VOL_SMA_20=100.0,
        FIB_YEAR_P=100.0,
        FIB_YEAR_S1=90.0,
    )
    if bearish:
        values.update(
            close=80.0,
            EMA_20=90.0,
            EMA_50=100.0,
            EMA_100=110.0,
            EMA_200=120.0,
            VWMA_20=95.0,
            VWMA_50=105.0,
            RSI_WILDER_14=40.0,
        )
    values.update(changes)
    return dict(
        rule=RULE,
        horizon=horizon,
        status="READY",
        bar_closed_at="2026-11-20T15:30:00+05:30",
        checked_at=NOW.isoformat(),
        indicators=values,
    )


@pytest.mark.parametrize("horizon", ["short_term", "long_term"])
def test_actual_buying_with_confirmed_technicals_has_explainable_rating(horizon):
    result = rate(activity(), evidence(horizon), horizon=horizon, now=NOW)
    assert result["rating"] == "STRONG_BUY"
    assert result["institutional_score"] == 26.67
    assert result["technical_score"] == 60
    assert result["score"] == 86.67
    assert result["disclosure_time"] is None
    assert result["execution_enabled"] is False
    json.dumps(result, allow_nan=False)


def test_buy_and_exit_are_gated_by_agreement_not_just_the_numeric_score():
    row = activity()
    row.update(avg_buy=50, avg_sell=200, activity_signal="SELL")
    assert rate(row, evidence(), now=NOW)["rating"] == "CONFLICT"
    result = rate(row, evidence(bearish=True), now=NOW)
    assert result["rating"] == "EXIT" and result["score"] == 23
    assert "long exits only" in result["reason"]
    assert rate(activity(), evidence(bearish=True), now=NOW)["rating"] == "CONFLICT"


@pytest.mark.parametrize(
    "changes",
    [
        {"volume": 100.0},
        {"RSI_WILDER_14": 50.0},
        {"RSI_WILDER_14": 71.0},
        {"VWMA_20": 100.0},
        {"EMA_20": 90.0},
    ],
)
def test_missing_momentum_volume_or_trend_confirmation_cannot_rate_buy(changes):
    assert rate(activity(), evidence(**changes), now=NOW)["rating"] == "WATCH"


def test_buy_below_central_pivot_has_lower_disclosed_score():
    row = activity()
    row.update(avg_buy=101, avg_sell=100)
    result = rate(row, evidence(FIB_YEAR_P=130.0), now=NOW)
    assert result["rating"] == "BUY" and result["score"] == 75.1


@pytest.mark.parametrize(
    "changes",
    [
        {"observations": 0},
        {"avg_buy": None},
        {"avg_sell": float("nan")},
        {"missing_or_invalid": 1},
        {"data_coverage": "PARTIAL_INPUT"},
        {"period_end": "2026-11-12"},
        {"period_end": "2026-11-21"},
        {"first_seen_at": "2026-11-20T13:00:00+00:00"},
        {"disclosure_time": "2026-11-20T13:00:00+00:00"},
        {"period_start": None},
    ],
)
def test_missing_partial_stale_and_not_yet_available_activity_abstains(changes):
    row = activity()
    row.update(changes)
    result = rate(row, evidence(), now=NOW)
    assert result["rating"] == "INSUFFICIENT_DATA" and result["score"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"EMA_50": None},
        {"VWMA_20": -1.0},
        {"VOL_SMA_20": 0.0},
        {"RSI_WILDER_14": 101.0},
    ],
)
def test_invalid_technical_values_never_create_a_score(changes):
    assert rate(activity(), evidence(**changes), now=NOW)["score"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("bar_closed_at", "2026-11-19T15:30:00+05:30"),
        ("bar_closed_at", "2026-11-21T15:30:00+05:30"),
        ("checked_at", "2026-11-20T13:00:00+00:00"),
        ("horizon", "long_term"),
        ("rule", "older-rating-rule"),
    ],
)
def test_stale_future_or_different_horizon_technical_evidence_abstains(field, value):
    tech = evidence()
    tech[field] = value
    assert rate(activity(), tech, now=NOW)["score"] is None


def test_cached_scores_preserve_source_and_do_not_invent_holdings_activity():
    row = activity()
    row["rating_technicals"] = {"short_term": evidence()}
    snapshot = {
        "imported_at": NOW.isoformat(),
        "signals": [row],
        "execution_enabled": False,
    }
    original = copy.deepcopy(snapshot)
    result = view(snapshot, now=NOW)
    assert snapshot == original
    assert result["signals"][0]["stock_rating"] == "STRONG_BUY"
    assert (
        view(snapshot, horizon="long_term", now=NOW)["signals"][0]["rating_score"]
        is None
    )
    snapshot["signals"][0].update(observations=0, avg_buy=None, avg_sell=None)
    assert view(snapshot, now=NOW)["signals"][0]["stock_rating"] == "INSUFFICIENT_DATA"


def test_actual_values_and_quantities_use_the_same_side_mean_formula():
    row = activity()
    row.update(metric="value", units="INR", avg_buy=2000, avg_sell=1000)
    assert rate(row, evidence(), now=NOW)["score"] == 86.67


def test_scan_exports_retain_ratings_but_do_not_change_technical_entry_signal():
    rating = rate(activity(), evidence(), now=NOW)
    result = {
        "run_id": "rating-fixture",
        "status": "completed",
        "results": [
            {
                "symbol": "EXAMPLE",
                "signal": "WAIT",
                "score": 50,
                "institutional_rating": rating,
                "entry": None,
                "stoploss": None,
                "target2": None,
            }
        ],
    }
    report = build_report(
        result, kind="scan", horizon="short_term", stock_list="NIFTY 500"
    )
    row = report["rows"][0]
    assert row["signal"] == "WAIT" and row["stock_rating"] == "STRONG_BUY"
    assert row["rating_score"] == 86.67
    assert "rating_data_coverage" in report["columns"]
    assert row["rating_disclosure_time"] is None


def test_technical_evidence_excludes_future_bars_and_keeps_source_unchanged():
    import numpy as np

    index = pd.bdate_range("2023-01-02", "2026-11-23", tz="Asia/Kolkata")
    price = 100 + np.arange(len(index)) * 0.02 + np.sin(np.arange(len(index))) * 2
    frame = pd.DataFrame(
        dict(open=price, high=price + 1, low=price - 1, close=price, volume=1000.0),
        index=index,
    )
    original = frame.copy()
    baseline = technical_evidence(frame, horizon="long_term", now=NOW)
    assert baseline["status"] == "READY"
    changed = frame.copy()
    changed.loc["2026-11-23", ["open", "high", "low", "close"]] = [
        10000,
        11000,
        9000,
        10000,
    ]
    after = technical_evidence(changed, horizon="long_term", now=NOW)
    assert baseline["indicators"] == after["indicators"]
    assert baseline["bar_closed_at"].startswith("2026-11-20")
    pd.testing.assert_frame_equal(frame, original)


def test_scanner_reads_only_latest_private_disclosure_without_creating_tables(tmp_path):
    from types import SimpleNamespace

    from database.database import Database
    from services.institutional_stock_rating import load_snapshot

    db = Database(str(tmp_path / "private.db"))
    technical = SimpleNamespace(repository=SimpleNamespace(db=db))
    try:
        assert load_snapshot(technical) == {}
        assert (
            db.fetchone(
                "SELECT name FROM sqlite_master WHERE name='big_shark_portfolios'"
            )
            is None
        )
        db.execute("CREATE TABLE big_shark_portfolios (payload_json TEXT)")
        for symbol in ("OLD", "LATEST"):
            row = activity()
            row["symbol"] = symbol
            payload = json.dumps({"signals": [row], "imported_at": NOW.isoformat()})
            db.execute("INSERT INTO big_shark_portfolios VALUES (?)", (payload,))
        assert set(load_snapshot(technical)) == {"LATEST"}
    finally:
        db.close()


def test_private_workbook_exports_both_rating_horizons_without_formulas():
    from io import BytesIO

    from openpyxl import load_workbook

    from services.big_shark_portfolio import read_portfolio, workbook_bytes
    from tests.test_big_shark_portfolio import workbook

    snapshot = read_portfolio(workbook())
    row = activity()
    row["rating_technicals"] = {h: evidence(h) for h in ("short_term", "long_term")}
    snapshot["signals"] = [row]
    result = load_workbook(BytesIO(workbook_bytes(snapshot)), data_only=False)
    records = list(result["STOCK RATINGS"].values)
    assert len(records) == 3
    assert {value for record in records[1:] for value in record} >= {
        "short_term",
        "long_term",
    }
    assert not any(
        cell.data_type == "f" for sheet in result for record in sheet for cell in record
    )


def test_prepared_workbook_revision_survives_display_clock_reruns_without_mutation():
    from datetime import timedelta

    from webapp.institutional_activity import workbook_revision

    snapshot = {"signals": [activity()]}
    snapshot["signals"][0]["rating_technicals"] = {"short_term": evidence()}
    original = copy.deepcopy(snapshot)
    first = view(snapshot, now=NOW)
    rerun = view(snapshot, now=NOW + timedelta(seconds=10))
    assert first != rerun
    assert workbook_revision(first) == workbook_revision(rerun)
    assert snapshot == original
    assert "as_of" in first["signals"][0]["rating_evidence"]


@pytest.mark.parametrize("change", ["freshness", "source", "evidence", "rating"])
def test_prepared_workbook_revision_changes_for_material_updates(change):
    from webapp.institutional_activity import workbook_revision

    original = view({"signals": [activity()]}, now=NOW)
    changed = copy.deepcopy(original)
    if change == "source":
        changed["snapshot_id"] = "new-owner-snapshot"
    elif change == "freshness":
        changed["signals"][0]["rating_evidence"]["reason"] = "Evidence is stale"
    elif change == "evidence":
        changed["signals"][0]["rating_technicals"] = {"short_term": evidence()}
    else:
        changed["signals"][0]["rating_score"] = 90
    assert workbook_revision(changed) != workbook_revision(original)


def test_export_invalidates_when_hidden_horizons_daily_evidence_becomes_stale():
    from webapp.institutional_activity import workbook_revision

    row = activity()
    row["rating_technicals"] = {"short_term": evidence()}
    snapshot = {"signals": [row]}
    next_close = datetime(2026, 11, 23, 11, tzinfo=UTC)
    first = view(snapshot, horizon="long_term", now=NOW)
    after = view(snapshot, horizon="long_term", now=next_close)
    # Long Term was already unavailable, but the Short Term sheet has expired.
    assert first["signals"][0]["rating_reason"] == after["signals"][0]["rating_reason"]
    assert workbook_revision(first, now=NOW) != workbook_revision(after, now=next_close)
