"""Provider router for canonical historical market data."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .market_data_provider import ProviderAuthenticationError


class RoutedMarketDataProvider:
    """Try providers in configured order while preserving one OHLCV interface."""

    def __init__(
        self,
        providers: list[Any],
        fallback_on_error: bool = True,
        symbol_resolver: Any | None = None,
    ):
        if not providers:
            raise ValueError("At least one market-data provider is required")
        self.providers = list(providers)
        self.fallback_on_error = bool(fallback_on_error)
        self.symbol_resolver = symbol_resolver
        self.last_provider: dict[str, str] = {}
        self.last_errors: dict[str, list[str]] = {}

    def begin_observation(self) -> None:
        """Reset per-run provider attribution before a production scan."""
        self.last_provider = {}
        self.last_errors = {}

    def observability_snapshot(
        self,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        requested = {
            str(symbol or "").strip().upper()
            for symbol in (symbols or [])
            if str(symbol or "").strip()
        }

        providers = (
            {
                symbol: provider
                for symbol, provider in self.last_provider.items()
                if not requested or symbol in requested
            }
        )
        errors = (
            {
                symbol: list(messages)
                for symbol, messages in self.last_errors.items()
                if not requested or symbol in requested
            }
        )

        provider_counts: dict[str, int] = {}
        fallback_count = 0
        nse_resolution_count = 0

        primary_name = (
            self.providers[0].__class__.__name__
            if self.providers
            else None
        )

        for provider_name in providers.values():
            provider_counts[provider_name] = (
                provider_counts.get(provider_name, 0) + 1
            )
            if primary_name and not provider_name.startswith(primary_name):
                fallback_count += 1
            if "[NSE:" in provider_name:
                nse_resolution_count += 1

        return {
            "provider_counts": provider_counts,
            "fallback_count": fallback_count,
            "nse_resolution_count": nse_resolution_count,
            "providers_by_symbol": providers,
            "provider_errors_by_symbol": errors,
        }

    def set_symbol_aliases(self, aliases: dict[str, str] | None) -> None:
        for provider_index, provider in enumerate(self.providers):
            setter = getattr(provider, "set_symbol_aliases", None)
            if callable(setter):
                setter(aliases)

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

    def _resolve_failed_symbols_with_nse(
        self,
        symbols: list[str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        resolver = self.symbol_resolver
        method = getattr(resolver, "resolve_equity_symbol", None)
        if not callable(method):
            return {}, {}

        resolved: dict[str, str] = {}
        failures: dict[str, str] = {}
        for symbol in symbols:
            try:
                candidate = method(symbol)
                candidate = str(candidate or "").strip().upper()
                if candidate:
                    resolved[symbol] = candidate
                else:
                    failures[symbol] = "NSE returned no active equity symbol"
            except Exception as exc:
                failures[symbol] = str(exc)
        return resolved, failures

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

        for provider_index, provider in enumerate(self.providers):
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
                except ProviderAuthenticationError:
                    raise
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

            if provider_index == 0 and unresolved and self.symbol_resolver is not None:
                resolved_map, resolver_failures = (
                    self._resolve_failed_symbols_with_nse(unresolved)
                )

                retry_method = getattr(provider, "candles", None)
                if callable(retry_method):
                    for canonical in list(unresolved):
                        resolved_symbol = resolved_map.get(canonical)
                        if not resolved_symbol:
                            message = resolver_failures.get(canonical)
                            if message:
                                errors_by_symbol[canonical].append(
                                    f"NSESymbolResolver: {message}"
                                )
                            continue

                        if resolved_symbol == canonical:
                            errors_by_symbol[canonical].append(
                                "NSESymbolResolver: symbol confirmed active"
                            )
                            continue

                        try:
                            frame = retry_method(
                                resolved_symbol,
                                period=period,
                                interval=interval,
                            )
                            if (
                                frame is None
                                or not isinstance(frame, pd.DataFrame)
                                or frame.empty
                            ):
                                raise ValueError(
                                    "Provider returned no candle data "
                                    f"for NSE-resolved symbol {resolved_symbol}"
                                )
                            results[canonical] = frame
                            self.last_provider[canonical] = (
                                f"{provider.__class__.__name__}"
                                f"[NSE:{resolved_symbol}]"
                            )
                        except ProviderAuthenticationError:
                            raise
                        except Exception as exc:
                            errors_by_symbol[canonical].append(
                                "NSESymbolResolver: resolved "
                                f"{canonical}->{resolved_symbol}; "
                                f"{provider.__class__.__name__} retry failed: {exc}"
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
            "symbol_resolver": (
                self.symbol_resolver.__class__.__name__
                if self.symbol_resolver is not None
                else None
            ),
        }


__all__ = ["RoutedMarketDataProvider"]
