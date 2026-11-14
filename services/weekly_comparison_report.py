"""Structured workbook tables; all variants retain their own trade ledger."""


def comparison_tables(result):
    tables = {}

    def add(name, rows):
        columns = list(dict.fromkeys(k for row in rows for k in row))
        tables[name] = (
            columns or ["No observations"],
            [[r.get(c) for c in columns] for r in rows],
        )

    add("Comparisons", result["comparisons"])
    for name, key in (
        ("Daily account equity", "equity_curve"),
        ("All variant trades", "trades"),
        ("Terminal liquidations", "terminal_liquidations"),
        ("Entry risk audit", "allocations"),
        ("Skipped entries", "rejected_entries"),
    ):
        add(
            name,
            [
                {"variant": run["variant"], **row}
                for run in result["comparison_results"]
                for row in run[key]
            ],
        )
    add("Benchmark", [result["benchmark"]])
    add("Stock coverage", result["history_alignment"]["coverage"])
    return tables
