"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownUp,
  ArrowRight,
  ChevronDown,
  CircleAlert,
  Crosshair,
  LockKeyhole,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  closeOf,
  fmt,
  guardrail,
  horizonNames,
  ist,
  money,
  number,
  percent,
  sameUniverse,
  sideOf,
  stateOf,
  statuses,
  text,
  type Batch,
  type BatchSummary,
  type Candle,
  type Evidence,
  type ScanStatus,
} from "@/lib/model";
import { useWorkspace } from "./workspace-state";
import { ContextPopover } from "./ui/overlay";
import { indicators, PriceChart, type Level } from "./price-chart";

export const StateBadge = ({ state }: { state: ScanStatus }) => (
  <span className={`state-badge state-${state.toLowerCase()}`}>{state}</span>
);
const setupKey = (row: Evidence) =>
  JSON.stringify([row.symbol, row.strategy_id, row.run_id]);
const helper = createColumnHelper<Evidence>();
const columns = [
  helper.accessor((row) => text(row.symbol), {
    id: "symbol",
    header: "Symbol / Side",
    cell: ({ row }) => (
      <>
        <strong className="symbol">{text(row.original.symbol)}</strong>
        <small>{sideOf(row.original)}</small>
      </>
    ),
  }),
  helper.accessor((row) => number(row.score), {
    id: "score",
    header: "State / Score",
    cell: ({ row }) => (
      <span className="row-state">
        <StateBadge state={stateOf(row.original)} />
        {number(row.original.score) !== undefined && (
          <span className="score" title="Setup score">
            {fmt(row.original.score, 0)}
          </span>
        )}
      </span>
    ),
  }),
  helper.accessor((row) => closeOf(row), {
    id: "entry",
    header: "Close → Entry",
    cell: ({ row }) => (
      <>
        <strong className="mono">{money(closeOf(row.original))}</strong>
        <small className="mono trigger">
          {number(row.original.entry) !== undefined && <ArrowRight size={10} />}{" "}
          {money(row.original.entry)}
        </small>
      </>
    ),
  }),
  helper.accessor((row) => number(row.stoploss), {
    id: "stop",
    header: "Stop-loss",
    cell: ({ row }) => {
      const entry = number(row.original.entry),
        stop = number(row.original.stoploss);
      return (
        <>
          <strong className="mono negative">{money(stop)}</strong>
          <small
            className="mono"
            title={`Risk / share ${money(row.original.risk_per_share)}`}
          >
            {entry && stop ? percent(-Math.abs(stop / entry - 1) * 100) : "—"}
          </small>
        </>
      );
    },
  }),
  helper.display({
    id: "target",
    header: "Target plan",
    cell: ({ row }) => {
      const item = row.original;
      const partial = number(item.partial_target),
        entry = number(item.entry),
        stop = number(item.stoploss);
      const r =
        partial && entry && stop && entry !== stop
          ? Math.abs((partial - entry) / (entry - stop))
          : undefined;
      return (
        <>
          <strong
            className="target-label"
            title={text(
              item.target_plan_note,
              partial && number(item.target2)
                ? `Remainder target ${money(item.target2)}`
                : "",
            )}
          >
            {partial
              ? `Partial${r ? ` ${fmt(r, Math.abs(r - Math.round(r)) < 0.02 ? 0 : 1)}R` : ""}`
              : number(item.target2)
                ? "Target"
                : "—"}
          </strong>
          <small className="mono">{money(partial ?? item.target2)}</small>
        </>
      );
    },
  }),
  helper.display({
    id: "validity",
    header: "Validity",
    cell: ({ row }) => (
      <span className="validity">{text(row.original.entry_validity)}</span>
    ),
  }),
  helper.display({
    id: "exec",
    header: "Exec",
    cell: ({ row }) =>
      row.original.execution_eligible === true ? (
        <span
          className="eligibility ready"
          title="Execution eligible"
          aria-label="Execution eligible"
        >
          <ShieldCheck size={14} />
        </span>
      ) : row.original.execution_eligible === false ? (
        <span
          className="eligibility locked"
          title={guardrail(row.original)}
          aria-label={guardrail(row.original)}
        >
          <LockKeyhole size={13} />
        </span>
      ) : (
        <span className="muted">—</span>
      ),
  }),
];
const states: Record<ScanStatus | "ALL", { label: string; caption: string }> = {
  ALL: { label: "All setups", caption: "Symbols scanned" },
  ARMED: { label: "Armed / Buy", caption: "Ready for a trigger" },
  WAIT: { label: "Wait", caption: "Watching for a setup" },
  EXIT: { label: "Exit", caption: "Position exit signal" },
  ERROR: { label: "Error", caption: "Data needs review" },
};

