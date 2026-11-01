"""Next-candle EMA/pivot paper triggers using the canonical admission boundary."""

import threading
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from scanner.ema_pivot_scanner import pivot_plan
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from scanner.strategy_registry import REGISTRY_VERSION, get_strategy
from services.staged_paper_plan import new_plan
from services.technical_trading_service import TechnicalTradingService


class StagedPaperExecution:
    KEY = "paper.ema-pivot.pending.v1"
    TZ = ZoneInfo("Asia/Kolkata")

    def __init__(self, auto_entry, repository, quotes):
        self.auto, self.repository, self.quotes = auto_entry, repository, quotes
        # Restart deliberately cancels unfilled triggers. Existing positions
        # recover their protective state from the trade ledger independently.
        self.pending = {}
        self._poll_lock = threading.Lock()
        self.last_result = {"status": "idle", "opened_count": 0}
        try:
            previous = repository.load_state(self.KEY) or {}
            self.last_result["cancelled_on_restart_count"] = len(
                previous.get("payload", {}).get("pending", [])
            )
        except Exception:
            self.last_result["pending_recovery_status"] = "unavailable_cancelled"

    def _save(self):
        self.repository.save_state(
            self.KEY,
            "paper_pending_triggers",
            {"pending": list(self.pending.values()), "last_result": self.last_result},
        )

    def cancel(self):
        self.pending.clear()
        self.last_result = {"status": "cancelled", "opened_count": 0}
        self._save()

    @classmethod
    def window(cls, bar, mode):
        stamp = datetime.fromisoformat(bar)
        stamp = (
            stamp.replace(tzinfo=cls.TZ)
            if stamp.tzinfo is None
            else stamp.astimezone(cls.TZ)
        )
        if mode == "intraday":
            return stamp + timedelta(minutes=15), stamp + timedelta(minutes=30)
        day = stamp.date() + timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        return datetime.combine(day, time(9, 15), cls.TZ), datetime.combine(
            day, time(15, 30), cls.TZ
        )

    @staticmethod
    def eligible(validation, key, mode, universe):
        if (
            validation.get("status") != "completed"
            or validation.get("registry_version") != REGISTRY_VERSION
        ):
            return False
        return any(
            row.get("strategy_id") == key
            and row.get("mode") == mode
            and row.get("promotion_status") == "ELIGIBLE_FOR_REVIEW"
            and row.get("registry_paper_eligible") is True
            and any(
                gate.get("universe") == universe and gate.get("status") == "PASS"
                for gate in row.get("universe_gates", [])
            )
            for row in validation.get("strategy_validation", [])
        )

    def arm(self, scan, validation, strategy_ids, *, short_borrow_assumed, now):
        outcomes = []
        complete = (
            scan.get("status") == "completed"
            and scan.get("error_symbols") == 0
            and scan.get("requested_symbols", 0) > 0
            and scan.get("completed_symbols") == scan.get("requested_symbols")
        )
        for key in strategy_ids:
            blockers = []
            matches = sum(
                evaluation.get("strategy_id") == key
                and evaluation.get("entry_state") == "ARMED"
                for candidate in scan.get("top_picks", [])
                for evaluation in candidate.get("strategy_evaluations", [])
            )
            if not complete:
                blockers.append("scan_not_fully_completed")
            if not self.eligible(validation, key, scan["mode"], scan["universe"]):
                blockers.append("strategy_not_validation_eligible")
            if EMA_PIVOT_SETUPS[key].direction == -1 and not short_borrow_assumed:
                blockers.append("paper_short_availability_assumption_required")
            armed = 0
            expired = 0
            if not blockers:
                for candidate in scan.get("top_picks", []):
                    if candidate.get("consensus") == "CONFLICT":
                        continue
                    for evaluation in candidate.get("strategy_evaluations", []):
                        if (
                            evaluation.get("strategy_id") != key
                            or evaluation.get("entry_state") != "ARMED"
                        ):
                            continue
                        risk = evaluation["risk"]
                        start, end = self.window(candidate["bar_at"], scan["mode"])
                        if now >= end:
                            expired += 1
                            continue
                        token = (
                            f"{key}:{scan['mode']}:{candidate['symbol']}:"
                            f"{candidate['bar_at']}"
                        )
                        self.pending[token] = {
                            "token": token,
                            "strategy_id": key,
                            "symbol": candidate["symbol"],
                            "mode": scan["mode"],
                            "universe": scan["universe"],
                            "scan_run_id": scan["run_id"],
                            "validation_run_id": validation["run_id"],
                            "entry_bar_at": candidate["bar_at"],
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                            "risk": risk,
                            "score": evaluation["score"],
                            "confidence": candidate.get("consensus_score", 0),
                            "short_borrow_assumed": short_borrow_assumed,
                        }
                        armed += 1
            outcomes.append(
                {
                    "strategy_id": key,
                    "mode": scan["mode"],
                    "status": "blocked"
                    if blockers and (matches or not complete)
                    else "armed"
                    if armed
                    else "expired"
                    if expired
                    else "no_candidates",
                    "blockers": blockers if matches or not complete else [],
                    "eligibility_blockers": blockers,
                    "scanner_matches": matches,
                    "candidate_count": armed,
                    "expired_before_arming": expired,
                    "opened_count": 0,
                }
            )
        self._save()
        return outcomes

    def process(self, *, now, validation, admission_guard):
        if not self._poll_lock.acquire(blocking=False):
            return {"status": "busy", "opened_count": 0}
        try:
            return self._process(
                now=now, validation=validation, admission_guard=admission_guard
            )
        finally:
            self._poll_lock.release()

    def _process(self, *, now, validation, admission_guard):
        opened, events = [], []
        valid = []
        for token, candidate in list(self.pending.items()):
            if (
                now >= datetime.fromisoformat(candidate["end"])
                or candidate["validation_run_id"] != validation.get("run_id")
                or not self.eligible(
                    validation,
                    candidate["strategy_id"],
                    candidate["mode"],
                    candidate["universe"],
                )
            ):
                self.pending.pop(token, None)
                events.append(
                    {"symbol": candidate["symbol"], "status": "expired_or_invalidated"}
                )
            elif now >= datetime.fromisoformat(candidate["start"]):
                valid.append(candidate)
        if not valid:
            self.last_result = {
                "status": "waiting_for_trigger",
                "pending_count": len(self.pending),
                "opened_count": 0,
                "events": events,
            }
            self._save()
            return self.last_result
        quotes = self.quotes.prices(
            sorted({"NSE:" + row["symbol"] for row in valid}), now=now
        )
        triggered = {}
        conflicting = set()
        for row in sorted(
            valid, key=lambda r: (-r["score"], r["strategy_id"], r["symbol"])
        ):
            key, symbol = row["strategy_id"], row["symbol"]
            setup = EMA_PIVOT_SETUPS[key]
            quote = quotes.get("NSE:" + symbol)
            if quote is None:
                events.append({"symbol": symbol, "status": "fresh_quote_unavailable"})
                continue
            price = float(quote["last_price"])
            if setup.direction * (price - row["risk"]["entry_trigger"]) < 0:
                continue
            old = triggered.get(symbol)
            if (
                old
                and EMA_PIVOT_SETUPS[old["strategy_id"]].direction != setup.direction
            ):
                conflicting.add(symbol)
            triggered.setdefault(symbol, {**row, "quote": quote})
        positions = self.auto.paper_service.runtime.snapshot()["positions"]
        symbols_open = {row["symbol"] for row in positions}
        selected = [
            row
            for s, row in triggered.items()
            if s not in conflicting and s not in symbols_open
        ][: max(0, min(3, self.auto.max_open_positions) - len(positions))]
        committed = sum(
            float(row["quantity"]) * float(row["average_price"]) for row in positions
        )
        budget = max(0.0, self.auto.max_deployed_capital - committed)
        total_score = sum(row["score"] for row in selected)
        for row in selected:
            key, symbol = row["strategy_id"], row["symbol"]
            setup, risk = EMA_PIVOT_SETUPS[key], row["risk"]
            source = {
                "high": risk["signal_high"],
                "low": risk["signal_low"],
                "ATR_WILDER_14": risk["signal_atr"],
                **{
                    f"TRAD_{risk['pivot_period'].upper()}_{level}": value
                    for level, value in risk["pivot_levels"].items()
                },
            }
            plan = pivot_plan(
                setup,
                source,
                mode=row["mode"],
                tick_size=risk["tick_size_assumption"],
                entry=row["quote"]["last_price"],
            )
            if not plan or not plan["pivot_room_sufficient"]:
                self.pending.pop(row["token"], None)
                events.append({"symbol": symbol, "status": "gap_failed_pivot_room"})
                continue
            definition = get_strategy(key)
            adapter = {
                "symbol": symbol,
                "strategy_id": key,
                "strategy_name": definition["name"],
                "strategy_source": definition["source"],
                "technical_mode": row["mode"],
                "entry_bar_at": row["entry_bar_at"],
                "source_scan_run_id": row["scan_run_id"],
                "validation_run_id": row["validation_run_id"],
                "execution_eligible": True,
                "ranking_score": row["score"],
                "confidence": row.get("confidence", 0),
                "automation_quote_at": row["quote"]["timestamp"],
                "allocated_budget": budget * row["score"] / total_score,
                "paper_plan": new_plan(
                    key, plan, short_borrow_assumed=row["short_borrow_assumed"]
                ),
                "signal": {
                    "signal": "BUY" if setup.direction == 1 else "SELL",
                    "overall_score": row["score"],
                    "confidence": row.get("confidence", 0),
                    "entry": plan["entry"],
                    "stoploss": plan["stoploss"],
                    "target2": plan["target2"] or 0,
                },
            }
            stamp_frame = pd.DataFrame(index=pd.DatetimeIndex([row["entry_bar_at"]]))
            if TechnicalTradingService._execution_block_reason(
                stamp_frame, mode=row["mode"], now=now
            ):
                continue
            gate = self.auto.evaluate_candidate(adapter, now=now)
            if not gate["approved"]:
                events.append(
                    {
                        "symbol": symbol,
                        "status": "risk_blocked",
                        "reasons": gate["reasons"],
                    }
                )
                continue
            if not admission_guard(adapter):
                continue
            if not self.repository.claim_execution(
                scan_run_id=row["token"],
                validation_run_id=row["validation_run_id"],
                strategy_id=key,
                payload={"paper_only": True},
            ):
                self.pending.pop(row["token"], None)
                continue
            result = self.auto.process_scan(
                {"outcome": "completed", "execution_top_picks": [adapter]},
                run_id="staged:" + row["token"],
                execute_requested=True,
                now=now,
                admission_guard=admission_guard,
            )
            opened.extend(result.get("opened", []))
            events.extend(result.get("evaluations", []))
            self.pending.pop(row["token"], None)
        self.last_result = {
            "status": "opened" if opened else "waiting_for_trigger",
            "pending_count": len(self.pending),
            "opened_count": len(opened),
            "opened": opened,
            "events": events,
        }
        self._save()
        return self.last_result
