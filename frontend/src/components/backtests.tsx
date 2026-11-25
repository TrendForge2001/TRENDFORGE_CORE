"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowDownUp,
  ChartNoAxesCombined,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Database,
  ExternalLink,
  Layers3,
  ListTree,
  Percent,
  Wallet,
} from "lucide-react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import {
  exits,
  groupTrades,
  points,
  summary,
  type Trade,
} from "@/lib/analytics";
import {
  fmt,
  human,
  ist,
  money,
  number,
  percent,
  sameUniverse,
  text,
  tone,
  type Batch,
  type Candle,
  type Point,
} from "@/lib/model";
import { useWorkspace } from "./workspace-state";
import { ContextPopover, Overlay } from "./ui/overlay";
import {
  PerformanceChart,
  PriceChart,
  type Level,
  type Marker,
} from "./price-chart";

const helper = createColumnHelper<Trade>();
const emptyPoints: Point[] = [];
const noIndicators: string[] = [];
const columns = [
  helper.accessor("symbol", {
    header: "Symbol",
    cell: ({ row }) => (
      <>
        <strong>{row.original.symbol}</strong>
        <small>{row.original.side}</small>
      </>
    ),
  }),
  helper.accessor("first", {
    header: "Entry (IST)",
    cell: ({ row }) => (
      <>
        <span>{ist(row.original.first, true)}</span>
        <small className="mono">{money(row.original.entry)}</small>
      </>
    ),
  }),
  helper.accessor("exit", {
    header: "Weighted exit",
    cell: ({ row }) => <span className="mono">{money(row.original.exit)}</span>,
  }),
  helper.accessor("net", {
    header: "Net P&L",
    cell: ({ row }) => (
      <strong className={`mono ${tone(row.original.net)}`}>
        {money(row.original.net)}
      </strong>
    ),
  }),
  helper.accessor("riskMultiple", {
    header: "Net R",
    cell: ({ row }) => (
      <span className="mono">
        {row.original.riskMultiple == null
          ? "—"
          : `${fmt(row.original.riskMultiple)}R`}
      </span>
    ),
  }),
  helper.accessor("days", {
    header: "Holding days",
    cell: ({ row }) => (
      <span className="mono">{fmt(row.original.days, 0)}</span>
    ),
  }),
];

