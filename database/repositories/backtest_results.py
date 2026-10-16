"""Repository for legacy summaries and detailed backtest runs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from database.database import Database


class BacktestResultsRepository:
    SUMMARY_FIELDS = (
        "strategy_name",
        "symbol",
        "timeframe",
        "start_date",
        "end_date",
        "total_trades",
        "win_rate",
        "net_profit",
        "max_drawdown",
        "sharpe_ratio",
        "created_at",
    )
    DETAIL_FIELDS = (
        "run_id",
        "strategy_version",
        "status",
        "initial_capital",
        "final_capital",
        "return_pct",
        "buy_hold_return_pct",
        "profit_factor",
        "expectancy",
        "exposure_pct",
        "cost_bps",
        "slippage_bps",
        "parameters_json",
        "result_json",
    )
    FIELDS = SUMMARY_FIELDS + DETAIL_FIELDS

    def __init__(
        self,
        db: Database | None = None,
        db_path: str | None = None,
    ) -> None:
        self._owns_database = db is None
        self.db = db or Database(db_path)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _decode(row) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for field in ("parameters_json", "result_json"):
            raw = result.pop(field, None)
            try:
                value = json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                value = {}
            result[field.removesuffix("_json")] = (
                value if isinstance(value, dict) else {}
            )
        return result

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data or {})
        if not payload.get("created_at"):
            payload["created_at"] = self._timestamp()

        values: list[Any] = []
        for field in self.FIELDS:
            if field == "parameters_json":
                values.append(
                    json.dumps(
                        payload.get("parameters") or {},
                        sort_keys=True,
                    )
                )
            elif field == "result_json":
                values.append(
                    json.dumps(
                        payload.get("result") or {},
                        sort_keys=True,
                    )
                )
            else:
                values.append(payload.get(field))

        placeholders = ", ".join("?" for _ in self.FIELDS)
        self.db.execute(
            "INSERT INTO backtest_results ("
            + ", ".join(self.FIELDS)
            + ") VALUES ("
            + placeholders
            + ")",
            tuple(values),
        )

        run_id = str(payload.get("run_id") or "").strip()
        if run_id:
            return self.by_run_id(run_id) or payload

        row = self.db.fetchone(
            """
            SELECT *
            FROM backtest_results
            ORDER BY id DESC
            LIMIT 1
            """
        )
        return self._decode(row) or payload

    def latest(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT *
            FROM backtest_results
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        )
        return [
            item
            for item in (self._decode(row) for row in rows)
            if item is not None
        ]

    def by_run_id(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT *
            FROM backtest_results
            WHERE run_id=?
            LIMIT 1
            """,
            (str(run_id or "").strip(),),
        )
        return self._decode(row)

    def by_symbol(
        self,
        symbol: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT *
            FROM backtest_results
            WHERE symbol=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                str(symbol or "").strip().upper(),
                max(1, min(int(limit), 500)),
            ),
        )
        return [
            item
            for item in (self._decode(row) for row in rows)
            if item is not None
        ]

    def count(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) AS total FROM backtest_results"
        )
        return int(row["total"] or 0) if row is not None else 0

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["BacktestResultsRepository"]
