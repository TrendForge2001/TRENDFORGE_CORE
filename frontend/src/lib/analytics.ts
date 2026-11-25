import { number, text, type Evidence, type Point, type Report } from "./model";

export type Trade = {
  id: string;
  account: string;
  symbol: string;
  side: string;
  fills: Evidence[];
  entry?: number;
  exit?: number;
  quantity: number;
  net: number;
  riskMultiple?: number;
  days?: number;
  first: string;
  last: string;
};
export function groupTrades(rows: Evidence[], account: string): Trade[] {
  const groups = new Map<string, Evidence[]>();
  for (const row of rows) {
    const id = `${account}:${row.trade_number ?? `${row.symbol}-${row.side}-${row.entry_at}`}`;
    const list = groups.get(id) ?? [];
    list.push(row);
    groups.set(id, list);
  }
  return Array.from(groups, ([id, items]) => {
    const fills = [...items].sort((a, b) =>
      text(a.exit_at, "").localeCompare(text(b.exit_at, "")),
    );
    const first = text(fills[0].entry_at, ""),
      last = text(fills.at(-1)?.exit_at, "");
    const qty = fills.reduce(
      (value, fill) => value + (number(fill.quantity) ?? 0),
      0,
    );
    const net = fills.reduce(
      (value, fill) => value + (number(fill.net_pnl) ?? 0),
      0,
    );
    const entry = number(fills[0].entry_price),
      stop = number(fills[0].initial_stoploss);
    const initial = number(fills[0].entry_quantity) ?? qty;
    const risk =
      entry !== undefined && stop !== undefined
        ? Math.abs(entry - stop) * initial
        : undefined;
    const weighted =
      qty &&
      fills.every(
        (fill) =>
          number(fill.exit_price) !== undefined &&
          number(fill.quantity) !== undefined,
      )
        ? fills.reduce(
            (value, fill) =>
              value + number(fill.exit_price)! * number(fill.quantity)!,
            0,
          ) / qty
        : undefined;
    const days =
      (Date.parse(last.slice(0, 10)) - Date.parse(first.slice(0, 10))) /
      86400000;
    return {
      id,
      account,
      symbol: text(fills[0].symbol),
      side: text(fills[0].side),
      fills,
      entry,
      exit: weighted,
      quantity: qty,
      net,
      riskMultiple: risk ? net / risk : undefined,
      days: Number.isFinite(days) ? days : undefined,
      first,
      last,
    };
  });
}

export function summary(report: Report, trades: Trade[]) {
  const metrics = report.metrics ?? {};
  const win = trades.filter((trade) => trade.net > 0),
    loss = trades.filter((trade) => trade.net < 0);
  const winners = win.reduce((sum, trade) => sum + trade.net, 0),
    losers = Math.abs(loss.reduce((sum, trade) => sum + trade.net, 0));
  const net =
    number(metrics.net_profit) ??
    (trades.length ? winners - losers : undefined);
  const fees =
    number(metrics.transaction_costs) ??
    (report.rows.length &&
    report.rows.every((row) => number(row.transaction_costs) !== undefined)
      ? report.rows.reduce(
          (sum, row) => sum + number(row.transaction_costs)!,
          0,
        )
      : undefined);
  const slip = number(metrics.slippage_impact_estimate);
  const friction =
    fees !== undefined && slip !== undefined ? fees + slip : undefined;
  const gross =
    net !== undefined && friction !== undefined ? net + friction : undefined;
  const included = report.history_alignment?.included_symbols?.length;
  let peak =
    number(metrics.initial_capital) ?? report.equity_curve?.[0]?.equity ?? 0;
  let drawdown = 0,
    peakAt = report.equity_curve?.[0]?.date,
    period: [string, string] | undefined;
  for (const point of report.equity_curve ?? []) {
    if (point.equity >= peak) {
      peak = point.equity;
      peakAt = point.date;
    }
    const dip = peak > 0 ? ((peak - point.equity) / peak) * 100 : 0;
    if (dip > drawdown && peakAt) {
      drawdown = dip;
      period = [peakAt, point.date];
    }
  }
  return {
    net,
    gross,
    fees,
    slip,
    friction,
    frictionPct:
      gross && friction !== undefined
        ? (friction / Math.abs(gross)) * 100
        : undefined,
    rate: number(metrics.return_pct),
    winRate:
      number(metrics.win_rate) ??
      (trades.length ? (win.length / trades.length) * 100 : undefined),
    payoff:
      winners && losers
        ? winners / win.length / (losers / loss.length)
        : undefined,
    factor:
      number(metrics.profit_factor) ??
      (losers ? winners / losers : winners ? Infinity : undefined),
    drawdown:
      number(metrics.max_drawdown_pct) ??
      (report.equity_curve?.length ? drawdown : undefined),
    period,
    included,
  };
}
export function exits(rows: Evidence[]) {
  const groups = new Map<
    string,
    { reason: string; net: number; count: number; ids: Set<unknown> }
  >();
  for (const row of rows) {
    const reason = text(row.exit_reason, "UNKNOWN");
    const entry = groups.get(reason) ?? {
      reason,
      net: 0,
      count: 0,
      ids: new Set(),
    };
    entry.net += number(row.net_pnl) ?? 0;
    entry.ids.add(
      row.trade_number ?? `${row.symbol}|${row.entry_at}|${row.side}`,
    );
    entry.count = entry.ids.size;
    groups.set(reason, entry);
  }
  return [...groups.values()].sort((a, b) => Math.abs(b.net) - Math.abs(a.net));
}
export function points(input: unknown): Point[] {
  if (!Array.isArray(input)) return [];
  return input
    .flatMap((row) =>
      typeof row?.date === "string" &&
      Number.isFinite(Date.parse(row.date)) &&
      number(row.equity ?? row.benchmark_equity) !== undefined
        ? [
            {
              date: row.date,
              equity: number(row.equity ?? row.benchmark_equity)!,
            },
          ]
        : [],
    )
    .sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
}