function TradeLedger({
  trades,
  multi,
  onReplay,
}: {
  trades: Trade[];
  multi: boolean;
  onReplay: (trade: Trade) => void;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [expanded, setExpanded] = useState(new Set<string>());
  const table = useReactTable({
    data: trades,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 12, pageIndex: 0 } },
  });
  return (
    <section className="panel ledger">
      <div className="results-header">
        <div>
          <h2>Trade ledger</h2>
          <span>
            {fmt(trades.length, 0)} positions ·{" "}
            {fmt(
              trades.reduce((count, t) => count + t.fills.length, 0),
              0,
            )}{" "}
            exit fills
          </span>
        </div>
        <ListTree size={19} />
      </div>
      {!trades.length ? (
        <div className="empty compact">
          <ListTree size={22} />
          <strong>No recorded trades</strong>
        </div>
      ) : (
        <>
          <div className="ledger-scroll">
            <table>
              <thead>
                {table.getHeaderGroups().map((group) => (
                  <tr key={group.id}>
                    <th scope="col" aria-label="Expand fills" />
                    {group.headers.map((header) => (
                      <th scope="col" key={header.id}>
                        <button
                          className="sort-button"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                          <ArrowDownUp size={10} />
                        </button>
                      </th>
                    ))}
                    {multi && <th scope="col">Account</th>}
                    <th scope="col">Replay</th>
                  </tr>
                ))}
              </thead>
              {table.getRowModel().rows.map((row) => {
                const trade = row.original;
                const open = expanded.has(trade.id);
                return (
                  <tbody key={trade.id}>
                    <tr className="trade-main" onClick={() => onReplay(trade)}>
                      <td>
                        <button
                          className="icon-button"
                          aria-expanded={open}
                          aria-label={`${open ? "Hide" : "Show"} ${trade.symbol} exit fills`}
                          onClick={(event) => {
                            event.stopPropagation();
                            setExpanded((old) => {
                              const next = new Set(old);
                              if (next.has(trade.id)) next.delete(trade.id);
                              else next.add(trade.id);
                              return next;
                            });
                          }}
                        >
                          {open ? (
                            <ChevronDown size={15} />
                          ) : (
                            <ChevronRight size={15} />
                          )}
                        </button>
                      </td>
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </td>
                      ))}
                      {multi && (
                        <td className="mono" title={trade.account}>
                          {trade.account.split("-").at(-1)}
                        </td>
                      )}
                      <td>
                        <button
                          className="icon-button"
                          aria-label={`Replay ${trade.symbol} trade`}
                          onClick={(event) => {
                            event.stopPropagation();
                            onReplay(trade);
                          }}
                        >
                          <ExternalLink size={14} />
                        </button>
                      </td>
                    </tr>
                    {open &&
                      trade.fills.map((fill, i) => (
                        <tr className="fill-row" key={i}>
                          <td />
                          <td>
                            <span className="small-tag">LEG {i + 1}</span>
                          </td>
                          <td>{ist(fill.exit_at)} IST</td>
                          <td className="mono">{money(fill.exit_price)}</td>
                          <td className={`mono ${tone(fill.net_pnl)}`}>
                            {money(fill.net_pnl)}
                          </td>
                          <td className="mono">{fmt(fill.quantity, 0)} qty</td>
                          <td
                            colSpan={multi ? 3 : 2}
                            title={text(fill.exit_reason)}
                          >
                            {human(text(fill.exit_reason).toLowerCase())}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                );
              })}
            </table>
          </div>
          <div className="results-footer">
            <span>
              Page {table.getState().pagination.pageIndex + 1} of{" "}
              {table.getPageCount()}
            </span>
            <div className="pager">
              <button
                className="icon-button"
                disabled={!table.getCanPreviousPage()}
                onClick={() => table.previousPage()}
                aria-label="Previous page"
              >
                <ChevronLeft size={17} />
              </button>
              <button
                className="icon-button"
                disabled={!table.getCanNextPage()}
                onClick={() => table.nextPage()}
                aria-label="Next page"
              >
                <ChevronRight size={17} />
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function TradeReplay({
  trade,
  interval,
  onClose,
}: {
  trade: Trade;
  interval: string;
  onClose: () => void;
}) {
  const { chart } = useWorkspace();
  const [candles, setCandles] = useState<Candle[]>([]);
  const [load, setLoad] = useState("Loading recorded market history…");
  const first = text(trade.fills[0].entry_signal_at, trade.first);
  const last = trade.last;
  const bounds = useMemo<[string, string]>(() => [first, last], [first, last]);
  useEffect(() => {
    const controller = new AbortController();
    const end = new Date(`${last.slice(0, 10)}T00:00:00Z`);
    const endValue = Number.isFinite(end.getTime())
      ? new Date(Math.min(end.getTime() + 14 * 86400000, Date.now()))
          .toISOString()
          .slice(0, 10)
      : undefined;
    chart(trade.symbol, interval, {
      start: first.slice(0, 10) || undefined,
      end: endValue,
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) {
          setCandles(result);
          setLoad(result.length ? "" : "No candles for the trade window");
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) setLoad(error.message);
      });
    return () => controller.abort();
  }, [chart, trade, first, last, interval]);
  const levels = useMemo<Level[]>(
    () =>
      [
        { label: "Entry", price: trade.entry, color: "#78a7ff" },
        {
          label: "Initial stop",
          price: number(trade.fills[0].initial_stoploss),
          color: "#f37682",
        },
        ...trade.fills.map((fill, i) => ({
          label: `Exit ${i + 1}`,
          price: number(fill.exit_price),
          color: "#35d2a5",
        })),
      ].flatMap((level) =>
        level.price === undefined ? [] : [{ ...level, price: level.price }],
      ),
    [trade],
  );
  const markers = useMemo<Marker[]>(
    () => [
      { date: first, kind: "signal", label: "Signal" },
      { date: trade.first, kind: "entry", label: "Entry" },
      ...trade.fills.map((fill, i) => ({
        date: text(fill.exit_at, ""),
        kind: "exit" as const,
        label: `Fill ${i + 1}`,
      })),
    ],
    [first, trade],
  );
  return (
    <Overlay
      open
      onClose={onClose}
      title={`${trade.symbol} · Trade replay`}
      description={`${trade.side} · ${ist(trade.first)} to ${ist(trade.last)} IST`}
      wide
    >
      {interval === "1wk" && (
        <div className="banner amber-banner">
          <CircleAlert size={15} />
          Daily candles show the replay window. Weekly signal markers use
          recorded dates.
        </div>
      )}
      <div className="replay-chart">
        {candles.length ? (
          <PriceChart
            candles={candles}
            visible={noIndicators}
            markers={markers}
            levels={levels}
            interval={interval}
            range={bounds}
          />
        ) : (
          <div className="chart-placeholder">{load}</div>
        )}
      </div>
      <div className="replay-stats">
        <div>
          <span>Entry price</span>
          <strong>{money(trade.entry)}</strong>
        </div>
        <div>
          <span>Weighted exit</span>
          <strong>{money(trade.exit)}</strong>
        </div>
        <div>
          <span>Net P&L</span>
          <strong className={tone(trade.net)}>{money(trade.net)}</strong>
        </div>
      </div>
      <ul className="diagnostic-list">
        {trade.fills.map((fill, i) => (
          <li key={i}>
            <strong>
              Fill {i + 1} · {text(fill.exit_reason)}
            </strong>
            <span>
              {ist(fill.exit_at)} IST · {fmt(fill.quantity, 0)} at{" "}
              {money(fill.exit_price)}
            </span>
          </li>
        ))}
      </ul>
    </Overlay>
  );
}

export default function Backtests({ onLaunch }: { onLaunch: () => void }) {
  const {
    universe,
    summaries,
    batch,
    benchmark,
    catalog,
    notify,
    download,
    hasMore,
    loadMore,
    busy,
  } = useWorkspace();
  const choices = summaries.filter(
    (row) =>
      row.kind === "backtest" &&
      row.status === "completed" &&
      sameUniverse(row.stock_list, universe) &&
      !/-p\d{3}$/.test(row.batch_id),
  );
  const [selected, setSelected] = useState("");
  const id = choices.some((item) => item.batch_id === selected)
    ? selected
    : choices[0]?.batch_id;
  const [run, setRun] = useState<Batch | null>(null);
  const [children, setChildren] = useState<Batch[]>([]);
  const [focus, setFocus] = useState("");
  const [failure, setFailure] = useState("");
  const [replay, setReplay] = useState<Trade | null>(null);
  const [showBenchmark, setShowBenchmark] = useState(false);
  const [benchmarkData, setBenchmarkData] = useState<{
    id: string;
    values: Point[];
  }>({ id: "", values: [] });
  const [benchmarkError, setBenchmarkError] = useState("");
  const [exporting, setExporting] = useState(false);
  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    batch(id, false, controller.signal)
      .then(async (candidate) => {
        if (controller.signal.aborted) return;
        setRun(candidate);
        setFocus("");
        setChildren([]);
        setFailure("");
        if (candidate.report?.report_type !== "research_partition_manifest")
          return;
        const ids = candidate.report.rows
          .map((row) => text(row.batch_id, ""))
          .filter(Boolean);
        const accounts: Batch[] = [];
        for (let offset = 0; offset < ids.length; offset += 3) {
          accounts.push(
            ...(await Promise.all(
              ids
                .slice(offset, offset + 3)
                .map((id) => batch(id, false, controller.signal)),
            )),
          );
        }
        if (!controller.signal.aborted)
          setChildren(accounts.filter((item) => item.report));
      })
      .catch((error) => {
        if (!controller.signal.aborted) setFailure(error.message);
      });
    return () => controller.abort();
  }, [id, batch]);
  const current = run?.batch_id === id ? run : null;
  const campaign =
    current?.report?.report_type === "research_partition_manifest";
  const accounts = useMemo(
    () => (campaign ? children : current?.report ? [current] : []),
    [campaign, children, current],
  );
  const account =
    accounts.find((item) => item.batch_id === focus) ?? accounts[0];
  const report = account?.report;
  const fullLedger = useMemo(
    () =>
      accounts.flatMap((item) =>
        groupTrades(item.report?.rows ?? [], item.batch_id),
      ),
    [accounts],
  );
  const trades = useMemo(
    () =>
      campaign && focus
        ? fullLedger.filter((item) => item.account === focus)
        : fullLedger,
    [campaign, focus, fullLedger],
  );
  const metrics = report
    ? summary(
        report,
        fullLedger.filter((item) => item.account === account?.batch_id),
      )
    : null;
  const attribution = report ? exits(report.rows) : [];
  const max = Math.max(1, ...attribution.map((item) => Math.abs(item.net)));
  const curve = useMemo(() => points(report?.equity_curve), [report]);
  const first = curve[0]?.date.slice(0, 10),
    last = curve.at(-1)?.date.slice(0, 10),
    accountId = account?.batch_id;
  useEffect(() => {
    if (!showBenchmark || !first || !last || !accountId) return;
    const controller = new AbortController();
    benchmark(first, last, controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        const mapped = rows
          .filter(
            (c) => c.date.slice(0, 10) >= first && c.date.slice(0, 10) <= last,
          )
          .map((c) => ({ date: c.date, equity: c.close }));
        setBenchmarkData({ id: accountId, values: mapped });
        setBenchmarkError(mapped.length ? "" : "Benchmark history unavailable");
      })
      .catch((error) => {
        if (!controller.signal.aborted) setBenchmarkError(error.message);
      });
    return () => controller.abort();
  }, [showBenchmark, first, last, accountId, benchmark]);
  const strategy =
    catalog.strategies.find((item) => item.strategy_id === current?.strategy_id)
      ?.name ??
    current?.strategy_id ??
    "Backtest";
  const runExport = async (kind: "pdf" | "excel") => {
    if (!current || !accounts.length || exporting) return;
    setExporting(true);
    try {
      if (kind === "excel") await download(current.batch_id, "consolidated");
      else {
        const { exportPdf } = await import("@/lib/exports");
        await exportPdf(current, accounts, fullLedger, strategy);
      }
      notify(
        `${kind === "excel" ? "Excel report" : "PDF tear sheet"} exported`,
      );
    } catch (error) {
      notify((error as Error).message);
    } finally {
      setExporting(false);
    }
  };
  const cards = metrics
    ? [
        {
          label: "Net P&L",
          value: money(metrics.net),
          detail: `Gross ${money(metrics.gross)} · ${percent(metrics.rate)}`,
          icon: Wallet,
          color: tone(metrics.net),
        },
        {
          label: "Win Rate",
          value: percent(metrics.winRate, 1),
          detail: `Payoff ${metrics.payoff === undefined ? "—" : `${fmt(metrics.payoff)}x`}`,
          icon: Percent,
        },
        {
          label: "Net Profit Factor",
          value: metrics.factor === Infinity ? "∞" : fmt(metrics.factor),
          detail: "Net wins / losses",
          icon: ChartNoAxesCombined,
          color:
            metrics.factor === undefined
              ? "muted"
              : metrics.factor > 1.2
                ? "positive"
                : metrics.factor >= 1
                  ? "warning"
                  : "negative",
        },
        {
          label: "Max Drawdown",
          value: percent(metrics.drawdown),
          detail: metrics.period
            ? `${ist(metrics.period[0], true)} – ${ist(metrics.period[1], true)}`
            : "Peak to trough",
          icon: Activity,
          color: "negative",
        },
        {
          label: "Friction Drag",
          value: percent(metrics.frictionPct),
          detail: `${money(metrics.friction)} in fees + slippage`,
          icon: Layers3,
        },
      ]
    : [];
  const excluded = report?.history_alignment?.excluded_symbols ?? [];
  return (
    <>
      <header className="page-heading">
        <div>
          <div className="breadcrumb">
            Workspace <span>/</span> Backtests
          </div>
          <h1>Backtest Lab</h1>
          <p>
            Review performance, exit attribution, and individual trade fills.
          </p>
        </div>
        <button className="button primary" onClick={onLaunch}>
          <Activity size={16} />
          Run Backtest
        </button>
      </header>
      <div className="panel run-selector">
        <label>
          Completed run
          <select
            value={id ?? ""}
            onChange={(event) => {
              setSelected(event.target.value);
              setFailure("");
              setShowBenchmark(false);
              setReplay(null);
            }}
          >
            {!choices.length && <option value="">No completed runs</option>}
            {choices.map((item) => (
              <option value={item.batch_id} key={item.batch_id}>
                {ist(item.created_at, true)} ·{" "}
                {catalog.strategies.find(
                  (s) => s.strategy_id === item.strategy_id,
                )?.name ?? item.strategy_id}{" "}
                · {item.batch_id.slice(-10)}
              </option>
            ))}
          </select>
        </label>
        {hasMore && (
          <button
            className="button"
            onClick={() => void loadMore()}
            disabled={busy}
          >
            Load older runs
          </button>
        )}
        {accounts.length > 0 && (
          <ContextPopover
            label={
              <>
                <ArrowDownToLine size={15} />
                {exporting ? "Exporting…" : "Export"}
                <ChevronDown size={13} />
              </>
            }
          >
            <button
              className="menu-item"
              disabled={exporting}
              onClick={() => void runExport("excel")}
            >
              Consolidated Excel
            </button>
            <button
              className="menu-item"
              disabled={exporting}
              onClick={() => void runExport("pdf")}
            >
              Executive PDF
            </button>
          </ContextPopover>
        )}
      </div>
      {campaign && (
        <div className="panel campaign">
          <div>
            <strong>Campaign accounts</strong>
            <p>
              Each partition used its own starting capital. The unified ledger
              includes every account.
            </p>
          </div>
          <label>
            Account scope
            <select
              value={focus}
              onChange={(event) => {
                setFocus(event.target.value);
                setShowBenchmark(false);
                setReplay(null);
              }}
            >
              <option value="">All accounts · combined ledger</option>
              {accounts.map((item) => (
                <option value={item.batch_id} key={item.batch_id}>
                  {item.batch_id}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {!report || !metrics ? (
        <div className="panel empty">
          <ChartNoAxesCombined size={27} />
          <strong>
            {failure
              ? "Backtest unavailable"
              : id
                ? "Loading backtest evidence…"
                : "No completed backtests"}
          </strong>
          <span>
            {failure ||
              (!id
                ? "Queue a run from this page or the Strategy Registry."
                : "")}
          </span>
        </div>
      ) : (
        <>
          {campaign && !focus && (
            <p className="scope-note">
              Performance and attribution shown for{" "}
              <span className="mono">{account?.batch_id}</span>. Select another
              account to review its results.
            </p>
          )}
          <div className="kpi-grid">
            {cards.map(({ label, value, detail, icon: Icon, color }) => (
              <div className="panel kpi" key={label}>
                <span>
                  <Icon size={15} />
                  {label}
                </span>
                <strong className={`mono ${color ?? ""}`}>{value}</strong>
                <small title={detail}>{detail}</small>
              </div>
            ))}
            <div className="panel kpi">
              <span>
                <Database size={15} />
                Universe Coverage
              </span>
              <strong className="mono">
                {fmt(metrics.included, 0)} <b>/</b>{" "}
                {fmt(account?.requested_symbols, 0)}
              </strong>
              {excluded.length ? (
                <ContextPopover
                  className="inline-button warning"
                  label={
                    <>
                      <CircleAlert size={13} />
                      {excluded.length} excluded
                    </>
                  }
                >
                  <div className="popover-title">Universe exclusions</div>
                  <ul className="diagnostic-list">
                    {excluded.map((item, i) => (
                      <li key={`${item.symbol}-${i}`}>
                        <strong>{item.symbol}</strong>
                        <span>{human(item.reason)}</span>
                      </li>
                    ))}
                  </ul>
                </ContextPopover>
              ) : (
                <small>
                  {metrics.included === undefined
                    ? "Coverage unavailable"
                    : "Included symbols"}
                </small>
              )}
            </div>
          </div>
          <div className="analytics-grid">
            <section className="panel analytics-card">
              <div className="section-line">
                <div>
                  <h2>Equity curve</h2>
                  <span>Returns and drawdown over time</span>
                </div>
                <label className="switch-label">
                  <input
                    type="checkbox"
                    checked={showBenchmark}
                    onChange={(event) => {
                      setShowBenchmark(event.target.checked);
                      setBenchmarkError("");
                    }}
                    disabled={curve.length < 2}
                  />{" "}
                  NIFTY 50
                </label>
              </div>
              {curve.length > 1 ? (
                <PerformanceChart
                  curve={curve}
                  initialCapital={number(report.metrics?.initial_capital)}
                  benchmark={
                    showBenchmark && benchmarkData.id === accountId
                      ? benchmarkData.values
                      : emptyPoints
                  }
                />
              ) : (
                <div className="chart-placeholder">
                  Equity history is unavailable for this report
                </div>
              )}
              {showBenchmark && benchmarkError && (
                <small className="warning">{benchmarkError}</small>
              )}
            </section>
            <section className="panel analytics-card">
              <div className="section-line">
                <div>
                  <h2>Exit attribution</h2>
                  <span>Net P&L and trades by recorded exit reason</span>
                </div>
              </div>
              <div className="exit-bars">
                {attribution.length ? (
                  attribution.map((item) => (
                    <div className="exit-bar" key={item.reason}>
                      <div>
                        <strong title={item.reason}>
                          {human(item.reason.toLowerCase())}
                        </strong>
                        <span className={`mono ${tone(item.net)}`}>
                          {money(item.net)}
                        </span>
                      </div>
                      <div className="bar-track">
                        <i
                          className={item.net < 0 ? "loss" : "gain"}
                          style={{
                            width: `${(Math.abs(item.net) / max) * 100}%`,
                          }}
                        />
                      </div>
                      <small>
                        {item.count} {item.count === 1 ? "trade" : "trades"}
                      </small>
                    </div>
                  ))
                ) : (
                  <div className="chart-placeholder">No exits recorded</div>
                )}
              </div>
            </section>
          </div>
          <TradeLedger
            key={`${id}-${focus}`}
            trades={trades}
            multi={!!campaign && !focus}
            onReplay={setReplay}
          />
          {replay && (
            <TradeReplay
              key={replay.id}
              trade={replay}
              interval={
                accounts.find((item) => item.batch_id === replay.account)
                  ?.report?.trade_interval ??
                (report.mode === "intraday" ? "15m" : "1d")
              }
              onClose={() => setReplay(null)}
            />
          )}
        </>
      )}
    </>
  );
}
