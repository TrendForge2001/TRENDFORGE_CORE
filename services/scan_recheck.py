"""Recheck failed evidence at the saved scan's market-data cutoff."""

from datetime import datetime


def failed_symbols(batch):
    report = batch.get("report") or {}
    if (
        batch.get("kind") != "scan"
        or batch.get("status") != "completed"
        or batch["request"].get("scan_retry_of")
        or report.get("report_type") != "scanner_indicator_snapshot"
    ):
        return []
    return list(
        dict.fromkeys(
            row["symbol"]
            for row in report.get("rows", [])
            if row.get("signal") == "ERROR" and row.get("symbol")
        )
    )


def retry_request(repository, batch):
    symbols = failed_symbols(batch)
    if not symbols:
        raise ValueError("Choose a completed single-strategy scan with failed symbols")
    recheck = latest_recheck(repository, batch)
    if recheck:
        recovered = {
            row["symbol"] for row in recheck["rows"] if row.get("signal") != "ERROR"
        }
        symbols = [symbol for symbol in symbols if symbol not in recovered]
    if not symbols:
        raise ValueError("All failed symbols in this scan have recovered")
    cutoff = datetime.fromisoformat(batch.get("started_at") or batch["created_at"])
    if cutoff.utcoffset() is None:
        raise ValueError("This scan has no reliable market-data cutoff")
    return {
        "symbols": symbols,
        "scan_retry_of": batch["batch_id"],
        "scan_cutoff": cutoff.isoformat(),
        "strategy_id": batch["strategy_id"],
        "horizon": batch["horizon"],
        "stock_list": batch["stock_list"],
        "period": batch["report"].get("period"),
    }


def latest_recheck(repository, batch):
    from services.scanner_workflow import leaf_batches

    symbols = set(failed_symbols(batch))
    rows = {}
    retry_id = None
    for retry in repository.completed_scan_retries(batch["batch_id"]):
        retry_id = retry["batch_id"]
        for leaf in leaf_batches(repository, retry):
            for row in leaf["report"]["rows"]:
                symbol = row.get("symbol")
                if symbol in symbols and (
                    symbol not in rows or rows[symbol].get("signal") == "ERROR"
                ):
                    rows[symbol] = row
    return {"batch_id": retry_id, "rows": list(rows.values())} if retry_id else None
