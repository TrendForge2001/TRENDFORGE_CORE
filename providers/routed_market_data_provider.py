"""Provider router for canonical historical market data."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .market_data_provider import ProviderAuthenticationError
from .provider_circuit_breaker import ProviderCircuitBreaker


class RoutedMarketDataProvider:
    """Try providers in configured order while preserving one OHLCV interface."""

    SYSTEMIC_ERROR_MARKERS = (
        "429",
        "too many requests",
        "rate limit",
        "rate_limited",
        "cooldown active",
        "access cooldown",
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "http 502",
        "http 503",
        "http 504",
        "status code 502",
        "status code 503",
        "status code 504",
        "forbidden",
        "http 403",
        "status code 403",
    )

    def __init__(
        self,
        providers: list[Any],
        fallback_on_error: bool = True,
        symbol_resolver: Any | None = None,
        *,
        failure_threshold: int = 2,
        cooldown_seconds: float = 120.0,
    ):
        if not providers:
            raise ValueError("At least one market-data provider is required")
        self.providers = list(providers)
        self.fallback_on_error = bool(fallback_on_error)
        self.symbol_resolver = symbol_resolver
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds))
        self.last_provider: dict[str, str] = {}
        self.last_errors: dict[str, list[str]] = {}
        self._circuits = {
            provider.__class__.__name__: ProviderCircuitBreaker(
                provider.__class__.__name__,
                failure_threshold=self.failure_threshold,
                cooldown_seconds=self.cooldown_seconds,
            )
            for provider in self.providers
        }
        self._circuit_skip_count = 0
        self._circuit_events: list[dict[str, Any]] = []
        self._nse_resolver_attempts = 0
        self._nse_resolver_skips = 0

    @classmethod
    def _is_systemic_error(cls, error: Exception | str | None) -> bool:
        text = str(error or "").strip().lower()
        return bool(text) and any(
            marker in text
            for marker in cls.SYSTEMIC_ERROR_MARKERS
        )

    def _breaker(self, provider: Any) -> ProviderCircuitBreaker:
        name = provider.__class__.__name__
        breaker = self._circuits.get(name)
        if breaker is None:
            breaker = ProviderCircuitBreaker(
                name,
                failure_threshold=self.failure_threshold,
                cooldown_seconds=self.cooldown_seconds,
            )
            self._circuits[name] = breaker
        return breaker

    def _record_circuit_event(
        self,
        provider: str,
        event: str,
        **details: Any,
    ) -> None:
        self._circuit_events.append(
            {
                "provider": provider,
                "event": event,
                **details,
            }
        )

    def begin_observation(self) -> None:
        """Reset per-run attribution while preserving circuit cooldown state."""
        self.last_provider = {}
        self.last_errors = {}
        self._circuit_skip_count = 0
        self._circuit_events = []
        self._nse_resolver_attempts = 0
        self._nse_resolver_skips = 0

    def observability_snapshot(
        self,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        requested = {
            str(symbol or "").strip().upper()
            for symbol in (symbols or [])
            if str(symbol or "").strip()
        }

        providers = {
            symbol: provider
            for symbol, provider in self.last_provider.items()
            if not requested or symbol in requested
        }
        errors = {
            symbol: list(messages)
            for symbol, messages in self.last_errors.items()
            if not requested or symbol in requested
        }

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
            "circuit_breakers": {
                name: breaker.health()
                for name, breaker in self._circuits.items()
            },
            "circuit_skip_count": self._circuit_skip_count,
            "circuit_events": list(self._circuit_events),
            "nse_resolver_attempts": self._nse_resolver_attempts,
            "nse_resolver_skips": self._nse_resolver_skips,
        }

    def set_symbol_aliases(self, aliases: dict[str, str] | None) -> None:
        for provider in self.providers:
            setter = getattr(provider, "set_symbol_aliases", None)
            if callable(setter):
                setter(aliases)

    def candles(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        errors: list[str] = []
        key = str(symbol or "").strip().upper()

        for provider in self.providers:
            provider_name = provider.__class__.__name__
            breaker = self._breaker(provider)
            if not breaker.allow_request():
                health = breaker.health()
                message = (
                    f"{provider_name}: circuit open; retry in "
                    f"{health['retry_after_seconds']}s"
                )
                errors.append(message)
                self._circuit_skip_count += 1
                self._record_circuit_event(
                    provider_name,
                    "skipped_open_circuit",
                    symbol=key,
                    retry_after_seconds=health["retry_after_seconds"],
                )
                continue

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
                if (
                    frame is None
                    or not isinstance(frame, pd.DataFrame)
                    or frame.empty
                ):
                    raise ValueError("Provider returned no candle data")
                breaker.record_success()
                self.last_provider[key] = provider_name
                self.last_errors[key] = errors
                return frame
            except ProviderAuthenticationError:
                raise
            except Exception as exc:
                errors.append(f"{provider_name}: {exc}")
                if self._is_systemic_error(exc):
                    opened = breaker.record_failure(exc)
                    self._record_circuit_event(
                        provider_name,
                        "systemic_failure",
                        symbol=key,
                        opened=opened,
                        error=str(exc),
                    )
                if not self.fallback_on_error:
                    break

        self.last_errors[key] = errors
        raise RuntimeError(
            f"All market-data providers failed for {symbol}: "
            + " | ".join(errors)
        )

    def _resolver_cooldown_message(self) -> str | None:
        resolver = self.symbol_resolver
        health_method = getattr(resolver, "health", None)
        if not callable(health_method):
            return None
        try:
            payload = health_method()
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None

        retry_after = int(payload.get("retry_after_seconds") or 0)
        runtime_status = str(
            payload.get("runtime_status") or ""
        ).strip().lower()
        if retry_after > 0 or runtime_status in {
            "rate_limited",
            "access_blocked",
        }:
            return (
                "NSE resolver cooldown active"
                + (
                    f"; retry in {retry_after}s"
                    if retry_after > 0
                    else ""
                )
            )
        return None

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
        systemic_failures = 0
        systemic_budget = 2

        for index, symbol in enumerate(symbols):
            cooldown = self._resolver_cooldown_message()
            if cooldown:
                remaining = symbols[index:]
                for pending in remaining:
                    failures[pending] = cooldown
                self._nse_resolver_skips += len(remaining)
                self._record_circuit_event(
                    resolver.__class__.__name__,
                    "resolver_cooldown_skip",
                    symbols=len(remaining),
                    reason=cooldown,
                )
                break

            if systemic_failures >= systemic_budget:
                remaining = symbols[index:]
                reason = (
                    "NSE resolver failure budget exhausted for this batch"
                )
                for pending in remaining:
                    failures[pending] = reason
                self._nse_resolver_skips += len(remaining)
                self._record_circuit_event(
                    resolver.__class__.__name__,
                    "resolver_failure_budget_exhausted",
                    symbols=len(remaining),
                )
                break

            self._nse_resolver_attempts += 1
            try:
                candidate = method(symbol)
                candidate = str(candidate or "").strip().upper()
                if candidate:
                    resolved[symbol] = candidate
                else:
                    failures[symbol] = (
                        "NSE returned no active equity symbol"
                    )
            except Exception as exc:
                failures[symbol] = str(exc)
                if self._is_systemic_error(exc):
                    systemic_failures += 1

        return resolved, failures

    def _record_batch_breaker_outcome(
        self,
        provider: Any,
        requested: list[str],
        found: dict[str, pd.DataFrame] | None,
        failures: dict[str, str] | None,
        batch_exception: Exception | None = None,
    ) -> None:
        breaker = self._breaker(provider)
        provider_name = provider.__class__.__name__

        if found:
            breaker.record_success()
            return

        messages = list((failures or {}).values())
        systemic = (
            self._is_systemic_error(batch_exception)
            if batch_exception is not None
            else any(self._is_systemic_error(item) for item in messages)
        )
        if not systemic:
            return

        reason = (
            str(batch_exception)
            if batch_exception is not None
            else next(
                (
                    message
                    for message in messages
                    if self._is_systemic_error(message)
                ),
                "systemic upstream failure",
            )
        )
        opened = breaker.record_failure(reason)
        self._record_circuit_event(
            provider_name,
            "systemic_batch_failure",
            requested=len(requested),
            opened=opened,
            error=reason,
        )

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

            provider_name = provider.__class__.__name__
            breaker = self._breaker(provider)
            if not breaker.allow_request():
                health = breaker.health()
                message = (
                    f"{provider_name}: circuit open; retry in "
                    f"{health['retry_after_seconds']}s"
                )
                for symbol in unresolved:
                    errors_by_symbol[symbol].append(message)
                self._circuit_skip_count += len(unresolved)
                self._record_circuit_event(
                    provider_name,
                    "skipped_open_circuit",
                    symbols=len(unresolved),
                    retry_after_seconds=health["retry_after_seconds"],
                )
                if unresolved and not self.fallback_on_error:
                    break
                continue

            requested_for_provider = list(unresolved)
            batch_exception: Exception | None = None
            found: dict[str, pd.DataFrame] = {}
            failures: dict[str, str] = {}

            batch = getattr(
                provider,
                "batch_candles_with_errors",
                None,
            )
            if callable(batch):
                try:
                    raw_found, raw_failures = batch(
                        unresolved,
                        period=period,
                        interval=interval,
                    )
                    found = dict(raw_found or {})
                    failures = dict(raw_failures or {})
                except ProviderAuthenticationError:
                    raise
                except Exception as exc:
                    batch_exception = exc
                    found = {}
                    failures = {
                        symbol: str(exc)
                        for symbol in unresolved
                    }

                for symbol, frame in found.items():
                    key = str(symbol).strip().upper()
                    if (
                        key in unresolved
                        and isinstance(frame, pd.DataFrame)
                        and not frame.empty
                    ):
                        results[key] = frame
                        self.last_provider[key] = provider_name

                for symbol in list(unresolved):
                    if symbol in results:
                        continue
                    message = failures.get(symbol)
                    if message:
                        errors_by_symbol[symbol].append(
                            f"{provider_name}: {message}"
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
                        if (
                            frame is None
                            or not isinstance(frame, pd.DataFrame)
                            or frame.empty
                        ):
                            raise ValueError(
                                "Provider returned no candle data"
                            )
                        found[symbol] = frame
                        results[symbol] = frame
                        self.last_provider[symbol] = provider_name
                    except ProviderAuthenticationError:
                        raise
                    except Exception as exc:
                        failures[symbol] = str(exc)
                        errors_by_symbol[symbol].append(
                            f"{provider_name}: {exc}"
                        )

            self._record_batch_breaker_outcome(
                provider,
                requested_for_provider,
                found,
                failures,
                batch_exception=batch_exception,
            )

            unresolved = [
                symbol
                for symbol in unresolved
                if symbol not in results
            ]

            if (
                provider_index == 0
                and unresolved
                and self.symbol_resolver is not None
            ):
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

                        if not breaker.allow_request():
                            health = breaker.health()
                            errors_by_symbol[canonical].append(
                                f"{provider_name}: circuit open before "
                                "NSE-resolved retry; retry in "
                                f"{health['retry_after_seconds']}s"
                            )
                            self._circuit_skip_count += 1
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
                            breaker.record_success()
                            results[canonical] = frame
                            self.last_provider[canonical] = (
                                f"{provider_name}"
                                f"[NSE:{resolved_symbol}]"
                            )
                        except ProviderAuthenticationError:
                            raise
                        except Exception as exc:
                            if self._is_systemic_error(exc):
                                opened = breaker.record_failure(exc)
                                self._record_circuit_event(
                                    provider_name,
                                    "nse_resolved_retry_systemic_failure",
                                    symbol=canonical,
                                    opened=opened,
                                    error=str(exc),
                                )
                            errors_by_symbol[canonical].append(
                                "NSESymbolResolver: resolved "
                                f"{canonical}->{resolved_symbol}; "
                                f"{provider_name} retry failed: {exc}"
                            )

                unresolved = [
                    symbol
                    for symbol in unresolved
                    if symbol not in results
                ]

            if unresolved and not self.fallback_on_error:
                break

        failures_out: dict[str, str] = {}
        for symbol in unresolved:
            messages = errors_by_symbol.get(symbol) or []
            failures_out[symbol] = (
                "All market-data providers failed for "
                f"{symbol}: {' | '.join(messages)}"
            )
            self.last_errors[symbol] = list(messages)

        for symbol in results:
            self.last_errors[symbol] = list(
                errors_by_symbol.get(symbol) or []
            )

        return results, failures_out

    def health(self) -> dict[str, Any]:
        provider_health: dict[str, dict[str, Any]] = {}
        statuses: list[str] = []

        for provider in self.providers:
            name = provider.__class__.__name__
            health = getattr(provider, "health", None)
            if not callable(health):
                payload = {"status": "configured"}
            else:
                try:
                    payload = health()
                    payload = (
                        payload
                        if isinstance(payload, dict)
                        else {"status": "unknown"}
                    )
                except Exception as exc:
                    payload = {
                        "status": "degraded",
                        "error": str(exc),
                    }

            circuit = self._breaker(provider).health()
            if circuit["state"] == "open":
                payload = dict(payload)
                payload["status"] = "degraded"
                payload["circuit"] = circuit

            provider_health[name] = payload
            statuses.append(
                str(payload.get("status", "unknown")).lower()
            )

        circuit_health = {
            name: breaker.health()
            for name, breaker in self._circuits.items()
        }
        if any(
            item["state"] == "open"
            for item in circuit_health.values()
        ):
            statuses.append("degraded")

        status = (
            "degraded"
            if any(
                item in {"degraded", "unavailable"}
                for item in statuses
            )
            else "healthy"
            if statuses
            and all(item in {"healthy", "ok"} for item in statuses)
            else "configured"
        )
        return {
            "status": status,
            "providers": [
                provider.__class__.__name__
                for provider in self.providers
            ],
            "provider_health": provider_health,
            "fallback_on_error": self.fallback_on_error,
            "symbol_resolver": (
                self.symbol_resolver.__class__.__name__
                if self.symbol_resolver is not None
                else None
            ),
            "circuit_breakers": circuit_health,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
        }


__all__ = ["RoutedMarketDataProvider"]
