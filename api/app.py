"""Canonical FastAPI application boundary for TrendForge Core."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
import os
import re
import tempfile
import time
from typing import Any, Callable
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.admin_auth import require_admin_api_key
from api.public_health import public_health
from api.scanner_error_boundary import install_api_error_boundary
from api.production_runtime import production_runtime_enabled, secure_application
from api.scheduler_auth import (
    SCHEDULER_API_KEY_HEADER,
    scheduler_security_health,
    validate_scheduler_api_key,
)

from core.application_factory import ApplicationFactory, build_application_factory
from core.database import initialize_database
from database.repositories.scan_run_audit_repository import (
    DuplicateScanRunIdError,
)
from database.repositories.scan_continuation_repository import (
    ContinuationAttemptLimitError,
    ContinuationExpiredError,
    ContinuationNotFoundError,
    ContinuationUnavailableError,
)
from services.scan_execution_guard import ScanExecutionGuard
from services.paper_trading_service import (
    PaperTradingDisabledError,
    PaperTradingKillSwitchError,
    PaperTradingStorageError,
)
from services.technical_trading_service import TechnicalTradingValidationError


_AUDIT_LOG = logging.getLogger("trendforge.scan.continuation")

MAX_FUNDAMENTAL_UPLOAD_BYTES = 10 * 1024 * 1024


class ScanRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=500)
    period: str = "6mo"
    interval: str = "1d"
    capital: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    top_n: int = Field(default=20, ge=1, le=500)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        normalized = [str(symbol).strip().upper() for symbol in value]
        if any(not symbol for symbol in normalized):
            raise ValueError("symbols must not contain empty values")
        return normalized


class Nifty500ScanRequest(BaseModel):
    period: str = "6mo"
    interval: str = "1d"
    capital: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    top_n: int = Field(default=20, ge=1, le=500)
    batch_size: int = Field(default=25, ge=1, le=100)
    batch_pause_seconds: float = Field(default=1.0, ge=0, le=10)
    scan_time_budget_seconds: float = Field(
        default=450.0,
        ge=10.0,
        le=900.0,
    )
    batch_time_budget_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=180.0,
    )
    limit: int = Field(default=25, ge=1, le=500)
    full_universe: bool = False
    refresh_universe: bool = False
    compact: bool = True
    paper_auto_entry: bool = False


class PaperOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=30)
    side: str = Field(default="BUY", pattern="^(BUY|SELL|SHORT)$")
    quantity: int = Field(gt=0, le=1_000_000)
    price: float = Field(gt=0, allow_inf_nan=False)
    stoploss: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    target2: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    trade_mode: str = Field(
        default="intraday",
        pattern="^(intraday|swing)$",
    )

    @field_validator("quantity", "price", "stoploss", "target2", mode="before")
    @classmethod
    def reject_boolean_order_values(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("Paper order values must be numbers, not booleans")
        return value

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = str(value).strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._&-]{0,29}", normalized) or ".." in normalized:
            raise ValueError("A valid NSE symbol is required")
        return normalized


class PaperMonitorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    quotes: dict[str, float]

    @field_validator("quotes", mode="before")
    @classmethod
    def reject_boolean_quote_values(cls, value: Any) -> Any:
        if isinstance(value, dict) and any(isinstance(price, bool) for price in value.values()):
            raise ValueError("Paper monitor prices must be numbers, not booleans")
        return value

    @field_validator("quotes")
    @classmethod
    def validate_monitor_prices(cls, value: dict[str, float]) -> dict[str, float]:
        if any(price <= 0 for price in value.values()):
            raise ValueError("Paper monitor prices must be positive")
        return value


class PaperKillSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class WatchlistEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=30)
    exchange: str = Field(default="NSE", min_length=1, max_length=12)
    notes: str = Field(default="", max_length=500)
    priority: int = Field(default=1, ge=1, le=5)
    target: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    stoploss: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    scanner: str | None = Field(default=None, max_length=80)
    score: float | None = Field(
        default=None,
        ge=0,
        le=100,
        allow_inf_nan=False,
    )
    last_signal: str | None = Field(default=None, max_length=40)
    last_scan: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_watchlist_symbol(cls, value: str) -> str:
        normalized = str(value).strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class WatchlistUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(default=None, max_length=500)
    priority: int | None = Field(default=None, ge=1, le=5)
    target: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    stoploss: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    scanner: str | None = Field(default=None, max_length=80)
    score: float | None = Field(
        default=None,
        ge=0,
        le=100,
        allow_inf_nan=False,
    )
    last_signal: str | None = Field(default=None, max_length=40)
    last_scan: str | None = None


class MarketContextRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=25, le=500)
    period: str = Field(
        default="1y",
        pattern="^(1y|2y)$",
    )
    interval: str = Field(default="1d", pattern="^1d$")
    refresh_universe: bool = False


class BacktestRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=30)
    period: str = Field(
        default="2y",
        pattern="^(1y|2y|5y)$",
    )
    interval: str = Field(default="1d", pattern="^1d$")
    capital: float = Field(
        default=100000.0,
        ge=1000.0,
        le=1_000_000_000.0,
        allow_inf_nan=False,
    )
    rsi_threshold: float = Field(
        default=60.0,
        ge=0.0,
        le=100.0,
        allow_inf_nan=False,
    )
    ema_proximity_pct: float = Field(
        default=1.0,
        ge=0.0,
        le=20.0,
        allow_inf_nan=False,
    )
    cost_bps: float = Field(
        default=0.0,
        ge=0.0,
        le=1000.0,
        allow_inf_nan=False,
    )
    slippage_bps: float = Field(
        default=0.0,
        ge=0.0,
        le=1000.0,
        allow_inf_nan=False,
    )
    run_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
    )

    @field_validator("symbol")
    @classmethod
    def normalize_backtest_symbol(cls, value: str) -> str:
        normalized = str(value).strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class TechnicalScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(..., min_length=1, max_length=100)
    strategy_id: str | None = Field(default=None, max_length=80)
    mode: str = Field(default="intraday", pattern="^(intraday|swing)$")
    period: str | None = Field(default=None, max_length=10)
    top_n: int = Field(default=20, ge=1, le=100)
    execute_paper: bool = False
    run_id: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("symbols")
    @classmethod
    def normalize_technical_symbols(cls, value: list[str]) -> list[str]:
        normalized = [str(symbol).strip().upper() for symbol in value]
        if any(not symbol for symbol in normalized):
            raise ValueError("symbols must not contain empty values")
        return normalized


class TechnicalBacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=30)
    strategy_id: str | None = Field(default=None, max_length=80)
    mode: str = Field(default="swing", pattern="^(intraday|swing)$")
    period: str | None = Field(default=None, max_length=10)
    capital: float = Field(
        default=100000.0,
        ge=1000.0,
        le=1_000_000_000.0,
        allow_inf_nan=False,
    )
    cost_bps: float = Field(
        default=0.0,
        ge=0.0,
        le=1000.0,
        allow_inf_nan=False,
    )
    slippage_bps: float = Field(
        default=0.0,
        ge=0.0,
        le=1000.0,
        allow_inf_nan=False,
    )
    run_id: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("symbol")
    @classmethod
    def normalize_technical_backtest_symbol(cls, value: str) -> str:
        normalized = str(value).strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class MultiStrategyScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    universe: str = Field(default="NIFTY 100", min_length=1, max_length=20)
    mode: str = Field(default="swing", pattern="^(intraday|swing|positional)$")
    source: str = Field(
        default="all",
        pattern="^(all|user_notebook|template)$",
    )
    strategy_ids: list[str] | None = Field(default=None, max_length=19)
    period: str | None = Field(default=None, max_length=10)
    top_n: int = Field(default=20, ge=1, le=100)
    limit: int | None = Field(default=None, ge=1, le=500)
    force_refresh_universe: bool = False
    run_id: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("universe")
    @classmethod
    def normalize_multi_strategy_universe(cls, value: str) -> str:
        from providers.nse_broad_market_constituents import normalize_index_name

        return normalize_index_name(value)

    @field_validator("strategy_ids")
    @classmethod
    def normalize_multi_strategy_ids(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        if value is None:
            return None
        normalized = [
            str(item).strip().lower()
            for item in value
            if str(item).strip()
        ]
        if not normalized:
            return None
        if len(normalized) != len(set(normalized)):
            raise ValueError("strategy_ids must be unique")
        return normalized


class StrategyDrivenPaperRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(min_length=1, max_length=120)
    scan_run_id: str = Field(min_length=1, max_length=120)
    validation_run_id: str = Field(min_length=1, max_length=120)

    @field_validator("strategy_id")
    @classmethod
    def normalize_strategy_paper_id(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            raise ValueError("strategy_id is required")
        return normalized

    @field_validator("scan_run_id", "validation_run_id")
    @classmethod
    def normalize_strategy_paper_run_ids(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("run id is required")
        return normalized


class MultiStrategyValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    universes: list[str] = Field(
        default_factory=lambda: ["NIFTY 100"],
        min_length=1,
        max_length=3,
    )
    modes: list[str] = Field(
        default_factory=lambda: ["swing"],
        min_length=1,
        max_length=3,
    )
    source: str = Field(
        default="all",
        pattern="^(all|user_notebook|template)$",
    )
    strategy_ids: list[str] | None = Field(
        default=None,
        max_length=19,
    )
    capital: float = Field(
        default=100000.0,
        ge=1000.0,
        le=1_000_000_000.0,
        allow_inf_nan=False,
    )
    chunk_size: int = Field(default=25, ge=1, le=50)
    limit: int | None = Field(default=25, ge=1, le=500)
    force_refresh_universes: bool = False
    force: bool = False

    @field_validator("universes")
    @classmethod
    def normalize_validation_universes(
        cls,
        value: list[str],
    ) -> list[str]:
        from providers.nse_broad_market_constituents import (
            normalize_index_name,
        )

        output: list[str] = []
        for item in value:
            name = normalize_index_name(item)
            if name not in output:
                output.append(name)
        if not output:
            raise ValueError("at least one universe is required")
        return output

    @field_validator("modes")
    @classmethod
    def normalize_validation_modes(
        cls,
        value: list[str],
    ) -> list[str]:
        allowed = {"intraday", "swing", "positional"}
        output: list[str] = []
        for item in value:
            mode = str(item or "").strip().lower()
            if mode not in allowed:
                raise ValueError(
                    "modes must contain intraday, swing or positional"
                )
            if mode not in output:
                output.append(mode)
        if not output:
            raise ValueError("at least one mode is required")
        return output

    @field_validator("strategy_ids")
    @classmethod
    def normalize_validation_strategy_ids(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        if value is None:
            return None
        output = [
            str(item).strip().lower()
            for item in value
            if str(item).strip()
        ]
        if not output:
            return None
        if len(output) != len(set(output)):
            raise ValueError("strategy_ids must be unique")
        return output


class TechnicalValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capital: float = Field(
        default=100000.0,
        ge=1000.0,
        le=1_000_000_000.0,
        allow_inf_nan=False,
    )
    chunk_size: int = Field(default=25, ge=1, le=50)
    force: bool = False


class IntelligenceRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
    )
    domains: list[str] = Field(
        default_factory=lambda: [
            "news",
            "corporate_actions",
        ],
        min_length=1,
        max_length=2,
    )
    days: int = Field(default=120, ge=1, le=365)

    @field_validator("symbols")
    @classmethod
    def normalize_intelligence_symbols(
        cls,
        value: list[str],
    ) -> list[str]:
        normalized = [
            str(symbol).strip().upper()
            for symbol in value
        ]
        if any(not symbol for symbol in normalized):
            raise ValueError(
                "symbols must not contain empty values"
            )
        return normalized

    @field_validator("domains")
    @classmethod
    def validate_intelligence_domains(
        cls,
        value: list[str],
    ) -> list[str]:
        normalized = [
            str(item).strip().lower()
            for item in value
        ]
        allowed = {"news", "corporate_actions"}
        if any(item not in allowed for item in normalized):
            raise ValueError(
                "domains must contain news and/or corporate_actions"
            )
        return normalized


class InstitutionalRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(
        ...,
        min_length=1,
        max_length=25,
    )

    @field_validator("symbols")
    @classmethod
    def normalize_institutional_symbols(
        cls,
        value: list[str],
    ) -> list[str]:
        normalized = [
            str(symbol).strip().upper()
            for symbol in value
        ]
        if any(not symbol for symbol in normalized):
            raise ValueError(
                "symbols must not contain empty values"
            )
        return normalized


class SectorStrengthRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=25, le=500)
    period: str = Field(
        default="1y",
        pattern="^(1y|2y)$",
    )
    interval: str = Field(default="1d", pattern="^1d$")
    refresh_universe: bool = False


class NotificationEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=40)
    severity: str = Field(default="INFO", min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1, max_length=4000)
    symbol: str | None = Field(default=None, max_length=30)
    source: str = Field(default="webapp", min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str | None = Field(default=None, max_length=200)
    deliver: bool = True

    @field_validator("symbol")
    @classmethod
    def normalize_notification_symbol(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    @field_validator("category")
    @classmethod
    def normalize_notification_category(
        cls,
        value: str,
    ) -> str:
        return str(value).strip().lower()

    @field_validator("severity")
    @classmethod
    def normalize_notification_severity(
        cls,
        value: str,
    ) -> str:
        return str(value).strip().upper()


class NotificationCategoryPreferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    minimum_severity: str = Field(
        default="INFO",
        pattern="^(INFO|SUCCESS|WARNING|ERROR|CRITICAL)$",
    )


class NotificationQuietHoursRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    start: str = Field(default="22:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(default="07:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    allow_critical: bool = True


class NotificationDailySummaryPreferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    time_ist: str = Field(default="18:30", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    skip_empty: bool = True
    notable_limit: int = Field(default=10, ge=1, le=25)


class NotificationPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_enabled: bool = True
    categories: dict[
        str,
        NotificationCategoryPreferenceRequest,
    ]
    quiet_hours: NotificationQuietHoursRequest = Field(
        default_factory=NotificationQuietHoursRequest
    )
    daily_summary: NotificationDailySummaryPreferenceRequest = Field(
        default_factory=NotificationDailySummaryPreferenceRequest
    )


class NotificationDailySummarySendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_date: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    force: bool = False


class MarketDayCalendarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holiday_dates: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    special_trading_dates: list[str] = Field(
        default_factory=list,
        max_length=30,
    )


class MorningOperationsPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    time_ist: str = Field(
        default="08:45",
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
    )
    grace_minutes: int = Field(default=30, ge=5, le=180)
    refresh_market_context: bool = True
    notify_discord: bool = True


class EodOperationsPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    time_ist: str = Field(
        default="15:45",
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
    )
    grace_minutes: int = Field(default=30, ge=5, le=180)
    paper_safety_tick: bool = True
    refresh_market_context: bool = True
    portfolio_sync: bool = False
    notify_discord: bool = True


class MarketDayOperationsPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    automation_enabled: bool = False
    market_day_only: bool = True
    calendar: MarketDayCalendarRequest = Field(
        default_factory=MarketDayCalendarRequest
    )
    market_context_limit: int = Field(default=100, ge=25, le=500)
    morning: MorningOperationsPolicyRequest = Field(
        default_factory=MorningOperationsPolicyRequest
    )
    eod: EodOperationsPolicyRequest = Field(
        default_factory=EodOperationsPolicyRequest
    )


class MarketDayOperationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False


class ExternalOperationsTickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_operation: str = Field(
        pattern="^(morning|eod)$",
    )


class OperationsAuditRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str | None = Field(
        default=None,
        pattern="^(morning|eod)$",
    )
    deliver_alerts: bool = False


class FundamentalUpdateRequest(BaseModel):
    """Partial manual update; omitted values preserve existing SQLite fields."""

    model_config = ConfigDict(extra="forbid")

    roce: float | None = Field(default=None, ge=-1000, le=1000)
    roe: float | None = Field(default=None, ge=-1000, le=1000)
    sales_growth: float | None = Field(default=None, ge=-1000, le=1000)
    profit_growth: float | None = Field(default=None, ge=-1000, le=1000)
    eps_growth: float | None = Field(default=None, ge=-1000, le=1000)
    debt_equity: float | None = Field(default=None, ge=0)
    promoter_holding: float | None = Field(default=None, ge=0, le=100)
    pledged: float | None = Field(default=None, ge=0, le=100)
    source: str = Field(default="manual", min_length=1, max_length=100)
    as_of: str | None = None


_APPLICATION_FACTORY: ApplicationFactory | None = None


def get_application() -> ApplicationFactory:
    global _APPLICATION_FACTORY
    if _APPLICATION_FACTORY is None:
        _APPLICATION_FACTORY = build_application_factory()
    return _APPLICATION_FACTORY


def get_scanner_service():
    return get_application().scanner_service()


def create_app(
    application_factory: ApplicationFactory | None = None,
    *,
    database_initializer: Callable[[], dict[str, Any]] | None = None,
) -> FastAPI:
    global _APPLICATION_FACTORY
    factory = application_factory or build_application_factory()
    if application_factory is None:
        _APPLICATION_FACTORY = factory

    def current_application():
        return factory if application_factory is not None else get_application()

    def current_scanner_service():
        return factory.scanner_service() if application_factory is not None else get_scanner_service()

    def current_nifty500_universe():
        application = current_application()
        method = getattr(application, "nifty500_universe", None)
        if not callable(method):
            raise RuntimeError(
                "NIFTY 500 universe is not available in this application"
            )
        return method()

    def current_fundamental_manager():
        return current_application().fundamental_manager()

    def current_fundamental_completion_service():
        return current_application().fundamental_completion_service()

    def current_fundamental_coverage_service():
        application = current_application()
        method = getattr(
            application,
            "fundamental_coverage_service",
            None,
        )
        return method() if callable(method) else None

    def current_fundamental_bulk_ingestion_service():
        application = current_application()
        method = getattr(
            application,
            "fundamental_bulk_ingestion_service",
            None,
        )
        return method() if callable(method) else None

    def current_scan_run_audit_service():
        application = current_application()
        method = getattr(application, "scan_run_audit_service", None)
        return method() if callable(method) else None

    def current_scan_continuation_service():
        application = current_application()
        method = getattr(
            application,
            "scan_continuation_service",
            None,
        )
        return method() if callable(method) else None

    def current_paper_trading_service():
        application = current_application()
        method = getattr(
            application,
            "paper_trading_service",
            None,
        )
        return method() if callable(method) else None

    def current_paper_quote_monitor():
        application = current_application()
        method = getattr(
            application,
            "paper_quote_monitor",
            None,
        )
        return method() if callable(method) else None

    def current_paper_auto_entry_service():
        application = current_application()
        method = getattr(
            application,
            "paper_auto_entry_service",
            None,
        )
        return method() if callable(method) else None

    def current_strategy_driven_paper_service():
        application = current_application()
        method = getattr(
            application,
            "strategy_driven_paper_service",
            None,
        )
        return method() if callable(method) else None

    def current_strategy_paper_monitor_service():
        application = current_application()
        method = getattr(
            application,
            "strategy_paper_monitor_service",
            None,
        )
        return method() if callable(method) else None

    def current_strategy_runtime_reconciliation_service():
        application = current_application()
        method = getattr(
            application,
            "strategy_runtime_reconciliation_service",
            None,
        )
        return method() if callable(method) else None

    def current_portfolio_performance_service():
        application = current_application()
        method = getattr(
            application,
            "portfolio_performance_service",
            None,
        )
        return method() if callable(method) else None

    def current_watchlist_dashboard_service():
        application = current_application()
        method = getattr(
            application,
            "watchlist_dashboard_service",
            None,
        )
        return method() if callable(method) else None

    def current_market_context_service():
        application = current_application()
        method = getattr(
            application,
            "market_context_service",
            None,
        )
        return method() if callable(method) else None

    def current_backtest_service():
        application = current_application()
        method = getattr(
            application,
            "backtest_service",
            None,
        )
        return method() if callable(method) else None

    def current_technical_trading_service():
        application = current_application()
        method = getattr(
            application,
            "technical_trading_service",
            None,
        )
        return method() if callable(method) else None

    def current_multi_strategy_scanner_service():
        application = current_application()
        method = getattr(
            application,
            "multi_strategy_scanner_service",
            None,
        )
        return method() if callable(method) else None

    def current_intelligence_dashboard_service():
        application = current_application()
        method = getattr(
            application,
            "intelligence_dashboard_service",
            None,
        )
        return method() if callable(method) else None

    def current_institutional_sector_service():
        application = current_application()
        method = getattr(
            application,
            "institutional_sector_service",
            None,
        )
        return method() if callable(method) else None

    def current_notification_center_service():
        application = current_application()
        method = getattr(
            application,
            "notification_center_service",
            None,
        )
        return method() if callable(method) else None

    def current_notification_producer_service():
        application = current_application()
        method = getattr(
            application,
            "notification_producer_service",
            None,
        )
        return method() if callable(method) else None

    def current_notification_policy_service():
        application = current_application()
        method = getattr(
            application,
            "notification_policy_service",
            None,
        )
        return method() if callable(method) else None

    def current_notification_daily_summary_service():
        application = current_application()
        method = getattr(
            application,
            "notification_daily_summary_service",
            None,
        )
        return method() if callable(method) else None

    def current_notification_summary_scheduler():
        application = current_application()
        method = getattr(
            application,
            "notification_summary_scheduler",
            None,
        )
        return method() if callable(method) else None

    def current_market_day_operations_service():
        application = current_application()
        method = getattr(
            application,
            "market_day_operations_service",
            None,
        )
        return method() if callable(method) else None

    def current_market_day_operations_scheduler():
        application = current_application()
        method = getattr(
            application,
            "market_day_operations_scheduler",
            None,
        )
        return method() if callable(method) else None

    def current_operations_reliability_service():
        application = current_application()
        method = getattr(
            application,
            "operations_reliability_service",
            None,
        )
        return method() if callable(method) else None

    def best_effort_notification_producer():
        try:
            return current_notification_producer_service()
        except Exception:
            return None

    initializer = database_initializer or initialize_database

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _app.state.database = initializer()
        importer = getattr(
            current_application(),
            "import_fundamentals_if_configured",
            None,
        )
        _app.state.fundamentals_import = (
            importer()
            if callable(importer)
            else {"status": "not_supported"}
        )

        notification_producer = best_effort_notification_producer()

        notification_summary_scheduler = (
            current_notification_summary_scheduler()
        )
        if notification_summary_scheduler is not None:
            try:
                started = await notification_summary_scheduler.start()
                _app.state.notification_summary_scheduler = {
                    "status": (
                        "started"
                        if started
                        else "worker_disabled"
                    )
                }
            except Exception as exc:
                _app.state.notification_summary_scheduler = {
                    "status": "failed",
                    "error": str(exc),
                }
        else:
            _app.state.notification_summary_scheduler = {
                "status": "not_supported"
            }

        paper_service = current_paper_trading_service()
        if paper_service is not None:
            try:
                restored = paper_service.restore_open()
                _app.state.paper_trading_restore = {
                    "status": "restored",
                    "open_trades": restored,
                }
                if (
                    restored
                    and notification_producer is not None
                ):
                    notification_producer.startup_event(
                        event_type="paper_restore_completed",
                        title="Paper Positions Restored",
                        message=(
                            f"Restored {restored} open paper "
                            "position(s) from persistence."
                        ),
                        severity="INFO",
                        deliver=False,
                        payload={
                            "restored_open_trades": restored,
                            "paper_only": True,
                        },
                    )
            except Exception as exc:
                _app.state.paper_trading_restore = {
                    "status": "failed",
                    "error": str(exc),
                }
                if notification_producer is not None:
                    notification_producer.startup_event(
                        event_type="paper_restore_failed",
                        title="Paper Restore Failed",
                        message=str(exc),
                        severity="ERROR",
                        deliver=True,
                        payload={"paper_only": True},
                    )
        else:
            _app.state.paper_trading_restore = {
                "status": "not_supported"
            }

        paper_monitor = current_paper_quote_monitor()
        if paper_monitor is not None:
            try:
                started = await paper_monitor.start()
                _app.state.paper_quote_monitor_start = {
                    "status": (
                        "started"
                        if started
                        else "disabled"
                    )
                }
            except Exception as exc:
                _app.state.paper_quote_monitor_start = {
                    "status": "failed",
                    "error": str(exc),
                }
                if notification_producer is not None:
                    notification_producer.startup_event(
                        event_type="paper_monitor_start_failed",
                        title="Paper Quote Monitor Start Failed",
                        message=str(exc),
                        severity="ERROR",
                        deliver=True,
                        payload={"paper_only": True},
                    )
        else:
            _app.state.paper_quote_monitor_start = {
                "status": "not_supported"
            }

        operations_scheduler = None
        try:
            operations_scheduler = (
                current_market_day_operations_scheduler()
            )
            if operations_scheduler is not None:
                started = await operations_scheduler.start()
                _app.state.market_day_operations_scheduler = {
                    "status": (
                        "started"
                        if started
                        else "worker_disabled"
                    )
                }
            else:
                _app.state.market_day_operations_scheduler = {
                    "status": "not_supported"
                }
        except Exception as exc:
            operations_scheduler = None
            _app.state.market_day_operations_scheduler = {
                "status": "failed",
                "error": str(exc),
            }

        try:
            from services.technical_validation_runtime import (
                start_if_configured as start_r715_if_configured,
            )
            _app.state.r715_validation_start = (
                start_r715_if_configured(
                    _app,
                    technical_service=current_technical_trading_service(),
                )
            )
        except Exception as exc:
            _app.state.r715_validation_start = {
                "status": "failed",
                "error": str(exc),
            }

        technical_auto_scanner = None
        try:
            from services.technical_auto_scanner import TechnicalAutoScanner

            technical_auto_scanner = TechnicalAutoScanner(
                technical_service=current_technical_trading_service(),
                paper_auto_entry=current_paper_auto_entry_service(),
            )
            # Saved-strategy automation owns automatic entries. The legacy
            # scanner remains research-only so OFF controls every auto entry.
            technical_auto_scanner.paper_execution = False
            _app.state.technical_auto_scanner = technical_auto_scanner
            started = await technical_auto_scanner.start()
            _app.state.technical_auto_scanner_start = {
                "status": "started" if started else "worker_disabled"
            }
        except Exception as exc:
            technical_auto_scanner = None
            _app.state.technical_auto_scanner_start = {
                "status": "failed",
                "error": str(exc),
            }

        automation = None
        try:
            automation = current_strategy_paper_automation()
            if automation is not None:
                await automation.start()
        except Exception:
            _app.state.strategy_paper_automation_start = {"status": "unavailable"}

        try:
            yield
        finally:
            automation_drained = True
            if automation is not None:
                automation_drained = await automation.stop()
            if technical_auto_scanner is not None:
                await technical_auto_scanner.stop()
            if operations_scheduler is not None:
                stop_operations = getattr(
                    operations_scheduler,
                    "stop",
                    None,
                )
                if callable(stop_operations):
                    await stop_operations()
            if notification_summary_scheduler is not None:
                stop_summary = getattr(
                    notification_summary_scheduler,
                    "stop",
                    None,
                )
                if callable(stop_summary):
                    await stop_summary()
            if paper_monitor is not None:
                stop = getattr(paper_monitor, "stop", None)
                if callable(stop):
                    await stop()
            if paper_service is not None and automation_drained:
                close = getattr(paper_service, "close", None)
                if callable(close):
                    close()
            reporting = getattr(
                current_application(),
                "_portfolio_performance",
                None,
            )
            if reporting is not None:
                close = getattr(reporting, "close", None)
                if callable(close):
                    close()
            for attribute in (
                "_watchlist_dashboard",
                "_market_context",
                "_backtest_service",
                "_fundamental_coverage",
                "_finedge_fundamentals",
                "_fundamental_bulk_ingestion",
                "_intelligence_dashboard",
                "_institutional_sector",
                "_notification_center",
                "_notification_policy",
                "_market_day_operations",
                "_operations_reliability",
                "_strategy_runtime_state",
            ):
                if attribute == "_strategy_runtime_state" and not automation_drained:
                    continue
                service = getattr(
                    current_application(),
                    attribute,
                    None,
                )
                if service is not None:
                    close = getattr(service, "close", None)
                    if callable(close):
                        close()

    app = FastAPI(title="TrendForge Core API", version="1.0.0", lifespan=lifespan)
    app.state.application_factory = factory

    def current_strategy_paper_automation():
        method = getattr(current_application(), "strategy_paper_automation_service", None)
        if not callable(method):
            return None
        from services.multi_strategy_validation_runtime import status, start_validation

        return method(
            validation_getter=lambda: status(app),
            validation_starter=lambda: start_validation(
                app, scanner_service=current_multi_strategy_scanner_service(),
                request={"universes": ["NIFTY 100"],
                         "modes": ["intraday", "swing", "positional"], "source": "all"},
            ),
        )

    from api.paper_automation_router import paper_automation_router
    app.include_router(paper_automation_router(
        automation_getter=current_strategy_paper_automation,
        paper_getter=current_paper_trading_service,
    ))

    scan_execution_guard = ScanExecutionGuard()
    app.state.scan_execution_guard = scan_execution_guard

    @app.get("/")
    def root() -> dict[str, Any]:
        return {"service": "TrendForge Core", "status": "ok"}

    @app.api_route("/livez", methods=["GET", "HEAD"])
    async def liveness() -> dict[str, Any]:
        """Process-local liveness only; never probes external providers."""
        return {
            "status": "ok",
            "service": "TrendForge Core",
            "liveness": "process_local",
        }

    @app.get("/health")
    def health(details: bool = False) -> dict[str, Any]:
        try:
            report = current_application().health()
            if getattr(app.state, "trendforge_production_runtime", False) and not details:
                return public_health(report)
            return report
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/paper/readiness")
    def paper_readiness() -> dict[str, Any]:
        service = current_paper_trading_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Paper trading service is unavailable",
            )
        monitor = current_paper_quote_monitor()
        return {
            **service.health(),
            "restore": getattr(
                app.state,
                "paper_trading_restore",
                {"status": "not_run"},
            ),
            "automatic_monitor": (
                monitor.health()
                if monitor is not None
                else {"status": "not_supported"}
            ),
            "automatic_monitor_start": getattr(
                app.state,
                "paper_quote_monitor_start",
                {"status": "not_run"},
            ),
        }

    @app.get("/paper/auto-entry/readiness")
    def paper_auto_entry_readiness() -> dict[str, Any]:
        service = current_paper_auto_entry_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Paper auto-entry service is unavailable",
            )
        return service.health()

    @app.get("/paper/strategy-driven/readiness")
    def strategy_driven_paper_readiness() -> dict[str, Any]:
        from services.multi_strategy_validation_runtime import status

        service = current_strategy_driven_paper_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Strategy-driven paper service is unavailable",
            )
        try:
            return service.readiness(
                validation_status=status(app),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Strategy-driven paper readiness failed",
            ) from exc

    @app.post(
        "/paper/strategy-driven/preview",
        dependencies=[Depends(require_admin_api_key)],
    )
    def strategy_driven_paper_preview(
        request: StrategyDrivenPaperRequest,
    ) -> dict[str, Any]:
        from services.multi_strategy_validation_runtime import status

        service = current_strategy_driven_paper_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Strategy-driven paper service is unavailable",
            )
        try:
            return service.preview(
                **request.model_dump(),
                validation_status=status(app),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Strategy-driven paper preview failed",
            ) from exc

    @app.post(
        "/paper/strategy-driven/execute",
        dependencies=[Depends(require_admin_api_key)],
    )
    def strategy_driven_paper_execute(
        request: StrategyDrivenPaperRequest,
    ) -> dict[str, Any]:
        from services.multi_strategy_validation_runtime import status

        service = current_strategy_driven_paper_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Strategy-driven paper service is unavailable",
            )
        try:
            return service.execute(
                **request.model_dump(),
                validation_status=status(app),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Strategy-driven paper execution failed",
            ) from exc

    @app.get("/paper/strategy-monitor/readiness")
    def strategy_paper_monitor_readiness() -> dict[str, Any]:
        service = current_strategy_paper_monitor_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Strategy paper monitor is unavailable",
            )
        return service.health()

    @app.post(
        "/paper/strategy-monitor/tick",
        dependencies=[Depends(require_admin_api_key)],
    )
    def strategy_paper_monitor_tick() -> dict[str, Any]:
        service = current_strategy_paper_monitor_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Strategy paper monitor is unavailable",
            )
        try:
            return service.tick(force=True)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Strategy exit monitoring failed",
            ) from exc

    @app.get("/paper/strategy-performance")
    def strategy_paper_performance() -> dict[str, Any]:
        service = current_strategy_paper_monitor_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Strategy paper monitor is unavailable",
            )
        return service.performance()

    @app.get("/paper/strategy-trades")
    def strategy_paper_trades(
        strategy_id: str | None = Query(
            default=None,
            max_length=120,
        ),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        service = current_strategy_paper_monitor_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Strategy paper monitor is unavailable",
            )
        return service.trades(
            strategy_id,
            limit=limit,
        )

    @app.get("/paper/strategy-runtime/reconciliation")
    def strategy_runtime_reconciliation() -> dict[str, Any]:
        service = current_strategy_runtime_reconciliation_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Strategy runtime reconciliation is unavailable",
            )
        try:
            return service.reconciliation()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Strategy runtime reconciliation failed",
            ) from exc

    @app.get("/paper")
    def paper_snapshot() -> dict[str, Any]:
        service = current_paper_trading_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Paper trading service is unavailable",
            )
        return service.snapshot()

    @app.post("/paper/open")
    def paper_open(
        request: PaperOrderRequest,
    ) -> dict[str, Any]:
        service = current_paper_trading_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Paper trading service is unavailable",
            )
        try:
            return service.open(request)
        except PaperTradingStorageError as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc
        except PaperTradingDisabledError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
        except PaperTradingKillSwitchError as exc:
            raise HTTPException(
                status_code=423,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Paper trade open failed",
            ) from exc

    @app.post("/paper/monitor")
    def paper_monitor(
        request: PaperMonitorRequest,
    ) -> dict[str, Any]:
        service = current_paper_trading_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Paper trading service is unavailable",
            )
        try:
            return service.monitor(request.quotes)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Paper trade monitoring failed",
            ) from exc

    @app.get("/paper/monitor-runtime")
    def paper_monitor_runtime() -> dict[str, Any]:
        monitor = current_paper_quote_monitor()
        if monitor is None:
            raise HTTPException(
                status_code=503,
                detail="Paper quote monitor is unavailable",
            )
        return monitor.health()

    @app.post("/paper/monitor/tick")
    def paper_monitor_tick() -> dict[str, Any]:
        monitor = current_paper_quote_monitor()
        if monitor is None:
            raise HTTPException(
                status_code=503,
                detail="Paper quote monitor is unavailable",
            )
        try:
            return monitor.tick()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc

    @app.post("/paper/kill-switch")
    def paper_kill_switch(
        request: PaperKillSwitchRequest,
    ) -> dict[str, Any]:
        service = current_paper_trading_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Paper trading service is unavailable",
            )
        return service.set_runtime_kill_switch(
            request.enabled
        )

    @app.get("/portfolio")
    def portfolio_snapshot() -> dict[str, Any]:
        service = current_portfolio_performance_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Portfolio reporting service is unavailable",
            )
        try:
            return service.portfolio()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Portfolio snapshot unavailable",
            ) from exc

    @app.post("/portfolio/sync")
    def portfolio_sync() -> dict[str, Any]:
        service = current_portfolio_performance_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Portfolio reporting service is unavailable",
            )
        try:
            return service.sync_portfolio()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Portfolio synchronization failed",
            ) from exc

    @app.get("/pnl")
    def pnl_statement(
        period: str = Query(
            default="monthly",
            pattern="^(daily|weekly|monthly|yearly|all)$",
        ),
    ) -> dict[str, Any]:
        service = current_portfolio_performance_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Performance reporting service is unavailable",
            )
        try:
            return service.pnl_statement(period=period)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="P&L statement unavailable",
            ) from exc

    @app.get("/performance")
    def performance_report(
        period: str = Query(
            default="monthly",
            pattern="^(daily|weekly|monthly|yearly|all)$",
        ),
    ) -> dict[str, Any]:
        service = current_portfolio_performance_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Performance reporting service is unavailable",
            )
        try:
            return service.performance(period=period)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Performance report unavailable",
            ) from exc

    @app.get("/intelligence/readiness")
    def intelligence_readiness() -> dict[str, Any]:
        service = current_intelligence_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Intelligence service is unavailable",
            )
        return service.readiness()

    @app.get("/intelligence/events")
    def intelligence_events(
        domain: str | None = Query(default=None),
        symbol: str | None = Query(
            default=None,
            max_length=30,
        ),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        service = current_intelligence_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Intelligence service is unavailable",
            )
        try:
            return service.events(
                domain=domain,
                symbol=symbol,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.get("/intelligence/{symbol}/summary")
    def intelligence_summary(
        symbol: str,
    ) -> dict[str, Any]:
        service = current_intelligence_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Intelligence service is unavailable",
            )
        try:
            return service.summary(symbol)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.get("/intelligence/{symbol}/news")
    def intelligence_news(
        symbol: str,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        service = current_intelligence_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Intelligence service is unavailable",
            )
        try:
            return service.news(
                symbol,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.get("/intelligence/{symbol}/corporate-actions")
    def intelligence_corporate_actions(
        symbol: str,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        service = current_intelligence_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Intelligence service is unavailable",
            )
        try:
            return service.corporate_actions(
                symbol,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.post("/intelligence/refresh")
    def intelligence_refresh(
        request: IntelligenceRefreshRequest,
    ) -> dict[str, Any]:
        service = current_intelligence_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Intelligence service is unavailable",
            )
        try:
            return service.refresh(
                **request.model_dump()
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Intelligence refresh failed",
            ) from exc

    @app.get("/institutional/readiness")
    def institutional_readiness() -> dict[str, Any]:
        service = current_institutional_sector_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Institutional/sector service is unavailable",
            )
        return service.readiness()

    @app.get("/institutional")
    def institutional_latest(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        service = current_institutional_sector_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Institutional/sector service is unavailable",
            )
        return service.institutional_latest(limit=limit)

    @app.post("/institutional/refresh")
    def institutional_refresh(
        request: InstitutionalRefreshRequest,
    ) -> dict[str, Any]:
        service = current_institutional_sector_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Institutional/sector service is unavailable",
            )
        try:
            return service.refresh_institutional(
                symbols=request.symbols,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Institutional refresh failed",
            ) from exc

    @app.get("/institutional/{symbol}")
    def institutional_symbol(
        symbol: str,
    ) -> dict[str, Any]:
        service = current_institutional_sector_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Institutional/sector service is unavailable",
            )
        try:
            return service.institutional(symbol)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.get("/sector-strength")
    def sector_strength() -> dict[str, Any]:
        service = current_institutional_sector_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Institutional/sector service is unavailable",
            )
        return service.sector_strength()

    @app.post("/sector-strength/refresh")
    def sector_strength_refresh(
        request: SectorStrengthRefreshRequest,
    ) -> dict[str, Any]:
        service = current_institutional_sector_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Institutional/sector service is unavailable",
            )
        try:
            return service.refresh_sector_strength(
                **request.model_dump()
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Sector-strength refresh failed",
            ) from exc

    @app.get("/operations/readiness")
    def market_day_operations_readiness() -> dict[str, Any]:
        scheduler = current_market_day_operations_scheduler()
        if scheduler is None:
            raise HTTPException(
                status_code=503,
                detail="Market-day operations scheduler is unavailable",
            )
        return {
            **scheduler.health(),
            "startup": getattr(
                app.state,
                "market_day_operations_scheduler",
                {"status": "not_run"},
            ),
        }

    @app.get("/operations/session")
    def market_day_session() -> dict[str, Any]:
        service = current_market_day_operations_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Market-day operations service is unavailable",
            )
        try:
            return service.session()
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.get("/operations/policy")
    def market_day_operations_policy() -> dict[str, Any]:
        service = current_market_day_operations_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Market-day operations service is unavailable",
            )
        try:
            return service.policy()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Operations policy unavailable",
            ) from exc

    @app.put("/operations/policy")
    def market_day_operations_policy_update(
        request: MarketDayOperationsPolicyRequest,
    ) -> dict[str, Any]:
        service = current_market_day_operations_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Market-day operations service is unavailable",
            )
        try:
            return service.update_policy(
                request.model_dump()
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Operations policy update failed",
            ) from exc

    @app.delete("/operations/policy")
    def market_day_operations_policy_reset() -> dict[str, Any]:
        service = current_market_day_operations_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Market-day operations service is unavailable",
            )
        try:
            return service.reset_policy()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Operations policy reset failed",
            ) from exc

    @app.get("/operations/control-center")
    def market_day_operations_control_center() -> dict[str, Any]:
        service = current_market_day_operations_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Market-day operations service is unavailable",
            )
        try:
            return service.control_center()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Operations control center unavailable",
            ) from exc

    @app.get("/operations/runs")
    def market_day_operations_runs(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        service = current_market_day_operations_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Market-day operations service is unavailable",
            )
        return service.runs(limit=limit)

    @app.post("/operations/run/{operation}")
    def market_day_operations_run(
        operation: str,
        request: MarketDayOperationRunRequest,
    ) -> dict[str, Any]:
        service = current_market_day_operations_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Market-day operations service is unavailable",
            )
        try:
            return service.run(
                operation,
                force=request.force,
                scheduled=False,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Market-day operation failed",
            ) from exc

    @app.post("/operations/tick")
    def market_day_operations_tick() -> dict[str, Any]:
        scheduler = current_market_day_operations_scheduler()
        if scheduler is None:
            raise HTTPException(
                status_code=503,
                detail="Market-day operations scheduler is unavailable",
            )
        try:
            return scheduler.tick()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Market-day operations tick failed",
            ) from exc

    @app.get("/operations/external-scheduler/readiness")
    def external_scheduler_readiness() -> dict[str, Any]:
        return {
            **scheduler_security_health(),
            "endpoint": "/operations/external-tick",
            "audit_endpoint": "/operations/external-audit",
            "reliability_endpoint": "/operations/reliability",
            "status_endpoint": (
                "/operations/external-scheduler/status"
            ),
            "expected_operations": ["morning", "eod"],
            "timezone": "Asia/Kolkata",
            "broker_orders_allowed": False,
        }

    @app.get("/operations/external-scheduler/status")
    def external_scheduler_status(
        operation: str = Query(
            pattern="^(morning|eod)$",
        ),
    ) -> dict[str, Any]:
        service = current_market_day_operations_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Market-day operations service is unavailable",
            )
        try:
            return service.external_contract(operation)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="External scheduler status unavailable",
            ) from exc

    @app.post("/operations/external-tick")
    def external_scheduler_tick(
        request: ExternalOperationsTickRequest,
        x_trendforge_scheduler_key: str | None = Header(
            default=None,
            alias=SCHEDULER_API_KEY_HEADER,
        ),
    ) -> dict[str, Any]:
        validate_scheduler_api_key(
            x_trendforge_scheduler_key
        )
        scheduler = current_market_day_operations_scheduler()
        service = current_market_day_operations_service()
        if scheduler is None or service is None:
            raise HTTPException(
                status_code=503,
                detail="Market-day external scheduler is unavailable",
            )

        try:
            before = service.external_contract(
                request.expected_operation
            )
            tick = scheduler.tick(external=True)
            after = service.external_contract(
                request.expected_operation
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="External operations tick failed",
            ) from exc

        expected_tick = (
            tick.get("operations", {}).get(
                request.expected_operation
            )
            if isinstance(
                tick.get("operations"),
                dict,
            )
            else None
        )
        audit_record = None
        reliability = current_operations_reliability_service()
        if reliability is not None:
            try:
                audit_record = reliability.record_external_tick(
                    operation=request.expected_operation,
                    before=before,
                    tick=tick,
                    after=after,
                )
            except Exception as exc:
                audit_record = {
                    "status": "failed",
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }

        return {
            "status": after.get("status"),
            "expected_operation": (
                request.expected_operation
            ),
            "auth_scope": (
                "operations_external_tick_only"
            ),
            "before": before,
            "tick": tick,
            "expected_tick": expected_tick,
            "after": after,
            "audit_record": audit_record,
            "broker_orders_allowed": False,
        }

    @app.get("/operations/reliability")
    def operations_reliability(
        days: int = Query(default=30, ge=1, le=90),
    ) -> dict[str, Any]:
        service = current_operations_reliability_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Operations reliability service is unavailable",
            )
        try:
            return service.reliability(days=days)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Operations reliability unavailable",
            ) from exc

    @app.get("/operations/audit")
    def operations_audit_history(
        limit: int = Query(default=100, ge=1, le=300),
        operation: str | None = Query(
            default=None,
            pattern="^(morning|eod)$",
        ),
    ) -> dict[str, Any]:
        service = current_operations_reliability_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Operations reliability service is unavailable",
            )
        try:
            return service.history(
                limit=limit,
                operation=operation,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.post("/operations/audit/run")
    def operations_audit_run(
        request: OperationsAuditRunRequest,
    ) -> dict[str, Any]:
        service = current_operations_reliability_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Operations reliability service is unavailable",
            )
        try:
            if request.operation:
                return service.audit(
                    request.operation,
                    trigger_source="admin_manual",
                    strict=False,
                    deliver_alerts=request.deliver_alerts,
                )
            return service.audit_all(
                trigger_source="admin_manual",
                strict=False,
                deliver_alerts=request.deliver_alerts,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Operations audit failed",
            ) from exc

    @app.post("/operations/external-audit")
    def external_operations_audit(
        request: ExternalOperationsTickRequest,
        x_trendforge_scheduler_key: str | None = Header(
            default=None,
            alias=SCHEDULER_API_KEY_HEADER,
        ),
    ) -> dict[str, Any]:
        validate_scheduler_api_key(
            x_trendforge_scheduler_key
        )
        service = current_operations_reliability_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Operations reliability service is unavailable",
            )
        try:
            result = service.audit(
                request.expected_operation,
                trigger_source="external_post_window",
                strict=True,
                deliver_alerts=True,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="External operations audit failed",
            ) from exc
        return {
            **result,
            "auth_scope": "operations_external_tick_only",
            "broker_orders_allowed": False,
        }

    @app.get("/notifications/readiness")
    def notification_readiness() -> dict[str, Any]:
        service = current_notification_center_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Notification Center is unavailable",
            )
        return service.readiness()

    @app.get("/notifications/producers")
    def notification_producers() -> dict[str, Any]:
        service = best_effort_notification_producer()
        if service is None:
            return {
                "status": "not_supported",
                "best_effort": True,
            }
        return service.health()

    @app.get("/notifications/policy")
    def notification_policy() -> dict[str, Any]:
        service = current_notification_policy_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Notification policy service is unavailable",
            )
        try:
            return service.current()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Notification policy unavailable",
            ) from exc

    @app.put("/notifications/policy")
    def notification_policy_update(
        request: NotificationPolicyRequest,
    ) -> dict[str, Any]:
        service = current_notification_policy_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Notification policy service is unavailable",
            )
        try:
            payload = request.model_dump()
            return service.update(payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Notification policy update failed",
            ) from exc

    @app.delete("/notifications/policy")
    def notification_policy_reset() -> dict[str, Any]:
        service = current_notification_policy_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Notification policy service is unavailable",
            )
        try:
            return service.reset()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Notification policy reset failed",
            ) from exc

    @app.get("/notifications/daily-summary/readiness")
    def notification_daily_summary_readiness() -> dict[str, Any]:
        scheduler = current_notification_summary_scheduler()
        if scheduler is None:
            raise HTTPException(
                status_code=503,
                detail="Notification daily summary scheduler is unavailable",
            )
        return {
            **scheduler.health(),
            "startup": getattr(
                app.state,
                "notification_summary_scheduler",
                {"status": "not_run"},
            ),
        }

    @app.get("/notifications/daily-summary/preview")
    def notification_daily_summary_preview(
        summary_date: str | None = Query(
            default=None,
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ) -> dict[str, Any]:
        service = current_notification_daily_summary_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Notification daily summary service is unavailable",
            )
        try:
            return service.preview(
                summary_date=summary_date,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Daily summary preview unavailable",
            ) from exc

    @app.post("/notifications/daily-summary/send")
    def notification_daily_summary_send(
        request: NotificationDailySummarySendRequest,
    ) -> dict[str, Any]:
        service = current_notification_daily_summary_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Notification daily summary service is unavailable",
            )
        try:
            return service.send(
                summary_date=request.summary_date,
                force=request.force,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Daily Discord summary failed",
            ) from exc

    @app.get("/notifications/summary")
    def notification_summary() -> dict[str, Any]:
        service = current_notification_center_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Notification Center is unavailable",
            )
        return service.summary()

    @app.get("/notifications/events")
    def notification_events(
        limit: int = Query(default=100, ge=1, le=500),
        category: str | None = Query(default=None, max_length=40),
        status: str | None = Query(default=None, max_length=20),
        symbol: str | None = Query(default=None, max_length=30),
    ) -> dict[str, Any]:
        service = current_notification_center_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Notification Center is unavailable",
            )
        try:
            return service.events(
                limit=limit,
                category=category,
                status=status,
                symbol=symbol,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.get("/notifications/events/{event_id}")
    def notification_event_detail(
        event_id: str,
    ) -> dict[str, Any]:
        service = current_notification_center_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Notification Center is unavailable",
            )
        from services.notification_center_service import (
            NotificationEventNotFoundError,
        )

        try:
            return service.get(event_id)
        except NotificationEventNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Notification event not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.post("/notifications/events")
    def route_notification_event(
        request: NotificationEventRequest,
    ) -> dict[str, Any]:
        service = current_notification_center_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Notification Center is unavailable",
            )
        try:
            return service.route_event(
                **request.model_dump()
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Notification routing failed",
            ) from exc

    @app.post("/notifications/test")
    def notification_test() -> dict[str, Any]:
        service = current_notification_center_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Notification Center is unavailable",
            )
        try:
            return service.test_delivery()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Discord test delivery failed",
            ) from exc

    @app.get("/technical/strategies")
    def technical_strategies(
        mode: str | None = Query(default=None, max_length=20),
        source: str | None = Query(default=None, max_length=40),
    ) -> dict[str, Any]:
        from scanner.strategy_registry import (
            REGISTRY_VERSION,
            list_strategies,
            registry_readiness,
        )

        rows = list_strategies(mode=mode, source=source)
        return {
            "status": "ready",
            "version": REGISTRY_VERSION,
            "filters": {
                "mode": mode,
                "source": source,
            },
            "count": len(rows),
            "strategies": rows,
            "readiness": registry_readiness(),
        }

    @app.get("/technical/strategies/{strategy_id}")
    def technical_strategy_detail(
        strategy_id: str,
    ) -> dict[str, Any]:
        from scanner.strategy_registry import (
            REGISTRY_VERSION,
            get_strategy,
        )

        try:
            strategy = get_strategy(strategy_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=str(exc),
            ) from exc
        return {
            "status": "ready",
            "version": REGISTRY_VERSION,
            "strategy": strategy,
        }

    @app.get("/technical/multi-strategy/readiness")
    def multi_strategy_readiness() -> dict[str, Any]:
        service = current_multi_strategy_scanner_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Multi-strategy scanner is unavailable",
            )
        try:
            return service.readiness()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Multi-strategy scanner readiness failed",
            ) from exc

    @app.get("/technical/multi-strategy/results")
    def multi_strategy_results() -> dict[str, Any]:
        """Read last completed results; this endpoint NEVER triggers a scan."""
        service = current_multi_strategy_scanner_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Multi-strategy scanner is unavailable",
            )
        return service.results()

    @app.get("/technical/multi-strategy/status")
    def multi_strategy_status() -> dict[str, Any]:
        service = current_multi_strategy_scanner_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Multi-strategy scanner is unavailable",
            )
        return service.status()

    @app.post(
        "/technical/multi-strategy/run",
        dependencies=[Depends(require_admin_api_key)],
    )
    def multi_strategy_run(
        request: MultiStrategyScanRequest,
    ) -> dict[str, Any]:
        service = current_multi_strategy_scanner_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Multi-strategy scanner is unavailable",
            )
        try:
            return service.trigger(**request.model_dump())
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Multi-strategy scan start failed",
            ) from exc

    @app.get("/technical/multi-strategy/validation/readiness")
    def multi_strategy_validation_readiness() -> dict[str, Any]:
        from services.multi_strategy_validation_runtime import status
        from services.multi_strategy_validation_service import (
            MultiStrategyValidationService,
        )

        service = current_multi_strategy_scanner_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Multi-strategy scanner is unavailable",
            )
        try:
            readiness = MultiStrategyValidationService(
                scanner_service=service,
            ).readiness()
            readiness["runtime"] = status(app)
            return readiness
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Multi-strategy validation readiness failed",
            ) from exc

    @app.get("/technical/multi-strategy/validation/status")
    def multi_strategy_validation_status() -> dict[str, Any]:
        from services.multi_strategy_validation_runtime import status

        return status(app)

    @app.post(
        "/technical/multi-strategy/validation/run",
        dependencies=[Depends(require_admin_api_key)],
    )
    def multi_strategy_validation_run(
        request: MultiStrategyValidationRequest,
    ) -> dict[str, Any]:
        from services.multi_strategy_validation_runtime import (
            start_validation,
        )

        service = current_multi_strategy_scanner_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Multi-strategy scanner is unavailable",
            )
        try:
            return start_validation(
                app,
                scanner_service=service,
                request=request.model_dump(),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Multi-strategy validation start failed",
            ) from exc

    @app.get(
        "/technical/multi-strategy/validation/export",
        dependencies=[Depends(require_admin_api_key)],
    )
    def multi_strategy_validation_export():
        from services.multi_strategy_validation_runtime import (
            output_path,
        )

        path = output_path()
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail="R72.5.3 validation export is not available",
            )
        return FileResponse(
            path,
            media_type="application/json",
            filename="trendforge_r7253_multi_strategy_validation.json",
        )

    @app.get("/technical/readiness")
    def technical_readiness() -> dict[str, Any]:
        service = current_technical_trading_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Technical trading service is unavailable",
            )
        try:
            return service.readiness()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Technical trading readiness failed",
            ) from exc

    @app.post("/technical/scan")
    def technical_scan(
        request: TechnicalScanRequest,
    ) -> dict[str, Any]:
        service = current_technical_trading_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Technical trading service is unavailable",
            )
        try:
            from scanner.workspace_strategies import strategy_choices
            parameters = request.model_dump()
            parameters["strategy_id"] = parameters.get("strategy_id") or next(iter(strategy_choices(request.mode).values()))
            return service.scan(**parameters)
        except TechnicalTradingValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Technical scan failed",
            ) from exc

    @app.post("/technical/backtest")
    def technical_backtest(
        request: TechnicalBacktestRequest,
    ) -> dict[str, Any]:
        service = current_technical_trading_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Technical trading service is unavailable",
            )
        try:
            from scanner.workspace_strategies import strategy_choices
            parameters = request.model_dump()
            parameters["strategy_id"] = parameters.get("strategy_id") or next(iter(strategy_choices(request.mode).values()))
            return service.backtest(**parameters)
        except TechnicalTradingValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Technical backtest failed",
            ) from exc

    @app.get("/technical/validation/readiness")
    def technical_validation_readiness() -> dict[str, Any]:
        from services.technical_validation_runtime import status
        from services.technical_validation_service import (
            TechnicalValidationService,
        )

        return {
            "status": "ready",
            "version": TechnicalValidationService.VERSION,
            "universes": list(TechnicalValidationService.UNIVERSES),
            "data_policy": "kite_only",
            "fundamentals_used": False,
            "enrichment_used": False,
            "broker_orders_allowed": False,
            "paper_orders_created": False,
            "realism": {
                "atr_bracket_execution": True,
                "same_bar_priority": "stop",
                "intraday_forced_exit_ist": "15:00",
                "mode_assumptions": (
                    TechnicalValidationService.DEFAULT_MODE_ASSUMPTIONS
                ),
            },
            "runtime": status(app),
        }

    @app.get("/technical/validation/status")
    def technical_validation_status() -> dict[str, Any]:
        from services.technical_validation_runtime import status
        return status(app)

    @app.post("/technical/validation/run")
    def technical_validation_run(
        request: TechnicalValidationRequest,
    ) -> dict[str, Any]:
        from services.technical_validation_runtime import start_validation

        service = current_technical_trading_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Technical trading service is unavailable",
            )
        return start_validation(
            app,
            technical_service=service,
            capital=request.capital,
            chunk_size=request.chunk_size,
            force=request.force,
        )

    @app.get("/technical/validation/export", dependencies=[Depends(require_admin_api_key)])
    def technical_validation_export():
        from services.technical_validation_runtime import output_path

        path = output_path()
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail="R71.5 validation export is not available",
            )
        return FileResponse(
            path,
            media_type="application/json",
            filename="trendforge_r715_validation.json",
        )

    @app.get("/backtests/readiness")
    def backtest_readiness() -> dict[str, Any]:
        service = current_backtest_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Backtest service is unavailable",
            )
        return service.readiness()

    @app.get("/backtests")
    def backtest_history(
        limit: int = Query(default=50, ge=1, le=500),
        symbol: str | None = Query(default=None, max_length=30),
    ) -> dict[str, Any]:
        service = current_backtest_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Backtest service is unavailable",
            )
        try:
            return service.history(
                limit=limit,
                symbol=symbol,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.post("/backtests")
    def run_backtest(
        request: BacktestRunRequest,
    ) -> dict[str, Any]:
        service = current_backtest_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Backtest service is unavailable",
            )
        from services.backtest_service import BacktestBusyError

        try:
            return service.run(
                **request.model_dump()
            )
        except BacktestBusyError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Backtest execution failed",
            ) from exc

    @app.get("/backtests/{run_id}")
    def backtest_detail(
        run_id: str,
    ) -> dict[str, Any]:
        service = current_backtest_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Backtest service is unavailable",
            )
        from services.backtest_service import BacktestNotFoundError

        try:
            return service.get(run_id)
        except BacktestNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.get("/watchlists")
    def watchlists_summary() -> dict[str, Any]:
        service = current_watchlist_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Watchlist service is unavailable",
            )
        return service.summary()

    @app.get("/watchlists/{name}")
    def watchlist_detail(
        name: str,
    ) -> dict[str, Any]:
        service = current_watchlist_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Watchlist service is unavailable",
            )
        try:
            return service.get(name)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.post("/watchlists/{name}/symbols")
    def watchlist_upsert(
        name: str,
        request: WatchlistEntryRequest,
    ) -> dict[str, Any]:
        service = current_watchlist_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Watchlist service is unavailable",
            )
        try:
            return service.upsert(
                name,
                **request.model_dump(),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.put("/watchlists/{name}/symbols/{symbol}")
    def watchlist_update(
        name: str,
        symbol: str,
        request: WatchlistUpdateRequest,
    ) -> dict[str, Any]:
        service = current_watchlist_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Watchlist service is unavailable",
            )
        try:
            fields = request.model_dump(
                exclude_none=True
            )
            return service.update(
                name,
                symbol,
                **fields,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.delete("/watchlists/{name}/symbols/{symbol}")
    def watchlist_remove(
        name: str,
        symbol: str,
    ) -> dict[str, Any]:
        service = current_watchlist_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Watchlist service is unavailable",
            )
        try:
            return service.remove(
                name,
                symbol,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.delete("/watchlists/{name}")
    def watchlist_delete(
        name: str,
    ) -> dict[str, Any]:
        service = current_watchlist_dashboard_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Watchlist service is unavailable",
            )
        try:
            return service.delete(name)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.get("/market/breadth")
    def market_breadth_snapshot() -> dict[str, Any]:
        service = current_market_context_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Market context service is unavailable",
            )
        return service.snapshot("breadth")

    @app.get("/market/regime")
    def market_regime_snapshot() -> dict[str, Any]:
        service = current_market_context_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Market context service is unavailable",
            )
        return service.snapshot("regime")

    @app.post("/market/context/refresh")
    def market_context_refresh(
        request: MarketContextRefreshRequest,
    ) -> dict[str, Any]:
        service = current_market_context_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Market context service is unavailable",
            )
        try:
            return service.refresh(
                **request.model_dump()
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Market context refresh failed",
            ) from exc

    @app.get("/observability/scan-runtime")
    def scan_runtime_status() -> dict[str, Any]:
        return scan_execution_guard.status()

    @app.get("/fundamentals/template.csv")
    def fundamentals_template_csv() -> Response:
        try:
            content = current_fundamental_manager().template_csv()
            return Response(
                content=content,
                media_type="text/csv",
                headers={
                    "Content-Disposition":
                    'attachment; filename="trendforge_fundamentals_template.csv"'
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/fundamentals/template.xlsx")
    def fundamentals_template_xlsx() -> Response:
        try:
            content = current_fundamental_manager().template_xlsx()
            return Response(
                content=content,
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                headers={
                    "Content-Disposition":
                    'attachment; filename="trendforge_fundamentals_template.xlsx"'
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/fundamentals/upload")
    async def upload_fundamentals(
        file: UploadFile = File(...),
        source: str = Form(default="manual_upload"),
        symbol_column: str | None = Form(default=None),
        field_map: str | None = Form(default=None),
        sheet: str = Form(default="0"),
        as_of: str | None = Form(default=None),
    ) -> dict[str, Any]:
        filename = Path(file.filename or "").name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xlsm"}:
            raise HTTPException(
                status_code=422,
                detail="Fundamentals upload must be CSV, XLSX or XLSM",
            )

        payload = await file.read(MAX_FUNDAMENTAL_UPLOAD_BYTES + 1)
        if len(payload) > MAX_FUNDAMENTAL_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Fundamentals upload exceeds 10 MB",
            )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=suffix,
                delete=False,
            ) as handle:
                handle.write(payload)
                temporary_path = Path(handle.name)

            return current_fundamental_manager().import_file(
                temporary_path,
                source=source,
                symbol_column=symbol_column,
                field_map=field_map,
                sheet_name=sheet,
                as_of=as_of,
                source_file_name=filename,
            )
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @app.get("/fundamentals/readiness")
    def fundamentals_readiness(
        refresh_universe: bool = False,
        incomplete_only: bool = False,
        limit: int = Query(default=5000, ge=1, le=5000),
    ) -> dict[str, Any]:
        service = current_fundamental_coverage_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Fundamental coverage service is unavailable",
            )
        try:
            return service.report(
                refresh_universe=refresh_universe,
                incomplete_only=incomplete_only,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/fundamentals/bulk/readiness")
    def fundamentals_bulk_readiness() -> dict[str, Any]:
        service = current_fundamental_bulk_ingestion_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Fundamental bulk ingestion service is unavailable",
            )
        return service.readiness()

    @app.get("/fundamentals/bulk/runs")
    def fundamentals_bulk_runs(
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        service = current_fundamental_bulk_ingestion_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Fundamental bulk ingestion service is unavailable",
            )
        try:
            rows = service.history(limit=limit)
            return {
                "version": service.VERSION,
                "count": len(rows),
                "runs": rows,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/fundamentals/bulk/runs/{run_id}")
    def fundamentals_bulk_run(run_id: str) -> dict[str, Any]:
        service = current_fundamental_bulk_ingestion_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Fundamental bulk ingestion service is unavailable",
            )
        try:
            result = service.get(run_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Fundamental bulk ingestion run not found",
            )
        return result

    @app.post("/fundamentals/bulk/upload")
    async def upload_fundamental_bulk(
        file: UploadFile = File(...),
        run_id: str | None = Form(default=None),
        stage_size: int = Form(default=25),
        apply: bool = Form(default=False),
        source: str | None = Form(default=None),
        as_of: str | None = Form(default=None),
        sheet: str = Form(default="Completion"),
    ) -> dict[str, Any]:
        filename = Path(file.filename or "").name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xlsm"}:
            raise HTTPException(
                status_code=422,
                detail="Bulk fundamentals upload must be CSV, XLSX or XLSM",
            )

        payload = await file.read(MAX_FUNDAMENTAL_UPLOAD_BYTES + 1)
        if len(payload) > MAX_FUNDAMENTAL_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Bulk fundamentals upload exceeds 10 MB",
            )

        service = current_fundamental_bulk_ingestion_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Fundamental bulk ingestion service is unavailable",
            )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=suffix,
                delete=False,
            ) as handle:
                handle.write(payload)
                temporary_path = Path(handle.name)

            return service.process_file(
                temporary_path,
                run_id=run_id,
                stage_size=stage_size,
                apply=apply,
                source=source,
                as_of=as_of,
                sheet_name=sheet,
                source_file_name=filename,
            )
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @app.get("/fundamentals/completion.csv")
    def fundamentals_completion_csv() -> Response:
        try:
            content = current_fundamental_completion_service().completion_csv()
            return Response(
                content=content,
                media_type="text/csv",
                headers={
                    "Content-Disposition":
                    'attachment; filename="trendforge_fundamental_completion.csv"'
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/fundamentals/completion.xlsx")
    def fundamentals_completion_xlsx() -> Response:
        try:
            content = current_fundamental_completion_service().completion_xlsx()
            return Response(
                content=content,
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                headers={
                    "Content-Disposition":
                    'attachment; filename="trendforge_fundamental_completion.xlsx"'
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/fundamentals/completion/upload")
    async def upload_fundamental_completion(
        file: UploadFile = File(...),
        apply: bool = Form(default=False),
        source: str | None = Form(default=None),
        as_of: str | None = Form(default=None),
        sheet: str = Form(default="Completion"),
    ) -> dict[str, Any]:
        filename = Path(file.filename or "").name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xlsm"}:
            raise HTTPException(
                status_code=422,
                detail="Completion upload must be CSV, XLSX or XLSM",
            )

        payload = await file.read(MAX_FUNDAMENTAL_UPLOAD_BYTES + 1)
        if len(payload) > MAX_FUNDAMENTAL_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Completion upload exceeds 10 MB",
            )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=suffix,
                delete=False,
            ) as handle:
                handle.write(payload)
                temporary_path = Path(handle.name)

            return current_fundamental_completion_service().process_file(
                temporary_path,
                apply=apply,
                source=source,
                as_of=as_of,
                sheet_name=sheet,
                source_file_name=filename,
            )
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @app.get("/fundamentals/{symbol}/evidence")
    def fundamental_completion_evidence(
        symbol: str,
        limit: int = Query(default=500, ge=1, le=2000),
    ) -> dict[str, Any]:
        try:
            return current_fundamental_completion_service().evidence(
                symbol,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/fundamentals/{symbol}/history")
    def fundamental_completion_history(
        symbol: str,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        try:
            return {
                "symbol": symbol.strip().upper(),
                "history": current_fundamental_completion_service().history(
                    symbol,
                    limit=limit,
                ),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/fundamentals")
    def fundamentals_report(
        limit: int = Query(default=1000, ge=1, le=5000),
        incomplete_only: bool = False,
        stale_only: bool = False,
    ) -> dict[str, Any]:
        try:
            return current_fundamental_manager().report(
                limit=limit,
                incomplete_only=incomplete_only,
                stale_only=stale_only,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Register source routes before the generic fundamental symbol route.
    from api.finedge_router import attach_finedge_routes

    def current_finedge_fundamental_service():
        getter = getattr(current_application(), "finedge_fundamental_service", None)
        return getter() if callable(getter) else None

    attach_finedge_routes(app, service_getter=current_finedge_fundamental_service)

    @app.get("/fundamentals/{symbol}")
    def fundamental_by_symbol(symbol: str) -> dict[str, Any]:
        try:
            result = current_fundamental_manager().inspect(symbol)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="Fundamentals not found")
        return result

    @app.put("/fundamentals/{symbol}")
    def update_fundamental(
        symbol: str,
        request: FundamentalUpdateRequest,
    ) -> dict[str, Any]:
        values = request.model_dump(
            exclude={"source", "as_of"},
            exclude_none=True,
        )
        try:
            return current_fundamental_manager().upsert(
                symbol,
                values,
                source=request.source,
                as_of=request.as_of,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/universe/nifty500")
    def nifty500_universe(
        refresh: bool = False,
        include_members: bool = False,
    ) -> dict[str, Any]:
        try:
            universe = current_nifty500_universe()
            universe.ensure_loaded(refresh=refresh)
            return universe.report(include_members=include_members)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/scan/universe/nifty500")
    def scan_nifty500(
        request: Nifty500ScanRequest,
        run_id: str | None = Query(default=None, max_length=128),
        continuation_token: str | None = Query(
            default=None,
            max_length=256,
        ),
    ) -> dict[str, Any]:
        scan_run_id = str(run_id or uuid4()).strip()
        audit_service = current_scan_run_audit_service()
        continuation_service = current_scan_continuation_service()
        source_continuation: dict[str, Any] | None = None
        resume_symbols: list[str] = []

        if audit_service is not None:
            try:
                audit_service.ensure_available(scan_run_id)
            except DuplicateScanRunIdError as exc:
                existing = audit_service.get(scan_run_id)
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "scan run_id already exists",
                        "run_id": scan_run_id,
                        "existing_outcome": (
                            existing.get("outcome")
                            if isinstance(existing, dict)
                            else None
                        ),
                    },
                ) from exc

        def audit_continuation_rejection(
            *,
            status_code: int,
            failure_stage: str,
            failure_message: str,
            record: dict[str, Any] | None,
        ) -> None:
            if audit_service is None:
                return
            now = datetime.now(timezone.utc)
            audit_service.record(
                {
                    "run_id": scan_run_id,
                    "scan_type": "nifty500",
                    "outcome": "rejected",
                    "http_status": status_code,
                    "failure_stage": failure_stage,
                    "failure_message": failure_message,
                    "started_at": now.isoformat(),
                    "finished_at": now.isoformat(),
                    "duration_sec": 0.0,
                    "requested_symbols": len(
                        (record or {}).get("symbols") or []
                    ),
                    "completed_symbols": 0,
                    "error_symbols": 0,
                    "missing_symbols": 0,
                    "enrichment_failures": 0,
                    "execution_errors": 0,
                    "full_universe": False,
                    "source_security_count": None,
                    "tradable_security_count": None,
                    "provider_counts": {},
                    "fallback_count": 0,
                    "nse_resolution_count": 0,
                    "error_details": {},
                    "metadata": {
                        "is_continuation": True,
                        "parent_run_id": (
                            (record or {}).get("parent_run_id")
                        ),
                        "lineage_root_run_id": (
                            (record or {}).get(
                                "lineage_root_run_id"
                            )
                        ),
                        "continuation_generation": (
                            (record or {}).get("generation")
                        ),
                        "continuation_status": (
                            (record or {}).get("status")
                        ),
                        "existing_child_run_id": (
                            (record or {}).get("child_run_id")
                        ),
                        "expires_at": (
                            (record or {}).get("expires_at")
                        ),
                        "claim_attempts": int(
                            (record or {}).get(
                                "claim_attempts",
                                0,
                            )
                            or 0
                        ),
                        "max_claim_attempts": int(
                            (record or {}).get(
                                "max_claim_attempts",
                                0,
                            )
                            or 0
                        ),
                    },
                }
            )

        if continuation_token is not None:
            if continuation_service is None:
                raise HTTPException(
                    status_code=503,
                    detail="Scan continuation service is unavailable",
                )
            try:
                source_continuation = continuation_service.inspect(
                    continuation_token
                )
            except ContinuationNotFoundError as exc:
                raise HTTPException(
                    status_code=404,
                    detail="Scan continuation token not found",
                ) from exc
            except ContinuationExpiredError as exc:
                record = None
                try:
                    record = continuation_service.inspect_any(
                        continuation_token
                    )
                except ContinuationNotFoundError:
                    pass
                audit_continuation_rejection(
                    status_code=410,
                    failure_stage="continuation_expiry",
                    failure_message=str(exc),
                    record=record,
                )
                raise HTTPException(
                    status_code=410,
                    detail="Scan continuation token has expired",
                ) from exc
            except ContinuationAttemptLimitError as exc:
                record = None
                try:
                    record = continuation_service.inspect_any(
                        continuation_token
                    )
                except ContinuationNotFoundError:
                    pass
                audit_continuation_rejection(
                    status_code=410,
                    failure_stage="continuation_attempt_limit",
                    failure_message=str(exc),
                    record=record,
                )
                raise HTTPException(
                    status_code=410,
                    detail=(
                        "Scan continuation claim limit exhausted"
                    ),
                ) from exc

            if source_continuation.get("status") != "pending":
                audit_continuation_rejection(
                    status_code=409,
                    failure_stage="continuation_validation",
                    failure_message=(
                        "Scan continuation token is not pending"
                    ),
                    record=source_continuation,
                )
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": (
                            "Scan continuation token is not pending"
                        ),
                        "status": source_continuation.get("status"),
                        "child_run_id": source_continuation.get(
                            "child_run_id"
                        ),
                    },
                )

            resume_symbols = [
                str(symbol).strip().upper()
                for symbol in (
                    source_continuation.get("symbols") or []
                )
                if str(symbol).strip()
            ]
            if not resume_symbols:
                raise HTTPException(
                    status_code=409,
                    detail="Scan continuation has no deferred symbols",
                )

            stored_request = dict(
                source_continuation.get("request") or {}
            )
            updates: dict[str, Any] = {
                "period": stored_request.get(
                    "period",
                    request.period,
                ),
                "interval": stored_request.get(
                    "interval",
                    request.interval,
                ),
                "capital": stored_request.get(
                    "capital",
                    request.capital,
                ),
                "top_n": stored_request.get(
                    "top_n",
                    request.top_n,
                ),
                "limit": len(resume_symbols),
                "full_universe": False,
                "refresh_universe": False,
            }
            for field_name in (
                "batch_size",
                "batch_pause_seconds",
                "scan_time_budget_seconds",
                "batch_time_budget_seconds",
                "compact",
            ):
                if (
                    field_name not in request.model_fields_set
                    and field_name in stored_request
                ):
                    updates[field_name] = stored_request[field_name]

            request = request.model_copy(update=updates)

        if not scan_execution_guard.try_start(scan_run_id):
            state = scan_execution_guard.status()
            active = state.get("active")
            active_run_id = (
                active.get("run_id")
                if isinstance(active, dict)
                else None
            )
            now = datetime.now(timezone.utc)
            if (
                audit_service is not None
                and active_run_id != scan_run_id
            ):
                try:
                    audit_service.record(
                        {
                            "run_id": scan_run_id,
                            "scan_type": "nifty500",
                            "outcome": "rejected",
                            "http_status": 409,
                            "failure_stage": "admission",
                            "failure_message": (
                                "Another NIFTY 500 universe scan is "
                                "already running"
                            ),
                            "started_at": now.isoformat(),
                            "finished_at": now.isoformat(),
                            "duration_sec": 0.0,
                            "requested_symbols": (
                                len(resume_symbols)
                                if continuation_token
                                else 500
                                if request.full_universe
                                else request.limit
                            ),
                            "completed_symbols": 0,
                            "error_symbols": 0,
                            "missing_symbols": 0,
                            "enrichment_failures": 0,
                            "execution_errors": 0,
                            "full_universe": request.full_universe,
                            "source_security_count": None,
                            "tradable_security_count": None,
                            "provider_counts": {},
                            "fallback_count": 0,
                            "nse_resolution_count": 0,
                            "error_details": {},
                            "metadata": {
                                "period": request.period,
                                "interval": request.interval,
                                "batch_size": request.batch_size,
                                "batch_pause_seconds": (
                                    request.batch_pause_seconds
                                ),
                                "active_run_id": (
                                    active.get("run_id")
                                    if isinstance(active, dict)
                                    else None
                                ),
                                "continuation_requested": bool(
                                    continuation_token
                                ),
                                "parent_run_id": (
                                    source_continuation.get(
                                        "parent_run_id"
                                    )
                                    if source_continuation
                                    else None
                                ),
                                "lineage_root_run_id": (
                                    source_continuation.get(
                                        "lineage_root_run_id"
                                    )
                                    if source_continuation
                                    else None
                                ),
                                "continuation_generation": (
                                    source_continuation.get(
                                        "generation"
                                    )
                                    if source_continuation
                                    else None
                                ),
                            },
                        }
                    )
                except DuplicateScanRunIdError:
                    pass

            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "Another NIFTY 500 universe scan is already running"
                    ),
                    "run_id": scan_run_id,
                    "active": active,
                    "duplicate_active_run_id": (
                        active_run_id == scan_run_id
                    ),
                },
                headers={"Retry-After": "15"},
            )

        if continuation_token is not None:
            try:
                source_continuation = continuation_service.claim(
                    continuation_token,
                    scan_run_id,
                )
            except ContinuationNotFoundError as exc:
                scan_execution_guard.finish(
                    scan_run_id,
                    "rejected",
                )
                raise HTTPException(
                    status_code=404,
                    detail="Scan continuation token not found",
                ) from exc
            except (
                ContinuationExpiredError,
                ContinuationAttemptLimitError,
            ) as exc:
                scan_execution_guard.finish(
                    scan_run_id,
                    "rejected",
                )
                record = None
                try:
                    record = continuation_service.inspect_any(
                        continuation_token
                    )
                except ContinuationNotFoundError:
                    pass
                is_expired = isinstance(
                    exc,
                    ContinuationExpiredError,
                )
                audit_continuation_rejection(
                    status_code=410,
                    failure_stage=(
                        "continuation_expiry"
                        if is_expired
                        else "continuation_attempt_limit"
                    ),
                    failure_message=str(exc),
                    record=record,
                )
                raise HTTPException(
                    status_code=410,
                    detail=(
                        "Scan continuation token has expired"
                        if is_expired
                        else "Scan continuation claim limit exhausted"
                    ),
                ) from exc
            except ContinuationUnavailableError as exc:
                scan_execution_guard.finish(
                    scan_run_id,
                    "rejected",
                )
                now = datetime.now(timezone.utc)
                if audit_service is not None:
                    try:
                        audit_service.record(
                            {
                                "run_id": scan_run_id,
                                "scan_type": "nifty500",
                                "outcome": "rejected",
                                "http_status": 409,
                                "failure_stage": (
                                    "continuation_admission"
                                ),
                                "failure_message": str(exc),
                                "started_at": now.isoformat(),
                                "finished_at": now.isoformat(),
                                "duration_sec": 0.0,
                                "requested_symbols": len(
                                    resume_symbols
                                ),
                                "completed_symbols": 0,
                                "error_symbols": 0,
                                "missing_symbols": 0,
                                "enrichment_failures": 0,
                                "execution_errors": 0,
                                "full_universe": False,
                                "source_security_count": None,
                                "tradable_security_count": None,
                                "provider_counts": {},
                                "fallback_count": 0,
                                "nse_resolution_count": 0,
                                "error_details": {},
                                "metadata": {
                                    "continuation_requested": True,
                                    "parent_run_id": (
                                        source_continuation.get(
                                            "parent_run_id"
                                        )
                                        if source_continuation
                                        else None
                                    ),
                                    "lineage_root_run_id": (
                                        source_continuation.get(
                                            "lineage_root_run_id"
                                        )
                                        if source_continuation
                                        else None
                                    ),
                                    "continuation_generation": (
                                        source_continuation.get(
                                            "generation"
                                        )
                                        if source_continuation
                                        else None
                                    ),
                                },
                            }
                        )
                    except DuplicateScanRunIdError:
                        pass
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": (
                            "Scan continuation token could not be claimed"
                        ),
                        "run_id": scan_run_id,
                    },
                ) from exc

        started_at = datetime.now(timezone.utc)
        request_started = time.perf_counter()
        terminal_outcome = "failed"
        failure_stage = "universe_load"
        market_data = None
        members = []
        tradable_members = []
        placeholder_members = []
        symbols: list[str] = []
        scale_gate: dict[str, Any] = {}
        provider_observability: dict[str, Any] = {}
        created_continuation_token: str | None = None
        created_continuation_expires_at: str | None = None
        continuation_limit_reason: str | None = None
        continuation_committed = False
        lineage_root_run_id = (
            str(
                source_continuation.get("lineage_root_run_id")
                or source_continuation.get("parent_run_id")
                or scan_run_id
            )
            if source_continuation
            else scan_run_id
        )
        continuation_generation = (
            int(source_continuation.get("generation") or 1)
            if source_continuation
            else 0
        )

        scan_deadline_at = (
            started_at
            + timedelta(seconds=request.scan_time_budget_seconds)
        )
        scan_execution_guard.annotate(
            scan_run_id,
            limit=request.limit,
            full_universe=request.full_universe,
            batch_size=request.batch_size,
            period=request.period,
            interval=request.interval,
            scan_time_budget_seconds=request.scan_time_budget_seconds,
            batch_time_budget_seconds=request.batch_time_budget_seconds,
            deadline_at=scan_deadline_at.isoformat(),
            deadline_monotonic=(
                request_started + request.scan_time_budget_seconds
            ),
            continuation=bool(continuation_token),
            parent_run_id=(
                source_continuation.get("parent_run_id")
                if source_continuation
                else None
            ),
            lineage_root_run_id=lineage_root_run_id,
            continuation_generation=continuation_generation,
        )

        def audit_payload(
            *,
            outcome: str,
            http_status: int,
            failure_message: str | None = None,
        ) -> dict[str, Any]:
            finished_at = datetime.now(timezone.utc)
            requested_default = (
                len(symbols)
                if symbols
                else 500
                if request.full_universe
                else request.limit
            )
            return {
                "run_id": scan_run_id,
                "scan_type": "nifty500",
                "outcome": outcome,
                "http_status": http_status,
                "failure_stage": (
                    failure_stage
                    if outcome != "completed"
                    else None
                ),
                "failure_message": failure_message,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "duration_sec": float(
                    scale_gate.get(
                        "duration_sec",
                        time.perf_counter() - request_started,
                    )
                ),
                "requested_symbols": int(
                    scale_gate.get(
                        "requested_symbols",
                        requested_default,
                    )
                ),
                "completed_symbols": int(
                    scale_gate.get("completed_symbols", 0)
                ),
                "error_symbols": int(
                    scale_gate.get("error_symbols", 0)
                ),
                "missing_symbols": int(
                    scale_gate.get("missing_symbols", 0)
                ),
                "enrichment_failures": int(
                    scale_gate.get("enrichment_failures", 0)
                ),
                "execution_errors": int(
                    scale_gate.get("execution_errors", 0)
                ),
                "full_universe": bool(
                    scale_gate.get(
                        "full_universe",
                        request.full_universe,
                    )
                ),
                "source_security_count": (
                    scale_gate.get("source_security_count")
                    if scale_gate
                    else len(members) or None
                ),
                "tradable_security_count": (
                    scale_gate.get("tradable_security_count")
                    if scale_gate
                    else len(tradable_members) or None
                ),
                "provider_counts": dict(
                    provider_observability.get(
                        "provider_counts",
                        {},
                    )
                ),
                "fallback_count": int(
                    provider_observability.get(
                        "fallback_count",
                        0,
                    )
                    or 0
                ),
                "nse_resolution_count": int(
                    provider_observability.get(
                        "nse_resolution_count",
                        0,
                    )
                    or 0
                ),
                "error_details": (
                    dict(scale_gate.get("error_details") or {})
                    if scale_gate
                    else (
                        {"fatal": failure_message}
                        if failure_message
                        else {}
                    )
                ),
                "metadata": {
                    "period": request.period,
                    "interval": request.interval,
                    "batch_size": request.batch_size,
                    "batch_pause_seconds": (
                        request.batch_pause_seconds
                    ),
                    "scan_time_budget_seconds": (
                        request.scan_time_budget_seconds
                    ),
                    "batch_time_budget_seconds": (
                        request.batch_time_budget_seconds
                    ),
                    "time_budget_exhausted": bool(
                        scale_gate.get(
                            "time_budget_exhausted",
                            False,
                        )
                    ),
                    "time_budget_stop_reason": (
                        scale_gate.get(
                            "time_budget_stop_reason"
                        )
                    ),
                    "time_budget_stop_batch": (
                        scale_gate.get(
                            "time_budget_stop_batch"
                        )
                    ),
                    "processed_symbols": int(
                        scale_gate.get(
                            "processed_symbols",
                            0,
                        )
                        or 0
                    ),
                    "deferred_symbol_count": int(
                        scale_gate.get(
                            "deferred_symbol_count",
                            0,
                        )
                        or 0
                    ),
                    "deferred_symbols": list(
                        scale_gate.get(
                            "deferred_symbols",
                            [],
                        )
                        or []
                    ),
                    "is_continuation": bool(
                        continuation_token
                    ),
                    "parent_run_id": (
                        source_continuation.get(
                            "parent_run_id"
                        )
                        if source_continuation
                        else None
                    ),
                    "lineage_root_run_id": lineage_root_run_id,
                    "continuation_generation": (
                        continuation_generation
                    ),
                    "next_continuation_available": bool(
                        created_continuation_token
                    ),
                    "next_continuation_expires_at": (
                        created_continuation_expires_at
                    ),
                    "continuation_limit_reason": (
                        continuation_limit_reason
                    ),
                    "max_continuation_generation": (
                        continuation_service.max_generation
                        if continuation_service is not None
                        and hasattr(
                            continuation_service,
                            "max_generation",
                        )
                        else None
                    ),
                    "progress_semantics_version": (
                        scale_gate.get(
                            "progress_semantics_version"
                        )
                    ),
                    "accounted_pct": scale_gate.get(
                        "accounted_pct"
                    ),
                    "processed_pct": scale_gate.get(
                        "processed_pct"
                    ),
                    "successful_pct": scale_gate.get(
                        "successful_pct"
                    ),
                    "error_pct": scale_gate.get("error_pct"),
                    "deferred_pct": scale_gate.get(
                        "deferred_pct"
                    ),
                    "missing_pct": scale_gate.get(
                        "missing_pct"
                    ),
                    "completion_pct_semantics": (
                        scale_gate.get(
                            "completion_pct_semantics"
                        )
                    ),
                    "scan_budget_headroom_sec": (
                        scale_gate.get(
                            "scan_budget_headroom_sec"
                        )
                    ),
                    "scan_budget_utilization_pct": (
                        scale_gate.get(
                            "scan_budget_utilization_pct"
                        )
                    ),
                    "scan_sla_met": scale_gate.get(
                        "scan_sla_met"
                    ),
                    "batch_sla_met": scale_gate.get(
                        "batch_sla_met"
                    ),
                    "sla_met": scale_gate.get("sla_met"),
                    "sla_status": scale_gate.get(
                        "sla_status"
                    ),
                    "max_batch_duration_sec": (
                        scale_gate.get(
                            "max_batch_duration_sec"
                        )
                    ),
                    "avg_batch_duration_sec": (
                        scale_gate.get(
                            "avg_batch_duration_sec"
                        )
                    ),
                    "batch_budget_breach_count": int(
                        scale_gate.get(
                            "batch_budget_breach_count",
                            0,
                        )
                        or 0
                    ),
                    "peak_batch_budget_utilization_pct": (
                        scale_gate.get(
                            "peak_batch_budget_utilization_pct"
                        )
                    ),
                    "excluded_index_placeholders": [
                        getattr(member, "symbol", None)
                        for member in placeholder_members
                        if getattr(member, "symbol", None)
                    ],
                    "circuit_skip_count": int(
                        provider_observability.get(
                            "circuit_skip_count",
                            0,
                        )
                        or 0
                    ),
                    "nse_resolver_attempts": int(
                        provider_observability.get(
                            "nse_resolver_attempts",
                            0,
                        )
                        or 0
                    ),
                    "nse_resolver_skips": int(
                        provider_observability.get(
                            "nse_resolver_skips",
                            0,
                        )
                        or 0
                    ),
                    "circuit_breakers": dict(
                        provider_observability.get(
                            "circuit_breakers",
                            {},
                        )
                    ),
                    "circuit_events": list(
                        provider_observability.get(
                            "circuit_events",
                            [],
                        )
                    ),
                },
            }

        try:
            universe = current_nifty500_universe()
            members = universe.ensure_loaded(
                refresh=request.refresh_universe
            )
            failure_stage = "universe_validation"
            report = universe.report(include_members=False)
            if str(report.get("status", "")).lower() != "healthy":
                raise RuntimeError(
                    "NIFTY 500 universe is not healthy: "
                    f"{report}"
                )
            if report.get("source") != "NSE_NIFTY500_CSV":
                raise RuntimeError(
                    "NIFTY 500 production scan requires canonical "
                    "NSE_NIFTY500_CSV source"
                )

            def is_index_placeholder(member) -> bool:
                symbol = str(
                    getattr(member, "symbol", "") or ""
                ).strip().upper()
                name = str(
                    getattr(member, "name", "") or ""
                ).strip().upper()
                return (
                    symbol.startswith("DUMMY")
                    or name.startswith("DUMMY ")
                )

            placeholder_members = [
                member for member in members
                if is_index_placeholder(member)
            ]
            tradable_members = [
                member for member in members
                if not is_index_placeholder(member)
            ]

            member_by_symbol = {
                str(member.symbol).strip().upper(): member
                for member in tradable_members
            }

            if continuation_token is not None:
                unavailable_symbols = [
                    symbol
                    for symbol in resume_symbols
                    if symbol not in member_by_symbol
                ]
                if unavailable_symbols:
                    raise ValueError(
                        "Continuation contains symbols no longer present "
                        "in the current tradable NIFTY 500 universe: "
                        + ", ".join(unavailable_symbols)
                    )
                selected_members = [
                    member_by_symbol[symbol]
                    for symbol in resume_symbols
                ]
            elif request.full_universe:
                selected_members = list(tradable_members)
            else:
                if request.limit > len(tradable_members):
                    raise ValueError(
                        "Requested NIFTY 500 scan limit exceeds "
                        "tradable constituent security count "
                        f"{len(tradable_members)}"
                    )
                selected_members = list(
                    tradable_members[: request.limit]
                )

            symbols = [member.symbol for member in selected_members]
            failure_stage = "market_data_setup"

            market_aliases = {
                member.symbol: (
                    f"{member.symbol}"
                    f"{str(getattr(member, 'series', '') or '').strip().upper()}"
                )
                for member in selected_members
                if str(
                    getattr(member, "series", "") or ""
                ).strip().upper() == "RR"
            }
            application = current_application()
            market_data_factory = getattr(application, "market_data", None)
            if callable(market_data_factory):
                market_data = market_data_factory()
                alias_setter = getattr(
                    market_data,
                    "set_symbol_aliases",
                    None,
                )
                if callable(alias_setter):
                    alias_setter(market_aliases)
                begin_observation = getattr(
                    market_data,
                    "begin_observation",
                    None,
                )
                if callable(begin_observation):
                    begin_observation()

            failure_stage = "scan_execution"
            result = current_scanner_service().scan_universe(
                symbols,
                period=request.period,
                interval=request.interval,
                capital=request.capital,
                top_n=request.top_n,
                batch_size=request.batch_size,
                batch_pause_seconds=request.batch_pause_seconds,
                scan_time_budget_seconds=(
                    request.scan_time_budget_seconds
                ),
                batch_time_budget_seconds=(
                    request.batch_time_budget_seconds
                ),
            )
            if not isinstance(result, dict):
                raise ValueError(
                    "Scanner returned an invalid universe result contract"
                )

            result["universe"] = report
            raw_scale_gate = result.get("scale_gate")
            if isinstance(raw_scale_gate, dict):
                scale_gate = raw_scale_gate
                scale_gate["stage_limit"] = len(symbols)
                scale_gate["full_universe"] = (
                    False
                    if continuation_token is not None
                    else len(symbols) == len(tradable_members)
                )
                scale_gate["continuation"] = bool(
                    continuation_token
                )
                scale_gate["parent_run_id"] = (
                    source_continuation.get("parent_run_id")
                    if source_continuation
                    else None
                )
                scale_gate["lineage_root_run_id"] = (
                    lineage_root_run_id
                )
                scale_gate["continuation_generation"] = (
                    continuation_generation
                )
                scale_gate["source_security_count"] = len(members)
                scale_gate["tradable_security_count"] = len(
                    tradable_members
                )
                scale_gate["excluded_index_placeholders"] = [
                    member.symbol
                    for member in placeholder_members
                ]
                scale_gate["excluded_index_placeholder_count"] = len(
                    placeholder_members
                )
                scale_gate["nominal_company_count"] = int(
                    report.get("nominal_company_count", 500)
                )

            if market_data is not None:
                snapshot = getattr(
                    market_data,
                    "observability_snapshot",
                    None,
                )
                if callable(snapshot):
                    payload = snapshot(symbols)
                    if isinstance(payload, dict):
                        provider_observability = payload

            result["run_id"] = scan_run_id
            result["provider_observability"] = provider_observability
            if scale_gate:
                scale_gate["run_id"] = scan_run_id
                scale_gate["provider_counts"] = dict(
                    provider_observability.get(
                        "provider_counts",
                        {},
                    )
                )
                scale_gate["fallback_count"] = int(
                    provider_observability.get(
                        "fallback_count",
                        0,
                    )
                    or 0
                )
                scale_gate["nse_resolution_count"] = int(
                    provider_observability.get(
                        "nse_resolution_count",
                        0,
                    )
                    or 0
                )
                scale_gate["circuit_skip_count"] = int(
                    provider_observability.get(
                        "circuit_skip_count",
                        0,
                    )
                    or 0
                )
                scale_gate["nse_resolver_attempts"] = int(
                    provider_observability.get(
                        "nse_resolver_attempts",
                        0,
                    )
                    or 0
                )
                scale_gate["nse_resolver_skips"] = int(
                    provider_observability.get(
                        "nse_resolver_skips",
                        0,
                    )
                    or 0
                )
                scale_gate["circuit_breakers"] = dict(
                    provider_observability.get(
                        "circuit_breakers",
                        {},
                    )
                )

            is_partial = bool(
                scale_gate.get("time_budget_exhausted", False)
            )
            response_outcome = (
                "partial"
                if is_partial
                else "completed"
            )
            result["outcome"] = response_outcome
            if scale_gate:
                scale_gate["outcome"] = response_outcome

            if continuation_token is not None:
                result["resumed_from"] = {
                    "parent_run_id": source_continuation.get(
                        "parent_run_id"
                    ),
                    "lineage_root_run_id": lineage_root_run_id,
                    "generation": continuation_generation,
                    "symbol_count": len(symbols),
                }

            if is_partial:
                failure_stage = "time_budget"
                failure_message = str(
                    scale_gate.get(
                        "time_budget_stop_reason"
                    )
                    or "scan time budget exhausted"
                )

                deferred_for_resume = [
                    str(symbol).strip().upper()
                    for symbol in (
                        scale_gate.get("deferred_symbols") or []
                    )
                    if str(symbol).strip()
                ]
                if (
                    deferred_for_resume
                    and continuation_service is not None
                ):
                    failure_stage = "continuation_create"
                    continuation_request = {
                        "period": request.period,
                        "interval": request.interval,
                        "capital": request.capital,
                        "top_n": request.top_n,
                        "batch_size": request.batch_size,
                        "batch_pause_seconds": (
                            request.batch_pause_seconds
                        ),
                        "scan_time_budget_seconds": (
                            request.scan_time_budget_seconds
                        ),
                        "batch_time_budget_seconds": (
                            request.batch_time_budget_seconds
                        ),
                        "compact": request.compact,
                    }
                    next_generation = (
                        continuation_generation + 1
                        if source_continuation
                        else 1
                    )
                    can_continue = bool(
                        getattr(
                            continuation_service,
                            "can_create_generation",
                            lambda generation: True,
                        )(next_generation)
                    )

                    if can_continue:
                        continuation_record = (
                            continuation_service.create(
                                parent_run_id=scan_run_id,
                                symbols=deferred_for_resume,
                                request=continuation_request,
                                lineage_root_run_id=lineage_root_run_id,
                                generation=next_generation,
                            )
                        )
                        created_continuation_token = str(
                            continuation_record["token"]
                        )
                        created_continuation_expires_at = (
                            continuation_record.get("expires_at")
                        )
                        result["continuation"] = {
                            "token": created_continuation_token,
                            "status": continuation_record["status"],
                            "parent_run_id": scan_run_id,
                            "lineage_root_run_id": lineage_root_run_id,
                            "generation": next_generation,
                            "symbol_count": len(deferred_for_resume),
                            "expires_at": (
                                created_continuation_expires_at
                            ),
                            "claim_attempts": int(
                                continuation_record.get(
                                    "claim_attempts",
                                    0,
                                )
                                or 0
                            ),
                            "max_claim_attempts": int(
                                continuation_record.get(
                                    "max_claim_attempts",
                                    0,
                                )
                                or 0
                            ),
                        }
                        scale_gate["continuation_token"] = (
                            created_continuation_token
                        )
                        scale_gate[
                            "next_continuation_generation"
                        ] = next_generation
                        scale_gate[
                            "continuation_symbol_count"
                        ] = len(deferred_for_resume)
                        scale_gate[
                            "next_continuation_expires_at"
                        ] = created_continuation_expires_at
                    else:
                        continuation_limit_reason = (
                            "maximum_generation_reached"
                        )
                        result["continuation_limit"] = {
                            "reason": continuation_limit_reason,
                            "max_generation": getattr(
                                continuation_service,
                                "max_generation",
                                None,
                            ),
                            "attempted_generation": next_generation,
                            "deferred_symbol_count": len(
                                deferred_for_resume
                            ),
                        }
                        scale_gate[
                            "continuation_limit_reason"
                        ] = continuation_limit_reason
                        scale_gate[
                            "max_continuation_generation"
                        ] = getattr(
                            continuation_service,
                            "max_generation",
                            None,
                        )
                        scale_gate[
                            "continuation_symbol_count"
                        ] = len(deferred_for_resume)
                    failure_stage = "time_budget"
            else:
                failure_stage = "audit_write"
                failure_message = None

            if (
                continuation_token is not None
                and continuation_service is not None
            ):
                failure_stage = "continuation_consume"
                continuation_service.consume(
                    continuation_token,
                    scan_run_id,
                )
                failure_stage = (
                    "time_budget"
                    if is_partial
                    else "audit_write"
                )

            if audit_service is not None:
                audit_service.record(
                    audit_payload(
                        outcome=response_outcome,
                        http_status=200,
                        failure_message=failure_message,
                    )
                )

            continuation_committed = True

            if request.paper_auto_entry:
                auto_entry = current_paper_auto_entry_service()
                if auto_entry is None:
                    result["paper_auto_entry"] = {
                        "status": "not_supported",
                        "run_id": scan_run_id,
                        "broker_orders_allowed": False,
                        "opened": [],
                    }
                else:
                    try:
                        result["paper_auto_entry"] = (
                            auto_entry.process_scan(
                                result,
                                run_id=scan_run_id,
                                execute_requested=True,
                                continuation=(
                                    continuation_token is not None
                                ),
                            )
                        )
                    except Exception as exc:
                        result["paper_auto_entry"] = {
                            "status": "failed_closed",
                            "run_id": scan_run_id,
                            "error": (
                                f"{type(exc).__name__}: {exc}"
                            ),
                            "broker_orders_allowed": False,
                            "opened": [],
                        }
                        producer = best_effort_notification_producer()
                        if producer is not None:
                            producer.auto_entry_result(
                                result["paper_auto_entry"]
                            )

            producer = best_effort_notification_producer()
            if producer is not None:
                result["notification_dispatch"] = (
                    producer.scan_completed(
                        result,
                        run_id=scan_run_id,
                        continuation=(
                            continuation_token is not None
                        ),
                    )
                )
            else:
                result["notification_dispatch"] = {
                    "status": "not_supported",
                }

            if request.compact:
                items = list(result.get("results") or [])
                items.extend(list(result.get("rejected") or []))

                summaries = []
                for item in items:
                    signal = item.get("signal")
                    if isinstance(signal, dict):
                        signal = signal.get(
                            "signal",
                            signal.get("name", "HOLD"),
                        )
                    else:
                        signal = getattr(
                            signal,
                            "signal",
                            signal,
                        )
                    summaries.append(
                        {
                            "symbol": item.get("symbol"),
                            "signal": str(signal or "HOLD").upper(),
                            "eligible": bool(
                                item.get("eligible", False)
                            ),
                            "analysis_eligible": bool(
                                item.get(
                                    "analysis_eligible",
                                    item.get("eligible", False),
                                )
                            ),
                            "execution_eligible": bool(
                                item.get(
                                    "execution_eligible",
                                    item.get("eligible", False),
                                )
                            ),
                            "ranking_score": item.get(
                                "ranking_score",
                                0.0,
                            ),
                            "analysis_rejection_reason": item.get(
                                "analysis_rejection_reason"
                            ),
                            "execution_rejection_reason": item.get(
                                "execution_rejection_reason",
                                item.get("rejection_reason"),
                            ),
                            "primary_execution_block": item.get(
                                "primary_execution_block"
                            ),
                            "execution_block_reasons": list(
                                item.get("execution_block_reasons") or []
                            ),
                            "fundamental_readiness": (
                                item.get("fundamental_readiness")
                            ),
                            "market_regime_context": (
                                item.get("market_regime_context")
                            ),
                            "risk_context": item.get("risk_context"),
                            "rejection_reason": item.get(
                                "rejection_reason"
                            ),
                            "error": item.get("error"),
                            "enrichment_failures": len(
                                item.get("enrichment_failures") or []
                            ),
                            "execution_errors": len(
                                item.get("execution_errors") or []
                            ),
                        }
                    )

                result["symbol_results"] = sorted(
                    summaries,
                    key=lambda row: str(row.get("symbol") or ""),
                )
                result.pop("results", None)
                result.pop("eligible", None)
                result.pop("rejected", None)
                # R67.3 keeps ranked top-N views but removes duplicate full
                # per-symbol partitions so compact mode remains compact.
                result.pop("analysis_ranked", None)
                result.pop("analysis_eligible", None)
                result.pop("analysis_rejected", None)
                result.pop("execution_eligible", None)
                result.pop("execution_rejected", None)

            terminal_outcome = response_outcome
            return result

        except DuplicateScanRunIdError as exc:
            if (
                continuation_service is not None
                and not continuation_committed
            ):
                if created_continuation_token:
                    continuation_service.delete_pending(
                        created_continuation_token,
                        scan_run_id,
                    )
                    created_continuation_token = None
                if continuation_token is not None:
                    continuation_service.restore_pending(
                        continuation_token,
                        scan_run_id,
                    )
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "scan run_id already exists",
                    "run_id": scan_run_id,
                },
            ) from exc
        except ValueError as exc:
            if (
                continuation_service is not None
                and not continuation_committed
            ):
                if created_continuation_token:
                    continuation_service.delete_pending(
                        created_continuation_token,
                        scan_run_id,
                    )
                    created_continuation_token = None
                if continuation_token is not None:
                    continuation_service.restore_pending(
                        continuation_token,
                        scan_run_id,
                    )
            if audit_service is not None:
                try:
                    audit_service.record(
                        audit_payload(
                            outcome="failed",
                            http_status=422,
                            failure_message=str(exc),
                        )
                    )
                except DuplicateScanRunIdError:
                    pass
            producer = best_effort_notification_producer()
            if producer is not None:
                producer.scan_failed(
                    run_id=scan_run_id,
                    failure_stage=failure_stage,
                    message=str(exc),
                    http_status=422,
                )
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            if (
                continuation_service is not None
                and not continuation_committed
            ):
                if created_continuation_token:
                    continuation_service.delete_pending(
                        created_continuation_token,
                        scan_run_id,
                    )
                    created_continuation_token = None
                if continuation_token is not None:
                    continuation_service.restore_pending(
                        continuation_token,
                        scan_run_id,
                    )
            failure_reference = uuid4().hex[:12]
            safe_failure = f"Scan temporarily unavailable; reference {failure_reference}"
            _AUDIT_LOG.error(
                "scan_run_failed run_id=%s reference=%s error_type=%s",
                scan_run_id, failure_reference, type(exc).__name__,
            )
            if audit_service is not None:
                try:
                    audit_service.record(
                        audit_payload(
                            outcome="failed",
                            http_status=503,
                            failure_message=safe_failure,
                        )
                    )
                except DuplicateScanRunIdError:
                    pass
            producer = best_effort_notification_producer()
            if producer is not None:
                producer.scan_failed(
                    run_id=scan_run_id,
                    failure_stage=failure_stage,
                    message=safe_failure,
                    http_status=503,
                )
            raise HTTPException(
                status_code=503,
                detail="Scan temporarily unavailable",
                headers={"X-Error-Reference": failure_reference},
            ) from exc
        finally:
            if (
                continuation_service is not None
                and not continuation_committed
                and continuation_token is not None
            ):
                try:
                    continuation_service.restore_pending(
                        continuation_token,
                        scan_run_id,
                    )
                except Exception:
                    _AUDIT_LOG.error(
                        "scan_continuation_restore_failed run_id=%s",
                        scan_run_id,
                    )
            scan_execution_guard.finish(
                scan_run_id,
                terminal_outcome,
            )

    @app.get("/observability/scan-lineages/{run_id}")
    def scan_lineage_rollup(run_id: str) -> dict[str, Any]:
        audit = current_scan_run_audit_service()
        continuations = current_scan_continuation_service()
        if audit is None or continuations is None:
            raise HTTPException(
                status_code=503,
                detail="Scan lineage services are unavailable",
            )

        from services.scan_lineage_service import (
            ScanLineageNotFoundError,
            ScanLineageService,
        )

        try:
            return ScanLineageService(
                audit,
                continuations,
            ).rollup(run_id)
        except ScanLineageNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

    @app.get(
        "/observability/scan-lineages/{run_id}/integrity"
    )
    def scan_lineage_integrity(run_id: str) -> dict[str, Any]:
        audit = current_scan_run_audit_service()
        continuations = current_scan_continuation_service()
        if audit is None or continuations is None:
            raise HTTPException(
                status_code=503,
                detail="Scan lineage services are unavailable",
            )

        from services.scan_lineage_service import (
            ScanLineageNotFoundError,
            ScanLineageService,
        )

        try:
            rollup = ScanLineageService(
                audit,
                continuations,
            ).rollup(run_id)
        except ScanLineageNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

        return {
            "requested_run_id": rollup["requested_run_id"],
            "lineage_root_run_id": rollup[
                "lineage_root_run_id"
            ],
            "lineage_status": rollup["status"],
            "integrity": rollup["integrity"],
        }

    @app.get("/observability/scan-continuations/{token}")
    def scan_continuation(token: str) -> dict[str, Any]:
        service = current_scan_continuation_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Scan continuation service is unavailable",
            )
        try:
            inspect_any = getattr(service, "inspect_any", None)
            record = (
                inspect_any(token)
                if callable(inspect_any)
                else service.inspect(token)
            )
        except ContinuationNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Scan continuation token not found",
            ) from exc

        payload = {
            key: value
            for key, value in record.items()
            if key != "token"
        }
        audit = current_scan_run_audit_service()
        if audit is not None:
            payload["parent_audit"] = audit.get(
                record.get("parent_run_id")
            )
            child_run_id = record.get("child_run_id")
            payload["child_audit"] = (
                audit.get(child_run_id)
                if child_run_id
                else None
            )
        return payload

    @app.get("/observability/scan-runs")
    def scan_run_audits(
        limit: int = Query(default=20, ge=1, le=500),
    ) -> dict[str, Any]:
        service = current_scan_run_audit_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Scan-run audit service is unavailable",
            )
        return {
            "runs": service.latest(limit),
            "limit": limit,
        }

    @app.get("/observability/scan-runs/{run_id}")
    def scan_run_audit(run_id: str) -> dict[str, Any]:
        service = current_scan_run_audit_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Scan-run audit service is unavailable",
            )
        record = service.get(run_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail="Scan run not found",
            )
        return record

    @app.get("/scan/{symbol}")
    def scan_symbol(symbol: str, period: str = "6mo", interval: str = "1d",
                    capital: float = Query(default=0.0, ge=0, allow_inf_nan=False)) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=422, detail="Symbol is required")
        try:
            result = current_scanner_service().scan(
                symbol, period=period, interval=interval, capital=capital
            )
            if not isinstance(result, dict):
                raise ValueError("Scanner returned an invalid result contract")
            return result
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Scanner service temporarily unavailable") from exc

    @app.post("/scan")
    def scan(request: ScanRequest) -> dict[str, Any]:
        try:
            result = current_scanner_service().scan_many(
                request.symbols, period=request.period, interval=request.interval,
                capital=request.capital, top_n=request.top_n
            )
            if not isinstance(result, dict):
                raise ValueError("Scanner returned an invalid batch result contract")
            return result
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Scanner service temporarily unavailable") from exc

    # R70.3: endpoint exists but refuses requests until durable cloud storage is verified.
    from api.hybrid_sync_router import receive_event, sync_readiness
    app.add_api_route("/sync/readiness", sync_readiness, methods=["GET"], tags=["PC Hybrid Sync"])
    app.add_api_route("/sync/events", receive_event, methods=["POST"], tags=["PC Hybrid Sync"])

    from api.trading_workspace_router import attach_trading_workspace_routes
    attach_trading_workspace_routes(
        app,
        intelligence_getter=current_intelligence_dashboard_service,
        paper_getter=current_paper_trading_service,
        provider_factory_getter=lambda: getattr(
            current_application(),
            "providers",
            None,
        ),
    )

    if production_runtime_enabled():
        secure_application(app)
    install_api_error_boundary(app)
    return app


app = create_app()
if production_runtime_enabled():
    secure_application(app)

if str(os.getenv("TRENDFORGE_UNIFIED_UI_ENABLED") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}:
    from core.unified_render import build_unified_app
    app = build_unified_app(app)

__all__ = [
    "app",
    "create_app",
    "get_application",
    "get_scanner_service",
    "FundamentalUpdateRequest",
    "WatchlistEntryRequest",
    "WatchlistUpdateRequest",
    "MarketContextRefreshRequest",
    "BacktestRunRequest",
    "IntelligenceRefreshRequest",
    "InstitutionalRefreshRequest",
    "SectorStrengthRefreshRequest",
    "NotificationEventRequest",
    "NotificationPolicyRequest",
    "NotificationDailySummarySendRequest",
    "MarketDayOperationsPolicyRequest",
    "MarketDayOperationRunRequest",
    "ExternalOperationsTickRequest",
    "OperationsAuditRunRequest",
    "Nifty500ScanRequest",
    "PaperOrderRequest",
    "PaperMonitorRequest",
    "PaperKillSwitchRequest",
]