function ScannerGrid({
  items,
  selected,
  onSelect,
}: {
  items: Evidence[];
  selected: Evidence | null;
  onSelect: (item: Evidence) => void;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const scroll = useRef<HTMLDivElement>(null);
  const table = useReactTable({
    data: items,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const rows = table.getRowModel().rows;
  const virtual = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroll.current,
    estimateSize: () => 50,
    initialRect: { width: 600, height: 504 },
    overscan: 10,
  });
  useEffect(() => {
    if (scroll.current) scroll.current.scrollTop = 0;
  }, [items, sorting]);
  return (
    <div className="table-scroll" ref={scroll}>
      <div
        role="table"
        aria-label="Scanner setups"
        aria-rowcount={rows.length + 1}
        className="scanner-table"
      >
        <div role="rowgroup" className="table-head">
          {table.getHeaderGroups().map((group) => (
            <div role="row" className="scan-grid" key={group.id}>
              {group.headers.map((header) => {
                const order = header.column.getIsSorted();
                return (
                  <div
                    role="columnheader"
                    key={header.id}
                    aria-sort={
                      order
                        ? order === "asc"
                          ? "ascending"
                          : "descending"
                        : undefined
                    }
                  >
                    {header.column.getCanSort() ? (
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
                    ) : (
                      flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        {rows.length ? (
          <div
            role="rowgroup"
            className="virtual-body"
            style={{ height: virtual.getTotalSize() }}
          >
            {virtual.getVirtualItems().map((item) => {
              const row = rows[item.index];
              return (
                <div
                  key={row.id}
                  role="row"
                  aria-rowindex={item.index + 2}
                  className={`scan-grid scan-row ${selected === row.original ? "selected" : ""}`}
                  style={{
                    height: item.size,
                    transform: `translateY(${item.start}px)`,
                  }}
                  onClick={() => onSelect(row.original)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <div key={cell.id} role="cell">
                      {cell.column.id === "symbol" ? (
                        <button
                          className="row-symbol"
                          onClick={(event) => {
                            event.stopPropagation();
                            onSelect(row.original);
                          }}
                          aria-label={`Inspect ${text(row.original.symbol)}`}
                          aria-pressed={selected === row.original}
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </button>
                      ) : (
                        flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext(),
                        )
                      )}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="empty compact">
            <Search size={23} />
            <strong>No matching setups</strong>
            <span>Try a different symbol or state.</span>
          </div>
        )}
      </div>
    </div>
  );
}

const pivotKeys = ["P", "R1", "R2", "S1", "S2"];
const indicatorKeys = [
  ["RSI · Wilder 14", "RSI_WILDER_14"],
  ["MACD", "MACD"],
  ["ATR · Wilder 14", "ATR_WILDER_14"],
  ["Volume SMA · Prior 20", "VOL_SMA_20_PREV"],
];
const periodKey = (date: string, period: string) => {
  if (period === "Month") return date.slice(0, 7);
  if (period === "Day") return date.slice(0, 10);
  const day = new Date(date.slice(0, 10));
  day.setUTCDate(day.getUTCDate() - ((day.getUTCDay() + 6) % 7));
  return day.toISOString().slice(0, 10);
};
function pivotsFor(row: Evidence, series: Candle[], period: string) {
  const recorded = pivotKeys.map((key) =>
    number(row[`indicator_FIB_${period.toUpperCase()}_${key}`]),
  );
  if (recorded.some((value) => value !== undefined)) return recorded;
  if (series.length < 2) return [];
  const asOf = text(row.bar_at, series.at(-1)!.date);
  const eligible = series.filter(
    (candle) =>
      candle.date.slice(0, 10) <= asOf.slice(0, 10) &&
      periodKey(candle.date, period) !== periodKey(asOf, period),
  );
  const last = eligible.at(-1);
  if (!last) return [];
  const previous = eligible.filter(
    (candle) => periodKey(candle.date, period) === periodKey(last.date, period),
  );
  const high = Math.max(...previous.map((c) => c.high)),
    low = Math.min(...previous.map((c) => c.low));
  const pivot = (high + low + last.close) / 3,
    spread = high - low;
  return [
    pivot,
    pivot + 0.382 * spread,
    pivot + 0.618 * spread,
    pivot - 0.382 * spread,
    pivot - 0.618 * spread,
  ];
}

function Inspector({
  item,
  initial,
  onClose,
}: {
  item: Evidence;
  initial: boolean;
  onClose: () => void;
}) {
  const { chart } = useWorkspace();
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [visible, setVisible] = useState(["EMA 100", "EMA 200"]);
  const [pivot, setPivot] = useState("");
  const symbol = text(item.symbol);
  const state = stateOf(item);
  const interval =
    item.interval === "15m" || item.mode === "intraday" ? "15m" : "1d";
  const asOf = text(item.bar_at, "");
  useEffect(() => {
    if (state === "ERROR") return;
    const controller = new AbortController();
    chart(symbol, interval, {
      end: asOf.slice(0, 10) || undefined,
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) {
          const cutoff = Date.parse(asOf);
          const filtered =
            interval === "15m" && Number.isFinite(cutoff)
              ? result.filter((candle) => Date.parse(candle.date) <= cutoff)
              : result;
          setCandles(filtered);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [chart, symbol, asOf, interval, item, state]);
  const entry = number(item.entry),
    stop = number(item.stoploss),
    target = number(item.partial_target ?? item.target2);
  const risk =
    number(item.risk_per_share) ??
    (entry !== undefined && stop !== undefined
      ? Math.abs(entry - stop)
      : undefined);
  const reward =
    entry !== undefined && target !== undefined
      ? Math.abs(target - entry)
      : undefined;
  const validRatio =
    risk &&
    reward &&
    entry !== undefined &&
    stop !== undefined &&
    target !== undefined &&
    (entry - stop) * (target - entry) > 0;
  const ratio = validRatio ? reward / risk : undefined;
  const levels = useMemo<Level[]>(() => {
    const primary = [
      { label: "Entry", price: entry, color: "#76a9ff" },
      { label: "Stop", price: stop, color: "#f37682" },
      {
        label: item.partial_target ? "Partial" : "Target",
        price: target,
        color: "#35d2a5",
      },
    ].flatMap((level) =>
      level.price === undefined ? [] : [{ ...level, price: level.price }],
    );
    const reference = pivot
      ? pivotsFor(item, candles, pivot).flatMap((price, i) =>
          price === undefined
            ? []
            : [
                {
                  label: `${pivot} ${pivotKeys[i]}`,
                  price,
                  color: "#a694df",
                  pivot: true,
                },
              ],
        )
      : [];
    return [...primary, ...reference];
  }, [entry, stop, target, item, candles, pivot]);
  return (
    <aside
      className={`inspector panel ${initial ? "initial-inspector" : ""}`}
      aria-label={`Symbol inspector for ${symbol}`}
    >
      <div className="inspector-top">
        <div className="panel-kicker">
          <Crosshair size={13} /> SYMBOL INSPECTOR
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close symbol inspector"
        >
          <X size={17} />
        </button>
      </div>
      <div className="inspector-identity">
        <div>
          <h2>{symbol}</h2>
          <span>{sideOf(item) === "—" ? "NSE" : `NSE · ${sideOf(item)}`}</span>
        </div>
        <div className="identity-right">
          <StateBadge state={state} />
          {number(item.score) !== undefined && (
            <span className="score" title="Setup score">
              {fmt(item.score, 0)}
            </span>
          )}
        </div>
      </div>
      {state === "ERROR" ? (
        <div className="banner danger">
          <CircleAlert size={17} />
          <div>
            <strong>
              {text(item.error, "The scan could not evaluate this symbol")}
            </strong>
            <span>
              {text(item.error_code)}{" "}
              {item.error_reference ? `· ${item.error_reference}` : ""}
            </span>
          </div>
        </div>
      ) : (
        <>
          {item.execution_eligible === false && (
            <div className="banner amber-banner">
              <LockKeyhole size={14} />
              <span>{guardrail(item)}</span>
            </div>
          )}
          <section className="chart-section">
            <div className="section-line">
              <h3>Price action</h3>
              <span className="small-tag">
                {interval === "15m" ? "15 MIN" : "1 DAY"}
              </span>
            </div>
            <div className="indicator-toggles" aria-label="Chart indicators">
              {indicators.map(({ key, color }) => (
                <button
                  key={key}
                  aria-pressed={visible.includes(key)}
                  onClick={() =>
                    setVisible((old) =>
                      old.includes(key)
                        ? old.filter((v) => v !== key)
                        : [...old, key],
                    )
                  }
                >
                  <i style={{ background: color }} />
                  {key}
                </button>
              ))}
            </div>
            {loading ? (
              <div className="chart-placeholder">
                Loading completed candles…
              </div>
            ) : error || !candles.length ? (
              <div className="chart-placeholder">
                {error || "No completed candles saved for this setup"}
              </div>
            ) : (
              <PriceChart
                candles={candles}
                levels={levels}
                visible={visible}
                interval={interval}
              />
            )}
            <div className="pivot-select">
              <span>Pivots</span>
              {["Day", "Week", "Month"].map((value) => (
                <button
                  key={value}
                  aria-pressed={pivot === value}
                  onClick={() =>
                    setPivot((old) => (old === value ? "" : value))
                  }
                >
                  {value}
                </button>
              ))}
            </div>
          </section>
          <section className="risk-section">
            <div className="section-line">
              <h3>Risk / Reward</h3>
              <span className="ratio-label">
                {ratio
                  ? `${fmt(ratio, Math.abs(ratio - Math.round(ratio)) < 0.02 ? 0 : 2)}R partial`
                  : "—"}
              </span>
            </div>
            {ratio && (
              <div
                className="risk-ruler"
                style={
                  { "--entry": `${100 / (1 + ratio)}%` } as React.CSSProperties
                }
              >
                <div className="risk-bar" />
                <i className="stop-mark" />
                <i className="entry-mark" />
                <i className="target-mark" />
              </div>
            )}
            <div className="risk-levels">
              <div>
                <span>Stop-loss</span>
                <strong className="negative">{money(stop)}</strong>
              </div>
              <div>
                <span>Entry trigger</span>
                <strong>{money(entry)}</strong>
              </div>
              <div>
                <span>{item.partial_target ? "Partial target" : "Target"}</span>
                <strong className="positive">{money(target)}</strong>
              </div>
            </div>
            {(item.pivot_room_note != null ||
              item.target_plan_note != null ||
              risk != null) && (
              <p>
                {risk != null && (
                  <>
                    Risk / share <span className="mono">{money(risk)}</span>
                    .{" "}
                  </>
                )}
                {text(item.pivot_room_note, "")}{" "}
                {text(item.target_plan_note, "")}
              </p>
            )}
          </section>
          <details className="metric-details">
            <summary>
              Indicator evidence <ChevronDown size={15} />
            </summary>
            <dl>
              {indicatorKeys.map(([label, key]) => (
                <div key={key}>
                  <dt>{label}</dt>
                  <dd>
                    {fmt(
                      item[`indicator_${key}`] ??
                        (key === "MACD" ? item.indicator_MACD_LINE : undefined),
                      key.startsWith("VOL") ? 0 : 2,
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </details>
        </>
      )}
    </aside>
  );
}

export default function Scanner() {
  const { universe, summaries, batch, read, catalog } = useWorkspace();
  const candidates = summaries.filter(
    (entry) =>
      entry.kind === "scan" &&
      entry.status === "completed" &&
      sameUniverse(entry.stock_list, universe),
  );
  const latest = candidates.find(
    (entry) => !/-p\d{3}$/.test(entry.batch_id),
  )?.batch_id;
  const [discovered, setDiscovered] = useState<{
    universe: string;
    id?: string;
  } | null>(null);
  const runId =
    latest ?? (discovered?.universe === universe ? discovered.id : undefined);
  const [result, setResult] = useState<Batch | null>(null);
  const [loadError, setLoadError] = useState("");
  const [filter, setFilter] = useState<ScanStatus | "ALL">("ALL");
  const [search, setSearch] = useState("");
  const [choice, setChoice] = useState<null | false | string>(null);
  useEffect(() => {
    if (latest) return;
    const controller = new AbortController();
    const query = new URLSearchParams({
      kind: "scan",
      limit: "1",
      stock_list: universe,
      completed_only: "true",
      primary_only: "true",
    });
    read<{ batches: BatchSummary[] }>(`reports/batches?${query}`, {
      signal: controller.signal,
    })
      .then(({ batches }) => {
        if (!controller.signal.aborted) {
          setDiscovered({ universe, id: batches[0]?.batch_id });
          setLoadError("");
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) setLoadError(error.message);
      });
    return () => controller.abort();
  }, [latest, universe, read]);
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    batch(runId, false, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) {
          setResult(next);
          setLoadError("");
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) setLoadError(error.message);
      });
    return () => controller.abort();
  }, [runId, batch]);
  const current = runId && result?.batch_id === runId ? result : null;
  const rows = useMemo(() => current?.report?.rows ?? [], [current]);
  const totals = useMemo(
    () =>
      rows.reduce<Record<ScanStatus, number>>(
        (counts, row) => {
          counts[stateOf(row)]++;
          return counts;
        },
        { ARMED: 0, WAIT: 0, EXIT: 0, ERROR: 0 },
      ),
    [rows],
  );
  const definedTotal = number(
    current?.report?.scanner_counts?.requested_symbols,
  );
  const items = useMemo(
    () =>
      rows.filter(
        (row) =>
          (filter === "ALL" || stateOf(row) === filter) &&
          text(row.symbol, "")
            .toUpperCase()
            .includes(search.trim().toUpperCase()),
      ),
    [rows, filter, search],
  );
  const active = choice
    ? (rows.find((row) => setupKey(row) === choice) ?? null)
    : null;
  const failed = rows.filter((row) => stateOf(row) === "ERROR");
  const completedCount = rows.length - totals.ERROR;
  const strategy =
    catalog.strategies.find((item) => item.strategy_id === current?.strategy_id)
      ?.name ?? current?.strategy_id;
  const selectState = (state: ScanStatus | "ALL") => {
    setFilter(state);
    if (state !== "ALL" && active && stateOf(active) !== state)
      setChoice(false);
  };
  const diagnostics = (
    <>
      <div className="popover-title">Failed symbols</div>
      {failed.length ? (
        <ul className="diagnostic-list">
          {failed.map((row, index) => (
            <li key={`${text(row.symbol)}-${index}`}>
              <strong>{text(row.symbol)}</strong>
              <span>
                {text(
                  row.error,
                  text(row.error_code, "Diagnostic unavailable in this run"),
                )}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="popover-title subtle">No failures in this scan</div>
      )}
    </>
  );
  return (
    <>
      <header className="page-heading">
        <div>
          <div className="breadcrumb">
            Workspace <span>/</span> Scanner
          </div>
          <h1>Scanner Workbench</h1>
          <p>
            Screen the universe for actionable setups and inspect the levels
            behind each signal.
          </p>
        </div>
        {current?.report && (
          <div className="run-stamp">
            <span>
              <i /> COMPLETED SCAN
            </span>
            <strong className="mono" title={current.report.run_id}>
              {current.report.run_id}
            </strong>
            <small>
              {horizonNames[current.horizon] ?? current.report.mode} ·{" "}
              {current.report.period} history
            </small>
            {strategy && (
              <small className="run-strategy" title={current.strategy_id}>
                {strategy}
              </small>
            )}
          </div>
        )}
      </header>
      <div className="state-strip" aria-label="Filter setups by state">
        {(["ALL", ...statuses] as const).map((state) => {
          const className = `state-card filter-${state.toLowerCase()} ${filter === state ? "active" : ""}`;
          const label = (
            <>
              <span>
                <i />
                {states[state].label}
              </span>
              <strong className="mono">
                {fmt(
                  state === "ALL"
                    ? (definedTotal ?? rows.length)
                    : totals[state],
                  0,
                )}
              </strong>
              <small>{states[state].caption}</small>
            </>
          );
          return state === "ERROR" ? (
            <ContextPopover
              key={state}
              className={className}
              label={label}
              pressed={filter === state}
              onTrigger={() => selectState(state)}
            >
              {diagnostics}
            </ContextPopover>
          ) : (
            <button
              key={state}
              className={className}
              aria-pressed={filter === state}
              onClick={() => selectState(state)}
            >
              {label}
            </button>
          );
        })}
      </div>
      <div className={`scanner-layout ${active ? "has-inspector" : ""}`}>
        <section className="panel scanner-results" aria-label="Setup list">
          <div className="results-header">
            <div>
              <h2>Scan results</h2>
              <span>
                {current
                  ? `${fmt(completedCount, 0)} evaluated · ${universe}`
                  : universe}
              </span>
            </div>
            <label className="symbol-search">
              <Search size={15} />
              <input
                aria-label="Filter by symbol"
                placeholder="Find a symbol…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              {search && (
                <button
                  aria-label="Clear symbol filter"
                  onClick={() => setSearch("")}
                >
                  <X size={14} />
                </button>
              )}
            </label>
          </div>
          {loadError ? (
            <div className="empty">
              <CircleAlert size={24} />
              <strong>Scan results unavailable</strong>
              <span>{loadError}</span>
            </div>
          ) : !current ? (
            <div className="empty">
              <Crosshair size={25} />
              <strong>
                {runId
                  ? "Loading scan results…"
                  : "No completed scan for this universe"}
              </strong>
              <span>
                {runId ? "" : "Run a scan to see the latest research setups."}
              </span>
            </div>
          ) : (
            <ScannerGrid
              items={items}
              selected={active}
              onSelect={(row) => setChoice(setupKey(row))}
            />
          )}
          <div className="results-footer">
            <span>
              <span className="mono">{fmt(items.length, 0)}</span> of{" "}
              <span className="mono">{fmt(rows.length, 0)}</span> results
            </span>
            {failed.length > 0 ? (
              <ContextPopover
                className="inline-button"
                label={
                  <>
                    <CircleAlert size={13} />
                    {failed.length} diagnostics
                  </>
                }
              >
                {diagnostics}
              </ContextPopover>
            ) : (
              <span className="subtle">Select a symbol to inspect</span>
            )}
          </div>
        </section>
        {active && (
          <Inspector
            key={setupKey(active)}
            item={active}
            initial={choice == null}
            onClose={() => setChoice(false)}
          />
        )}
      </div>
    </>
  );
}
