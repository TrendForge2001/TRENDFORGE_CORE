export const views = [
  "scanner",
  "stocks",
  "backtests",
  "strategies",
  "runs",
  "health",
] as const;
export type View = (typeof views)[number];
export const universes = ["NIFTY 100", "NIFTY 200", "NIFTY 500"] as const;
export type Universe = string;
export const statuses = ["ARMED", "WAIT", "EXIT", "HISTORY", "ERROR"] as const;
export type ScanStatus = (typeof statuses)[number] | "SELL";
export type ScanFilter = (typeof statuses)[number] | "ALL";
export type Evidence = Record<string, unknown>;
export type Candle = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
};
export type Point = { date: string; equity: number };
export type BatchSummary = {
  batch_id: string;
  kind: "scan" | "backtest";
  status: string;
  stock_list: string;
  strategy_id: string;
  horizon: string;
  phase?: string;
  phase_completed?: number;
  phase_total?: number;
  requested_symbols?: number;
  created_at: string;
  finished_at?: string;
  error_code?: string;
  failure_reason?: string;
  child_error_code?: string;
  child_batch_id?: string;
  scan_retry_of?: string | null;
};
export type Report = {
  run_id: string;
  generated_at: string;
  report_type: string;
  strategy_id: string;
  mode: string;
  period: string;
  registry_version: string;
  sha256: string;
  rows: Evidence[];
  parameters?: Evidence;
  metrics?: Evidence;
  scanner_counts?: Evidence;
  history_alignment?: {
    included_symbols?: string[];
    excluded_symbols?: { symbol: string; reason: string }[];
  };
  equity_curve?: Point[];
  benchmark?: unknown;
  trade_interval?: string;
};
export type Batch = BatchSummary & {
  report?: Report;
  request?: Evidence;
  diagnostic?: Evidence;
  scan_recheck_available?: boolean;
  scan_recheck?: { batch_id: string; rows: Evidence[] } | null;
};
export type Strategy = {
  strategy_id: string;
  name: string;
  description: string;
  direction: string;
  modes: string[];
  entry_rules: string[];
  exit_rules: string[];
  lifecycle: "PRODUCTION" | "PAPER" | "RESEARCH";
  horizons: string[];
  backtest_horizons?: string[];
  scanner: boolean;
  policy_overrides?: boolean;
  exit_only?: boolean;
};
export type StockReportHorizon = "short_term" | "long_term";
export type Catalog = {
  version: string;
  strategies: Strategy[];
  stock_lists?: { name: string; label: string }[];
  stock_report_defaults?: Record<StockReportHorizon, string>;
};
export type StockMember = {
  symbol: string;
  stock_name?: string;
  sector?: string;
};
export type StockMembership = {
  rows: StockMember[];
  source?: string;
  source_warning?: string;
};
export const stockReportHref = (
  symbol: string,
  horizon?: unknown,
  strategy?: unknown,
) => {
  const params = new URLSearchParams({ symbol });
  if (horizon === "short_term" || horizon === "long_term") {
    params.set("horizon", horizon);
    if (typeof strategy === "string") params.set("strategy_id", strategy);
  }
  return `/stocks?${params}`;
};
export const disclaimer =
  "Educational & backtesting analytics only — not SEBI-registered investment advice";
export const preferredStrategy = "tf_ema100_200_bullish_pivot";
export const horizonNames: Record<string, string> = {
  intraday: "Intraday",
  short_swing: "Short Swing",
  short_term: "Short Term",
  medium_term: "Medium Term",
  long_term: "Positional",
};
export const phases: Record<string, string> = {
  queued: "Queued",
  starting: "Starting worker",
  history: "Fetching OHLCV",
  indicators: "Preparing indicators",
  alignment: "Aligning calendar",
  simulation: "Running engine",
  report: "Generating report",
  partitions: "Processing accounts",
  completed: "Completed",
  failed: "Failed",
  interrupted: "Interrupted",
  cancelled: "Cancelled",
};
export const text = (value: unknown, fallback = "—") =>
  typeof value === "string" && value.length ? value : fallback;
export const number = (value: unknown): number | undefined => {
  if (typeof value !== "number" && (typeof value !== "string" || !value.trim()))
    return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};
export const fmt = (value: unknown, digits = 2) =>
  number(value)?.toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }) ?? "—";
export const money = (value: unknown) => {
  const n = number(value);
  return n === undefined ? "—" : `${n < 0 ? "−" : ""}₹${fmt(Math.abs(n))}`;
};
export const percent = (value: unknown, digits = 2) =>
  number(value) === undefined ? "—" : `${fmt(value, digits)}%`;
export const tone = (value: unknown) =>
  (number(value) ?? 0) > 0
    ? "positive"
    : (number(value) ?? 0) < 0
      ? "negative"
      : "muted";
export const human = (value: string) =>
  value.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
export const sameUniverse = (a: string, b: string) =>
  a.toLowerCase().replace(/[^a-z0-9]/g, "") ===
  b.toLowerCase().replace(/[^a-z0-9]/g, "");
export const ist = (value: unknown, dateOnly = false) => {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value)))
    return "—";
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    ...(dateOnly ? {} : { hour: "2-digit", minute: "2-digit", hour12: false }),
  }).format(new Date(value));
};
export function stateOf(row: Evidence): ScanStatus {
  if (row.signal === "ERROR") {
    if (
      row.data_code === "WEEKLY_WARMUP_NOT_READY" ||
      (!row.data_code &&
        row.error_code === "WEEKLY_HISTORY_INCOMPLETE" &&
        (row.data_reason ?? row.error) ===
          "This strategy requires 100 completed weekly candles.")
    )
      return "HISTORY";
    return "ERROR";
  }
  if (["STALE", "UNAVAILABLE", "WARMING_UP"].includes(String(row.data_status)))
    return "WAIT";
  if (
    row.signal === "EXIT" ||
    (row.signal === "SELL" && (row.side === "LONG" || row.interval === "1wk"))
  )
    return "EXIT";
  if (row.signal === "SELL" || row.signal === "SHORT") return "SELL";
  if (
    row.entry_state === "ARMED" ||
    ["BUY", "ARMED"].includes(String(row.signal))
  )
    return "ARMED";
  return "WAIT";
}
export const sideOf = (row: Evidence) =>
  row.side === "SELL" || row.side === "SHORT" || row.signal === "SHORT"
    ? "SHORT"
    : row.side === "LONG" ||
        row.side === "BUY" ||
        row.signal === "BUY" ||
        (row.signal === "SELL" && row.interval === "1wk")
      ? "LONG"
      : row.signal === "SELL"
        ? "SHORT"
        : "—";
export const closeOf = (row: Evidence) =>
  number(row.close ?? row.indicator_close ?? row.indicator_CLOSE);
export const guardrail = (row: Evidence) =>
  ({
    research_next_candle_execution_not_paper_enabled:
      "Paper execution disabled for research next-candle setups",
    weekly_research_only_no_orders:
      "Weekly research setup. Execution is disabled.",
  })[String(row.execution_blocked_reason)] ??
  human(
    text(
      row.execution_blocked_reason,
      "Execution eligibility has not been recorded",
    ),
  );
export function combineScanReports(batch: Batch, children: Batch[]): Batch {
  if (!batch.report) return batch;
  const rows = children.flatMap((child) => child.report?.rows ?? []);
  return {
    ...batch,
    report: {
      ...batch.report,
      report_type: "scanner_indicator_snapshot",
      rows,
    },
  };
}
