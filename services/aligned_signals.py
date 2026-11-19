"""One causal signal pass per native bar, retaining scanner consensus semantics."""

from scanner import approved_strategies as rules
from scanner.strategy_registry import get_strategy, list_strategies


def entry_consensus(evaluations):
    buys = [e for e in evaluations if e.get("signal") == "BUY"]
    sells = [e for e in evaluations if e.get("signal") == "SELL"]
    if buys and sells:
        return {
            "consensus": "CONFLICT",
            "consensus_score": min(
                100.0,
                sum(e["score"] for e in buys) / len(buys) * 0.75
                + min(len(buys), 3) * 5,
            ),
            "count": len(buys) + len(sells),
        }
    entries = buys or sells
    score = (
        min(
            100.0,
            sum(e["score"] for e in entries) / len(entries) * 0.75
            + min(len(entries), 3) * 5,
        )
        if entries
        else 0
    )
    strong = (
        len(entries) >= 2
        and score >= 80
        and (
            bool(sells)
            or any(
                get_strategy(e["strategy_id"])["source"] == "user_notebook"
                for e in buys
            )
        )
    )
    return {
        "consensus": ("STRONG_SELL" if strong else "SELL")
        if sells
        else ("STRONG_BUY" if strong else "BUY")
        if buys
        else "NEUTRAL",
        "consensus_score": score,
        "count": len(entries),
    }


def signals(frame, mode, *, strategy_ids=None):
    from backtest.indicator_rows import indicator_rows

    keys = [
        s["strategy_id"]
        for s in list_strategies(mode=mode)
        if s["strategy_id"] in rules.APPROVED_IDS
        and not rules.exit_only(s["strategy_id"], mode)
    ]
    # Include opposing armed entries in consensus even if one strategy alone
    # is being measured; this matches a source=all live scan.
    contexts = {key: rules.context_for(key, mode) for key in keys}
    iterator = indicator_rows(frame, rules.KEYS)
    previous = next(iterator)
    result = {}
    for offset, current in enumerate(iterator, 1):
        entries = []
        for key in keys:
            context = contexts[key]
            if all(rules.native_entry_checks(key, previous, current, context).values()):
                entry = rules.evaluate(previous, current, context, key)
                if entry["entry_state"] == "ARMED":
                    entries.append(entry)
        if entries:
            result[current.name] = {
                **entry_consensus(entries),
                "offset": offset,
                "evaluations": {
                    e["strategy_id"]: e
                    for e in entries
                    if strategy_ids is None or e["strategy_id"] in strategy_ids
                },
            }
        previous = current
    return result
