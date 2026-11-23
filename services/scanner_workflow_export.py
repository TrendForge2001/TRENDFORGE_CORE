"""Preserve complete simulated buy/sell evidence in password-encrypted Excel."""

import base64
import hashlib
import io
import math
import re
from collections import defaultdict

from openpyxl import Workbook, load_workbook

from core.report_access import encrypted_excel
from scanner.strategy_registry import get_strategy
from services.research_report import spreadsheet_value
from services.scanner_workflow import leaf_batches


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def profitability(workflow, job):
    if not job.get("batch_id") or job["status"] != "completed":
        return job["status"].replace("_", " ").title()
    batch = workflow.repository.get(job["batch_id"])
    if not batch or not batch.get("report"):
        return "Profitability unavailable — original evidence is missing"
    values = [
        finite((leaf.get("report") or {}).get("metrics", {}).get("net_profit"))
        for leaf in leaf_batches(workflow.repository, batch)
    ]
    if not values or any(value is None for value in values):
        return "Profitability unavailable — incomplete metrics"
    if len(values) == 1:
        metrics = batch["report"].get("metrics") or {}
        if metrics.get("total_trades") == 0:
            return "No trades"
        category = (
            "Profitable"
            if values[0] > 0
            else "Loss-making"
            if values[0] < 0
            else "Flat"
        )
        return f"{category} · ₹{values[0]:,.2f} net"
    label = (
        "Profitable"
        if all(value > 0 for value in values)
        else "Loss-making"
        if all(value < 0 for value in values)
        else "Mixed / flat"
    )
    return (
        f"{label} · independent accounts ₹{min(values):,.2f} to ₹{max(values):,.2f} net"
    )


def backtest_view(workflow):
    jobs = workflow.jobs()
    latest = {}
    for job in jobs:
        latest.setdefault((job["strategy_id"], job["horizon"]), job)
    pending = defaultdict(int)
    pending_ids = []
    for row in workflow.queue():
        if not row["job_id"]:
            pending[(row["strategy_id"], row["horizon"])] += 1
            pending_ids.append(row["queue_id"])
    keys = set(latest) | set(pending)
    rows = []
    for key in sorted(keys):
        job = latest.get(key)
        name = get_strategy(key[0])["name"]
        rows.append(
            {
                "strategy_id": key[0],
                "horizon": key[1],
                "strategy": name,
                "profitability": profitability(workflow, job) if job else "Queued",
                "pending_stocks": pending.get(key, 0),
                "job_id": job["job_id"] if job else None,
            }
        )
    return {
        "strategies": rows,
        "jobs": jobs,
        "pending_stocks": sum(pending.values()),
        "queue_fingerprint": hashlib.sha256(
            "|".join(sorted(pending_ids)).encode()
        ).hexdigest(),
        "paper_automation_modified": False,
        "broker_orders_allowed": False,
    }


def export_job(workflow, job_id):
    job = next((row for row in workflow.jobs() if row["job_id"] == job_id), None)
    if not job or job["status"] != "completed" or not job["batch_id"]:
        raise ValueError("Trade evidence is available after the backtest completes")
    batch = workflow.repository.get(job["batch_id"])
    if not batch or not batch.get("report"):
        raise ValueError("The original backtest evidence is unavailable")
    workbook = Workbook(write_only=True)
    summary = workbook.create_sheet("Strategy profitability")
    summary.append(
        ["Strategy", "Horizon", "Source account", "Net P&L", "Trades", "Scope"]
    )
    queue = workbook.create_sheet("Queued stock strategies")
    columns = [
        "symbol",
        "strategy_name",
        "strategy_id",
        "horizon",
        "origin_signal",
        "stock_list",
        "scan_id",
        "created_at",
    ]
    queue.append(columns)
    for row in workflow.queue():
        if row["job_id"] == job_id:
            queue.append(
                [
                    spreadsheet_value(
                        get_strategy(row["strategy_id"])["name"]
                        if key == "strategy_name"
                        else row.get(key)
                    )
                    for key in columns
                ]
            )
    for index, leaf in enumerate(leaf_batches(workflow.repository, batch), 1):
        report = leaf["report"]
        metrics = report.get("metrics") or {}
        scope = (
            "independent portfolio"
            if batch["report"].get("partition_scope")
            else "approved account simulation"
        )
        summary.append(
            [
                get_strategy(leaf["strategy_id"])["name"],
                leaf["horizon"],
                leaf["batch_id"],
                finite(metrics.get("net_profit")),
                metrics.get("total_trades"),
                scope,
            ]
        )
        if not report.get("xlsx_base64"):
            raise ValueError("The original trade workbook is unavailable")
        source = load_workbook(
            io.BytesIO(base64.b64decode(report["xlsx_base64"], validate=True)),
            read_only=True,
            data_only=False,
        )
        for sheet_index, original in enumerate(source, 1):
            name = re.sub(
                r"[\\/*?:\[\]]", "_", f"{index:02}-{sheet_index:02} {original.title}"
            )[:31]
            target = workbook.create_sheet(name)
            for values in original.iter_rows(values_only=True):
                target.append([spreadsheet_value(value) for value in values])
        source.close()
    notes = workbook.create_sheet("Research basis")
    notes.append(
        [
            "Universe",
            "Current scanner-selected stocks; no point-in-time membership audit",
        ]
    )
    notes.append(
        [
            "Profitability",
            "Net of the existing engine's costs; independent portfolios are not summed",
        ]
    )
    notes.append(["Execution", "Historical simulation only; no paper or broker order"])
    stream = io.BytesIO()
    workbook.save(stream)
    return encrypted_excel(stream.getvalue())


def export_pending_queue(workflow):
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Queued stock strategies")
    columns = [
        "symbol",
        "strategy_name",
        "strategy_id",
        "horizon",
        "origin_signal",
        "stock_list",
        "scan_id",
        "created_at",
    ]
    sheet.append(columns)
    for row in workflow.queue():
        if row["job_id"] is None:
            sheet.append(
                [
                    spreadsheet_value(
                        get_strategy(row["strategy_id"])["name"]
                        if key == "strategy_name"
                        else row.get(key)
                    )
                    for key in columns
                ]
            )
    stream = io.BytesIO()
    workbook.save(stream)
    return encrypted_excel(stream.getvalue())
