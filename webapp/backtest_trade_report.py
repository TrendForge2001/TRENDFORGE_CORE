"""Frontend adapters for the canonical backend execution report."""

from services.execution_report import TRADE_COLUMNS as TRADE_COLUMNS
from services.execution_report import ReportValidationError
from services.execution_report import trade_report as _trade_report
from services.execution_report import validate_result as _validate_result
from webapp.api_client import ApiError


def validate_result(result):
    try:
        return _validate_result(result)
    except ReportValidationError as exc:
        raise ApiError(str(exc)) from None


def trade_report(result):
    try:
        return _trade_report(result)
    except ReportValidationError as exc:
        raise ApiError(str(exc)) from None
