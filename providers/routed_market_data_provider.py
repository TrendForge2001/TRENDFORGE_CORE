"""Provider router for canonical historical market data."""

from __future__ import annotations

from typing import Any

import pandas as pd


class RoutedMarketDataProvider:
    """Try providers in configured order while preserving one OHLCV interface."""

    def __init__(self, providers: list[Any], fallback_on_error: bool = True):
        if not providers:
            raise ValueError("At least one market-data provider is required")
        self.providers = list(providers)
        self.fallback_on_error = bool(fallback_on_error)
        self.last_provider: dict[str, str] = {}
        self.last_errors: dict[str, list[str]] = {}

    def candles(self, symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        errors: list[str] = []
        for provider in self.providers:
            try:
                method = getattr(provider, "candles", None)
                if not callable(method):
                    raise AttributeError("Provider does not implement candles()")
                frame = method(symbol, period=period, interval=interval)
                if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
                    raise ValueError("Provider returned no candle data")
                self.last_provider[symbol.upper()] = provider.__class__.__name__
                self.last_errors[symbol.upper()] = errors
                return frame
            except Exception as exc:
                errors.append(f"{provider.__class__.__name__}: {exc}")
                if not self.fallback_on_error:
                    break
        self.last_errors[symbol.upper()] = errors
        raise RuntimeError(f"All market-data providers failed for {symbol}: {' | '.join(errors)}")

    def batch_candles_with_errors(
        self,
        symbols: list[str],
        period: str = "1y",
        interval: str = "1d",
    ) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
        """Resolve a batch provider-by-provider without dropping symbols."""
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in symbols or []:
            symbol = str(raw or "").strip().upper()
            if symbol and symbol not in seen:
                ordered.append(symbol)
                seen.add(symbol)

        unresolved = list(ordered)
        results: dict[str, pd.DataFrame] = {}
        errors_by_symbol: dict[str, list[str]] = {
            symbol: [] for symbol in ordered
        }

        for provider in self.providers:
            if not unresolved:
                break

            batch = getattr(provider, "batch_candles_with_errors", None)
            if callable(batch):
                try:
                    found, failures = batch(
                        unresolved,
                        period=period,
                        interval=interval,
                    )
                except Exception as exc:
                    found = {}
                    failures = {
                        symbol: str(exc)
                        for symbol in unresolved
                    }

                for symbol, frame in (found or {}).items():
                    key = str(symbol).strip().upper()
                    if key in unresolved and isinstance(frame, pd.DataFrame) and not frame.empty:
                        results[key] = frame
                        self.last_provider[key] = provider.__class__.__name__

                for symbol in list(unresolved):
                    if symbol in results:
                        continue
                    message = (failures or {}).get(symbol)
                    if message:
                        errors_by_symbol[symbol].append(
                            f"{provider.__class__.__name__}: {message}"
                        )
            else:
                for symbol in list(unresolved):
                    try:
                        method = getattr(provider, "candles", None)
                        if not callable(method):
                            raise AttributeError(
                                "Provider does not implement candles()"
                            )
                        frame = method(
                            symbol,
                            period=period,
                            interval=interval,
                        )
                        if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
                            raise ValueError(
                                "Provider returned no candle data"
                            )
                        results[symbol] = frame
                        self.last_provider[symbol] = provider.__class__.__name__
                    except Exception as exc:
                        errors_by_symbol[symbol].append(
                            f"{provider.__class__.__name__}: {exc}"
                        )

            unresolved = [
                symbol for symbol in unresolved
                if symbol not in results
            ]
            if unresolved and not self.fallback_on_error:
                break

        failures: dict[str, str] = {}
        for symbol in unresolved:
            messages = errors_by_symbol.get(symbol) or []
            failures[symbol] = (
                "All market-data providers failed for "
                f"{symbol}: {' | '.join(messages)}"
            )
            self.last_errors[symbol] = list(messages)

        for symbol in results:
            self.last_errors[symbol] = list(
                errors_by_symbol.get(symbol) or []
            )

        return results, failures

    def health(self) -> dict[str, Any]:
        provider_health: dict[str, dict[str, Any]] = {}
        statuses: list[str] = []
        for provider in self.providers:
            name = provider.__class__.__name__
            health = getattr(provider, "health", None)
            if not callable(health):
                provider_health[name] = {"status": "configured"}
                statuses.append("configured")
                continue
            try:
                payload = health()
                payload = payload if isinstance(payload, dict) else {"status": "unknown"}
            except Exception as exc:
                payload = {"status": "degraded", "error": str(exc)}
            provider_health[name] = payload
            statuses.append(str(payload.get("status", "unknown")).lower())
        status = (
            "degraded"
            if any(item in {"degraded", "unavailable"} for item in statuses)
            else "healthy"
            if statuses and all(item in {"healthy", "ok"} for item in statuses)
            else "configured"
        )
        return {
            "status": status,
            "providers": [provider.__class__.__name__ for provider in self.providers],
            "provider_health": provider_health,
            "fallback_on_error": self.fallback_on_error,
        }


__all__ = ["RoutedMarketDataProvider"]
