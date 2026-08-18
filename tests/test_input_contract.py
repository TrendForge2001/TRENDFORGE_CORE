from __future__ import annotations

import pandas as pd

from engines.input_contract import EngineInputContract


def test_valid_payload_is_ready(ohlcv_frame):
    report = EngineInputContract().validate({"symbol": "ABC", "df": ohlcv_frame})
    assert report.ready is True
    assert report.missing == []
    assert report.invalid == []
    assert report.warnings


def test_non_mapping_payload_is_invalid():
    report = EngineInputContract().validate(None)
    assert report.ready is False
    assert "stock_payload" in report.invalid


def test_missing_symbol_is_rejected(ohlcv_frame):
    report = EngineInputContract().validate({"df": ohlcv_frame})
    assert report.ready is False
    assert "symbol" in report.missing


def test_symbol_alias_is_supported(ohlcv_frame):
    report = EngineInputContract().validate({"ticker": "ABC", "df": ohlcv_frame})
    assert report.ready is True


def test_empty_dataframe_is_rejected(empty_ohlcv_frame):
    report = EngineInputContract().validate({"symbol": "ABC", "df": empty_ohlcv_frame})
    assert report.ready is False
    assert "df_empty" in report.invalid


def test_missing_close_column_is_rejected(ohlcv_frame):
    frame = ohlcv_frame.drop(columns=["close"])
    report = EngineInputContract().validate({"symbol": "ABC", "df": frame})
    assert report.ready is False
    assert "df_close_column" in report.invalid


def test_non_numeric_close_values_are_rejected(ohlcv_frame):
    frame = ohlcv_frame.copy()
    frame["close"] = ["x", "y", "z", "w"]
    report = EngineInputContract().validate({"symbol": "ABC", "df": frame})
    assert report.ready is False
    assert "df_close_values" in report.invalid


def test_data_alias_is_supported(ohlcv_frame):
    report = EngineInputContract().validate({"symbol": "ABC", "data": ohlcv_frame})
    assert report.ready is True


def test_short_history_generates_warning(ohlcv_frame):
    report = EngineInputContract().validate({"symbol": "ABC", "df": ohlcv_frame})
    assert any("200 candles" in warning for warning in report.warnings)


def test_report_serialization_is_stable(ohlcv_frame):
    report = EngineInputContract().validate({"symbol": "ABC", "df": ohlcv_frame})
    payload = report.as_dict()
    assert set(payload) == {"ready", "missing", "invalid", "warnings"}
    assert isinstance(payload["missing"], list)
    assert isinstance(payload["invalid"], list)
    assert isinstance(payload["warnings"], list)
