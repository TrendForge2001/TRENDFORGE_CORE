"""R72.5.1 canonical technical-strategy registry.

The registry is intentionally declarative.  It records the notebook-derived
TrendForge strategies and clearly labelled template-style strategies without
changing the execution engine yet.  R72.5.2+ consume these definitions for
scanner/backtest/paper execution.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

REGISTRY_VERSION = "source-six-with-five-intraday-shorts-v3"


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    strategy_id: str
    name: str
    source: str
    family: str
    description: str
    modes: tuple[str, ...]
    intervals: tuple[str, ...]
    default_interval: str
    universes: tuple[str, ...]
    indicators: tuple[str, ...]
    entry_rules: tuple[str, ...]
    exit_rules: tuple[str, ...]
    target_rules: tuple[str, ...]
    stoploss_rules: tuple[str, ...]
    risk_rules: tuple[str, ...]
    paper_eligible: bool = True
    implementation_status: str = "registered"
    notes: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    direction: str = "LONG"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in payload.items()
        }


U = ("NIFTY 100", "NIFTY 200", "NIFTY 500")


def _s(
    strategy_id: str,
    name: str,
    source: str,
    family: str,
    description: str,
    *,
    modes: tuple[str, ...],
    intervals: tuple[str, ...],
    default_interval: str,
    indicators: tuple[str, ...],
    entry: tuple[str, ...],
    exit: tuple[str, ...],
    targets: tuple[str, ...] = (),
    stops: tuple[str, ...] = (),
    risk: tuple[str, ...] = (),
    paper_eligible: bool = True,
    status: str = "registered",
    notes: tuple[str, ...] = (),
    ambiguities: tuple[str, ...] = (),
    direction: str = "LONG",
) -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id=strategy_id,
        name=name,
        source=source,
        family=family,
        description=description,
        modes=modes,
        intervals=intervals,
        default_interval=default_interval,
        universes=U,
        indicators=indicators,
        entry_rules=entry,
        exit_rules=exit,
        target_rules=targets,
        stoploss_rules=stops,
        risk_rules=risk,
        paper_eligible=paper_eligible,
        implementation_status=status,
        notes=notes,
        ambiguities=ambiguities,
        direction=direction,
    )


STRATEGIES: tuple[StrategyDefinition, ...] = (
    _s(
        "tf_intraday_ema9_20_momentum",
        "Intraday EMA 9/20 Momentum",
        "user_notebook",
        "intraday_trend",
        "15-minute momentum crossover with RSI and volume confirmation.",
        modes=("intraday",),
        intervals=("15m",),
        default_interval="15m",
        indicators=("EMA_9", "EMA_20", "RSI_14", "VOL_SMA_20", "ATR"),
        entry=(
            "EMA_9 crosses above EMA_20 after candle close.",
            "RSI_14 >= 60.",
            "Volume > VOL_SMA_20.",
            "Entry only after 09:45 IST.",
        ),
        exit=(
            "EMA_9 crosses below EMA_20.",
            "RSI_14 <= 40 indicates bearish momentum loss.",
            "Normal intraday square-off at 15:00 IST; hard safety cutoff 15:10 IST.",
        ),
        targets=("Minimum reward:risk 1.5:1.",),
        stops=("ATR/pivot support stop; never widen after entry.",),
        risk=(
            "Maximum 25% of paper capital per trade.",
            "Maximum 3 intraday trades.",
        ),
    ),
    _s(
        "tf_intraday_ema20_50_rsi_volume",
        "Intraday EMA 20/50 + RSI + Volume",
        "user_notebook",
        "intraday_trend",
        "Notebook EMA20/50 entry setup with proximity, RSI and volume confirmation.",
        modes=("intraday",),
        intervals=("15m",),
        default_interval="15m",
        indicators=("EMA_20", "EMA_50", "RSI_14", "VOL_SMA_20", "ATR"),
        entry=(
            "EMA_20 bullish crossover above EMA_50.",
            "Price must be within 1% of the crossover/reference EMA area.",
            "RSI_14 > 60.",
            "Volume > VOL_SMA_20.",
            "Entry only after 09:45 IST.",
        ),
        exit=(
            "EMA_20 bearish crossover below EMA_50 or confirmed trend reversal.",
            "RSI deterioration confirms exit.",
            "Intraday square-off by 15:00 IST; hard cutoff 15:10 IST.",
        ),
        targets=("Basic intraday reward:risk minimum 1.5:1.",),
        stops=("Use nearest technical support / pivot or ATR protective stop.",),
        risk=("Maximum 25% capital per trade.", "Maximum 3 intraday trades."),
    ),
    _s(
        "tf_intraday_vwma9_26_rsi_volume",
        "Intraday VWMA 9/26 + RSI + Volume",
        "user_notebook",
        "intraday_trend",
        "NIFTY scanner rule using VWMA 9/26 crossover, RSI and Volume MA20.",
        modes=("intraday",),
        intervals=("15m",),
        default_interval="15m",
        indicators=("VWMA_9", "VWMA_26", "RSI_14", "VOL_SMA_20", "ATR"),
        entry=(
            "VWMA_9 crosses above VWMA_26.",
            "Price is within 1% of the VWMA crossover/reference.",
            "RSI_14 > 60.",
            "Volume > VOL_SMA_20.",
        ),
        exit=(
            "VWMA_9 crosses below VWMA_26.",
            "RSI_14 < 40 is bearish confirmation.",
        ),
        targets=("Minimum reward:risk 1.5:1.",),
        stops=("Technical support / ATR stop.",),
        risk=("Paper-only until validated.",),
    ),
    _s(
        "tf_intraday_supertrend_vwap_pivots",
        "Intraday Supertrend + VWAP + Fibonacci Pivots",
        "user_notebook",
        "intraday_trend",
        "15-minute Supertrend/VWAP strategy with RSI, volume and Fibonacci pivots.",
        modes=("intraday",),
        intervals=("15m",),
        default_interval="15m",
        indicators=(
            "SUPERTREND_10_3", "SUPERTREND_DIR", "RSI_14",
            "VOL_SMA_20", "VWAP", "FIB_PIVOT", "FIB_R1", "FIB_S1",
        ),
        entry=(
            "Trade only after candle close.",
            "Supertrend direction and RSI must confirm the trade direction.",
            "Volume > VOL_SMA_20.",
            "VWAP and Fibonacci pivot location act as support/resistance filters.",
        ),
        exit=(
            "Close on Supertrend direction reversal.",
            "RSI < 30 is an emergency weakness condition in the notebook.",
        ),
        targets=("Prefer nearest Fibonacci R1/R2/R3 or minimum 1.5R.",),
        stops=("Prefer nearest Fibonacci S1/support or Supertrend/ATR stop.",),
        risk=("Maximum 25% capital per trade.",),
        ambiguities=(
            "Notebook VWAP wording says buy below 1% / sell above 1%; exact distance semantics remain for R72.5.2 execution review.",
            "Notebook pivot '50% between levels' gate is preserved as a future scanner filter, not silently reinterpreted here.",
        ),
    ),
    _s(
        "tf_swing_ema20_50_rsi_volume",
        "Swing EMA 20/50 + RSI + Volume",
        "user_notebook",
        "swing_trend",
        "Daily EMA20/50 crossover strategy with RSI and Volume MA20 confirmation.",
        modes=("swing",),
        intervals=("1d",),
        default_interval="1d",
        indicators=("EMA_20", "EMA_50", "RSI_14", "VOL_SMA_20", "ATR"),
        entry=(
            "EMA_20 crosses above EMA_50.",
            "Price is within 1% of the crossover/reference EMA.",
            "RSI_14 > 60.",
            "Volume > VOL_SMA_20.",
        ),
        exit=(
            "EMA_20 crosses below EMA_50 or bearish candle reversal is confirmed.",
            "Exit when volume remains below VOL_SMA_20 for the notebook-defined persistence window.",
        ),
        targets=(
            "Scale out 50% at Target 1.",
            "Scale out 25% at Target 2.",
            "Scale out final 25% at Target 3.",
        ),
        stops=("ATR/pivot support stop.",),
        risk=("Maximum 50% cash allocation per swing trade.", "Maximum 2 concurrent swing setups."),
    ),
    _s(
        "tf_swing_vwma9_26_rsi_volume",
        "Swing VWMA 9/26 + RSI + Volume",
        "user_notebook",
        "swing_trend",
        "Daily VWMA 9/26 crossover with RSI and Volume MA20.",
        modes=("swing",),
        intervals=("1d",),
        default_interval="1d",
        indicators=("VWMA_9", "VWMA_26", "RSI_14", "VOL_SMA_20", "ATR"),
        entry=(
            "VWMA_9 crosses above VWMA_26.",
            "RSI_14 > 60.",
            "Volume > VOL_SMA_20.",
        ),
        exit=("VWMA_9 crosses below VWMA_26 or momentum/volume confirmation is lost.",),
        targets=("Use staged swing targets after risk calibration.",),
        stops=("ATR or nearest support stop.",),
        risk=("Paper-only until multi-strategy validation is complete.",),
    ),
    _s(
        "tf_swing_macd_trend",
        "Swing / Positional MACD Trend",
        "user_notebook",
        "swing_momentum",
        "Daily/weekly directional trend strategy using MACD with higher-period EMA context.",
        modes=("swing", "positional"),
        intervals=("1d", "1wk"),
        default_interval="1d",
        indicators=("EMA_50", "EMA_100", "EMA_200", "RSI_20", "MACD", "MACD_SIGNAL"),
        entry=("MACD bullish crossover with higher-timeframe EMA trend confirmation.",),
        exit=("Exit on MACD bearish crossover.",),
        targets=("Trend-following target; allow staged profit booking.",),
        stops=("ATR / structural support stop.",),
        risk=("Maximum 50% cash allocation per swing/positional trade.",),
    ),
    _s(
        "tf_medium_ema50_100",
        "Medium-Term EMA 50/100",
        "user_notebook",
        "positional_trend",
        "Medium-term EMA 50/100 crossover regime.",
        status="review_required",
        paper_eligible=False,
        notes=("Source momentum confirmation, staged targets and stop rules require explicit review before simulation or execution.",),
        modes=("positional",),
        intervals=("1d", "1wk"),
        default_interval="1d",
        indicators=("EMA_50", "EMA_100", "RSI_20", "MACD"),
        entry=("EMA_50 crosses above EMA_100 with momentum confirmation.",),
        exit=("EMA_50 crosses below EMA_100 or MACD bearish crossover.",),
        targets=("Trend-following staged targets.",),
        stops=("Structural/ATR stop.",),
    ),
    _s(
        "tf_long_ema100_200",
        "Long-Term EMA 100/200",
        "user_notebook",
        "positional_trend",
        "Long-term EMA 100/200 trend regime.",
        status="review_required",
        paper_eligible=False,
        notes=("Source momentum confirmation, staged targets and stop rules require explicit review before simulation or execution.",),
        modes=("positional",),
        intervals=("1d", "1wk"),
        default_interval="1d",
        indicators=("EMA_100", "EMA_200", "RSI_20", "MACD"),
        entry=("EMA_100 crosses above EMA_200 with trend confirmation.",),
        exit=("EMA_100 crosses below EMA_200 or MACD bearish crossover.",),
        targets=("Long-term trend targets.",),
        stops=("Long-term structural stop.",),
    ),
    _s(
        "tf_golden_cross_50_200",
        "Golden Cross EMA 50/200",
        "user_notebook",
        "positional_trend",
        "Classic EMA50/200 golden-cross trend setup.",
        modes=("positional",),
        intervals=("1d", "1wk"),
        default_interval="1d",
        indicators=("EMA_50", "EMA_200", "RSI_20", "VOL_SMA_50"),
        entry=("EMA_50 crosses above EMA_200.",),
        exit=("EMA_50 crosses below EMA_200 (death cross) or trend invalidation.",),
        targets=("Trend-following targets.",),
        stops=("Structural support stop.",),
    ),
    _s(
        "tf_rsi_momentum_confirmation",
        "RSI Momentum Confirmation",
        "user_notebook",
        "momentum",
        "Momentum regime separated from mean-reversion RSI rules.",
        modes=("intraday", "swing"),
        intervals=("15m", "1d"),
        default_interval="1d",
        indicators=("RSI_14", "EMA_20", "EMA_50", "VOL_SMA_20"),
        entry=(
            "RSI_14 >= 60 is bullish only when EMA and volume conditions confirm.",
            "RSI between 40 and 60 is neutral: no signal.",
        ),
        exit=("RSI_14 <= 40 is bearish when EMA and volume confirm.",),
        targets=("Use parent strategy target rules.",),
        stops=("Use parent strategy stop rules.",),
        paper_eligible=False,
        notes=("Confirmation strategy; designed to be combined with a directional setup.",),
    ),
    _s(
        "tf_rsi_mean_reversion",
        "RSI Mean Reversion",
        "user_notebook",
        "mean_reversion",
        "Oversold/overbought RSI setup kept separate from momentum RSI logic.",
        modes=("intraday", "swing"),
        intervals=("15m", "1d"),
        default_interval="1d",
        indicators=("RSI_14", "EMA_20", "EMA_50", "VOL_SMA_20"),
        entry=("RSI_14 < 30 identifies oversold state; require EMA/volume confirmation before any buy.",),
        exit=("RSI_14 > 70 identifies overbought state; require EMA/volume confirmation before any sell/exit.",),
        targets=("Mean-reversion target toward trend reference.",),
        stops=("Structural/ATR stop.",),
        paper_eligible=False,
    ),
    _s(
        "tpl_supertrend_rsi",
        "Template · Supertrend + RSI",
        "template",
        "trend",
        "Generic trend template using Supertrend direction and RSI confirmation.",
        modes=("intraday", "swing"),
        intervals=("15m", "1d"),
        default_interval="15m",
        indicators=("SUPERTREND_10_3", "SUPERTREND_DIR", "RSI_14", "ATR"),
        entry=("Supertrend bullish and RSI_14 > 55.",),
        exit=("Supertrend bearish or RSI momentum loss.",),
        targets=("2R reference target.",),
        stops=("Supertrend or ATR stop.",),
    ),
    _s(
        "tpl_ema_adx_trend",
        "Template · EMA + ADX Trend",
        "template",
        "trend",
        "Generic EMA trend template confirmed by ADX and directional movement.",
        modes=("intraday", "swing"),
        intervals=("15m", "1d"),
        default_interval="1d",
        indicators=("EMA_20", "EMA_50", "ADX", "+DI", "-DI", "ATR"),
        entry=("EMA_20 > EMA_50, ADX >= 20 and +DI > -DI.",),
        exit=("EMA trend reverses or -DI overtakes +DI.",),
        targets=("2R reference target.",),
        stops=("ATR stop.",),
    ),
    _s(
        "tpl_vwap_volume_breakout",
        "Template · VWAP + Volume Breakout",
        "template",
        "breakout",
        "Generic intraday breakout above VWAP with relative-volume confirmation.",
        modes=("intraday",),
        intervals=("15m",),
        default_interval="15m",
        indicators=("VWAP", "BREAKOUT", "RVOL", "VOL_SMA_20", "ATR"),
        entry=("Close above VWAP on fresh breakout with RVOL > 1.2.",),
        exit=("Close below VWAP or breakout failure.",),
        targets=("2R reference target.",),
        stops=("VWAP/ATR protective stop.",),
    ),
    _s(
        "tpl_macd_trend_confirmation",
        "Template · MACD Trend Confirmation",
        "template",
        "momentum",
        "Generic MACD crossover aligned with EMA trend.",
        modes=("swing", "positional"),
        intervals=("1d",),
        default_interval="1d",
        indicators=("MACD", "MACD_SIGNAL", "MACD_HIST", "EMA_20", "EMA_50"),
        entry=("MACD bullish crossover while EMA_20 > EMA_50.",),
        exit=("MACD bearish crossover.",),
        targets=("Trend-following target.",),
        stops=("ATR/EMA invalidation stop.",),
    ),
    _s(
        "tpl_bollinger_breakout",
        "Template · Bollinger Breakout",
        "template",
        "breakout",
        "Generic volatility breakout using Bollinger upper band and volume.",
        modes=("intraday", "swing"),
        intervals=("15m", "1d"),
        default_interval="1d",
        indicators=("BB_UPPER", "BB_MID", "BB_LOWER", "RVOL", "ATR"),
        entry=("Close above BB_UPPER with elevated relative volume.",),
        exit=("Close below BB_MID or momentum failure.",),
        targets=("ATR expansion target.",),
        stops=("BB_MID/ATR stop.",),
    ),
    _s(
        "tpl_volume_breakout",
        "Template · Volume Breakout",
        "template",
        "breakout",
        "Generic price breakout confirmed by volume above moving average.",
        modes=("intraday", "swing"),
        intervals=("15m", "1d"),
        default_interval="1d",
        indicators=("BREAKOUT", "VOL_SMA_20", "RVOL", "ATR"),
        entry=("Fresh price breakout with Volume > VOL_SMA_20 and RVOL > 1.2.",),
        exit=("Breakout failure or close below support.",),
        targets=("2R reference target.",),
        stops=("Breakout support/ATR stop.",),
    ),
    _s(
        "tpl_52week_high_momentum",
        "Template · 52-Week High Momentum",
        "template",
        "momentum",
        "Generic daily momentum setup near the rolling 52-week high.",
        modes=("swing", "positional"),
        intervals=("1d",),
        default_interval="1d",
        indicators=("HIGH_252", "DIST_52W_HIGH_PCT", "RSI_14", "VOL_SMA_20"),
        entry=("Close is within 5% of HIGH_252 with RSI_14 >= 60 and Volume > VOL_SMA_20.",),
        exit=("Momentum loss or break below trend support.",),
        targets=("Trend-following target.",),
        stops=("ATR / structural support stop.",),
    ),
)

SHORT_STRATEGIES = tuple(
    _s(
        strategy_id,
        name,
        "user_analysis",
        "intraday_short",
        "Bearish counterpart of the owner's existing crossover setup; unleveraged paper simulation only.",
        modes=("intraday",),
        intervals=("15m",),
        default_interval="15m",
        indicators=(fast, slow, "RSI_14", "VOL_SMA_20", "ATR"),
        entry=(
            f"{fast} crosses below {slow} on a completed 15-minute candle.",
            "RSI_14 <= 40 and volume > VOL_SMA_20.",
            "Entry signal at or after 09:45 IST; fresh same-session quote required.",
            *( (f"Close within 1% of {fast}.",) if fast == "VWMA_9" else () ),
        ),
        exit=(
            f"{fast} crosses above {slow} or RSI_14 >= 60.",
            "Buy to cover at the protective stop/target or 15:00 IST square-off.",
        ),
        targets=("Target = entry minus 2 × initial risk/share (risk:reward 1:2).",),
        stops=("Stop = entry plus 1.5 × ATR; never widen after entry.",),
        risk=("Intraday only; no leverage or overnight short entries.",
              "Same shared paper risk, storage, validation and kill controls as long entries."),
        notes=("New bearish counterpart requested by the owner; not a notebook transcription or a Streak preset.",),
        direction="SHORT",
    )
    for strategy_id, name, fast, slow in (
        ("tf_intraday_ema9_20_short", "Intraday SHORT · EMA 9/20 + RSI + Volume", "EMA_9", "EMA_20"),
        ("tf_intraday_vwma9_26_short", "Intraday SHORT · VWMA 9/26 + RSI + Volume", "VWMA_9", "VWMA_26"),
    )
)
ADDITIONAL_SHORT_STRATEGIES = tuple(
    _s(
        strategy_id, name, "user_analysis", "intraday_short",
        description,
        modes=("intraday",), intervals=("15m",), default_interval="15m",
        indicators=(*indicators, "RSI_14", "VOL_SMA_20", "ATR"),
        entry=(*entry,
               "RSI_14 <= 45 and volume > VOL_SMA_20.",
               "Completed same-session 15-minute candles; signal starts at/after 09:45 and before 14:45 IST."),
        exit=(*exit,
              "Buy to cover at the stop/target or 15:00 IST square-off."),
        targets=("Target = entry minus 2 × initial risk/share (risk:reward 1:2).",),
        stops=("Stop = entry plus 1.5 × ATR; never widen after entry.",),
        risk=("Intraday only; full-notional collateral, no leverage or overnight shorts.",
              "Existing validation, capital reserve, position limits, fresh quotes and kill gates apply."),
        notes=("Owner-requested research rules; not a copied Streak preset. No profitability or market-regime claim.",),
        direction="SHORT",
    )
    for strategy_id, name, description, indicators, entry, exit in (
        (
            "tf_intraday_vwap_breakdown_short",
            "Intraday SHORT · Session VWAP Breakdown",
            "A fresh close below the NSE-session VWAP with bearish EMA context.",
            ("VWAP_SESSION", "EMA_9", "EMA_20"),
            ("Previous close >= previous session VWAP; current close < current session VWAP.",
             "EMA_9 < EMA_20; both candles belong to the same NSE session."),
            ("Close recovers above session VWAP or RSI_14 >= 60.",),
        ),
        (
            "tf_intraday_low20_breakdown_short",
            "Intraday SHORT · 20-Candle Low Breakdown",
            "A fresh close below the prior 20-candle low, excluding the signal candle.",
            ("LOW_20_PREV", "EMA_20"),
            ("Close < LOW_20_PREV and previous close >= previous LOW_20_PREV.",
             "Close < EMA_20; the rolling reference may include earlier sessions."),
            ("Close recovers above EMA_20 or RSI_14 >= 60.",),
        ),
        (
            "tf_intraday_ema_adx_continuation_short",
            "Intraday SHORT · EMA / ADX Bearish Continuation",
            "Continuation in an established bearish EMA/ADX trend, without requiring a new EMA crossover.",
            ("EMA_20", "EMA_50", "ADX", "+DI", "-DI"),
            ("EMA_20 < EMA_50, ADX >= 20 and -DI > +DI.",
             "Current close breaks below the previous completed candle low."),
            ("Close recovers above EMA_20, +DI > -DI, or RSI_14 >= 60.",),
        ),
    )
)
STRATEGIES = (*STRATEGIES, *SHORT_STRATEGIES, *ADDITIONAL_SHORT_STRATEGIES)

# Definitions for retired rules remain private for exit-only handling of existing
# positions. They are never returned by the active catalog or admitted for entry.
_HISTORICAL_BY_ID = {item.strategy_id: item for item in STRATEGIES}
ACTIVE_STRATEGY_IDS = frozenset({
    "tf_intraday_ema9_20_momentum", "tf_intraday_vwma9_26_rsi_volume",
    "tf_swing_ema20_50_rsi_volume", "tf_swing_vwma9_26_rsi_volume",
    "tf_medium_ema50_100", "tf_long_ema100_200",
    "tf_intraday_ema9_20_short", "tf_intraday_vwma9_26_short",
    "tf_intraday_vwap_breakdown_short", "tf_intraday_low20_breakdown_short",
    "tf_intraday_ema_adx_continuation_short",
})
STRATEGIES = tuple(item for item in STRATEGIES if item.strategy_id in ACTIVE_STRATEGY_IDS)
_BY_ID = {item.strategy_id: item for item in STRATEGIES}


def historical_strategy_for_exit(strategy_id: str) -> dict[str, Any]:
    """Private compatibility metadata, only for monitoring existing positions."""
    item = _HISTORICAL_BY_ID.get(str(strategy_id).strip().lower())
    if item is None:
        raise KeyError("Unknown historical strategy")
    return item.to_dict()


def list_strategies(
    *,
    mode: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    mode_key = str(mode or "").strip().lower()
    source_key = str(source or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for item in STRATEGIES:
        if mode_key and mode_key not in item.modes:
            continue
        if source_key and source_key != item.source.lower():
            continue
        rows.append(item.to_dict())
    return rows


def get_strategy(strategy_id: str) -> dict[str, Any]:
    key = str(strategy_id or "").strip().lower()
    item = _BY_ID.get(key)
    if item is None:
        raise KeyError(f"unknown strategy_id: {strategy_id}")
    return item.to_dict()


def registry_readiness() -> dict[str, Any]:
    required = sorted({name for item in STRATEGIES for name in item.indicators})
    notebook = sum(1 for item in STRATEGIES if item.source == "user_notebook")
    templates = sum(1 for item in STRATEGIES if item.source == "template")
    return {
        "status": "ready",
        "version": REGISTRY_VERSION,
        "strategies": len(STRATEGIES),
        "user_notebook_strategies": notebook,
        "user_analysis_strategies": sum(item.source == "user_analysis" for item in STRATEGIES),
        "intraday_short_strategies": sum(item.direction == "SHORT" for item in STRATEGIES),
        "template_strategies": templates,
        "paper_eligible_strategies": sum(1 for item in STRATEGIES if item.paper_eligible),
        "required_indicators": required,
        "execution_wiring": "R72.5.6_restart_safe_strategy_paper",
        "paper_execution_wiring": "explicit_validation_plus_R67.2_gate",
        "runtime_persistence_wiring": "sqlite_scan_validation_execution_lineage",
        "scan_started": False,
        "backtest_started": False,
        "paper_orders_created": False,
    }


__all__ = [
    "REGISTRY_VERSION",
    "STRATEGIES",
    "StrategyDefinition",
    "get_strategy",
    "list_strategies",
    "registry_readiness",
]
