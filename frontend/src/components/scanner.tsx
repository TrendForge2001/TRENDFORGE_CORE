"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownUp,
  ChevronDown,
  CircleAlert,
  Crosshair,
  FileChartColumn,
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
  human,
  ist,
  money,
  number,
  sameUniverse,
  sideOf,
  stateOf,
  statuses,
  stockReportHref,
  text,
  type Batch,
  type BatchSummary,
  type Candle,
  type Evidence,
  type ScanFilter,
  type ScanStatus,
} from "@/lib/model";
import { running, useWorkspace } from "./workspace-state";
import { assessLevels, positivePrice } from "@/lib/trade-levels";
import { ContextPopover, Overlay } from "./ui/overlay";
import {
  indicators,
  PriceChart,
  type ChartZoom,
  type Level,
} from "./price-chart";

export const StateBadge = ({ state }: { state: ScanStatus }) => (
  <span className={`state-badge state-${state.toLowerCase()}`}>
    {state === "ARMED" ? "BUY" : state}
  </span>
);
const rupees = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 6,
});
const levelPrice = (value?: number) =>
  value === undefined ? "—" : rupees.format(value);
const filterOf = (row: Evidence): Exclude<ScanFilter, "ALL"> => {
  const state = stateOf(row);
  return state === "SELL" ? "EXIT" : state;
};

function scanPlan(row: Evidence) {
  const state = stateOf(row);
  const positionExit = state === "EXIT";
  const weekly = row.interval === "1wk";
  const approved = text(row.exit_policy_version, "").startsWith(
    "approved-horizon-strategies-",
  );
  const nextOpen =
    weekly || row.interval === "1d" ? "Next session open" : "Next candle open";
  const order = positionExit ? row.exit_order_type : row.entry_order_type;
  const breakout = order === "NEXT_CANDLE_BREAKOUT";
  const timing = breakout
    ? "Next candle breakout"
    : order === "NEXT_SESSION_OPEN"
      ? "Next session open"
      : order === "NEXT_CANDLE_OPEN" ||
          (!order && (approved || (weekly && !positionExit)))
        ? nextOpen
        : "";
  const entry = positionExit
    ? undefined
    : positivePrice(breakout ? (row.entry_trigger ?? row.entry) : row.entry);
  const stop = positionExit ? undefined : positivePrice(row.stoploss);
  const partial = number(row.partial_target),
    second = number(row.second_target),
    final = number(row.target2);
  const targets = positionExit
    ? []
    : [
        { label: "Partial target", short: "T1", price: partial },
        { label: "Second target", short: "T2", price: second },
        {
          label:
            partial !== undefined || second !== undefined
              ? "Final target"
              : "Target",
          short:
            second !== undefined ? "T3" : partial !== undefined ? "T2" : "",
          price: final,
        },
      ].flatMap(({ price, ...level }) =>
        price === undefined || price <= 0 ? [] : [{ ...level, price }],
      );
  const assessed = assessLevels(entry, stop, targets, sideOf(row), row.risk_per_share);
  const exitClose = positionExit
    ? (number(row.exit_signal_close) ?? closeOf(row))
    : undefined;
  const exitLevel = positionExit
    ? number(row.exit_trigger_level ?? (weekly ? row.target2 : undefined))
    : undefined;
  const exitRule = text(row.exit_trigger_rule, "");
  return {
    positionExit,
    entry,
    stop,
    targets: assessed.targets,
    assessment: assessed,
    timing,
    exitClose,
    exitLevel,
    entryLabel: breakout ? "Entry trigger" : "Entry reference",
    stopLabel:
      row.stop_is_resting_order === false
        ? "Conditional stop"
        : row.stop_is_resting_order === true
          ? "Stop-loss"
          : "Stop reference",
    exitLabel:
      exitLevel === undefined
        ? "Exit trigger"
        : weekly
          ? "Yearly Floor R2"
          : "Exit trigger level",
    exitReason:
      exitRule === "RSI_GAP_CLOSE"
        ? "RSI below 30 and gap down confirmed"
        : exitRule === "BEARISH_SETUP"
          ? "Bearish setup confirmed"
          : exitRule === "SHORT_EXIT_SETUP"
            ? "Cover setup confirmed"
            : exitRule === "YEARLY_FLOOR_R2" || weekly
              ? "Weekly close reached Yearly Floor R2"
              : exitRule
                ? human(exitRule.toLowerCase())
                : "",
    targetCondition: text(
      row.target_condition,
      row.risk_reward === "Indicator exit" ? "Indicator exit" : "",
    ),
  };
}
const setupKey = (row: Evidence) =>
  JSON.stringify([row.symbol, row.strategy_id, row.run_id]);
const errorReason = (row: Evidence) =>
  text(
    row.data_reason,
    text(row.error, "No diagnostics saved for this symbol"),
  );
function weeklyCoverage(row: Evidence) {
  const available = number(row.consecutive_completed_weeks);
  const required = number(row.required_completed_weeks);
  if (available === undefined || required === undefined) return "";
  return `${fmt(available, 0)} of ${fmt(required, 0)} consecutive weeks available`;
}
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
  helper.accessor(
    (row) => {
      const { entry, exitClose } = scanPlan(row);
      return entry ?? exitClose;
    },
    {
      id: "entry",
      header: "Entry / Signal",
      cell: ({ row }) => {
        const plan = scanPlan(row.original);
        return (
          <>
            <strong className="mono">
              {levelPrice(plan.positionExit ? plan.exitClose : plan.entry)}
            </strong>
            <small>
              {plan.positionExit
                ? "Signal close"
                : plan.entry === undefined
                  ? ""
                  : plan.entryLabel}
            </small>
          </>
        );
      },
    },
  ),
  helper.accessor((row) => scanPlan(row).stop, {
    id: "stop",
    header: "Stop level",
    cell: ({ row }) => {
      const { stop, stopLabel } = scanPlan(row.original);
      return (
        <>
          <strong className="mono negative">{levelPrice(stop)}</strong>
          {stop !== undefined && <small>{stopLabel}</small>}
        </>
      );
    },
  }),
  helper.display({
    id: "target",
    header: "Targets / Exit",
    cell: ({ row }) => {
      const plan = scanPlan(row.original);
      if (plan.positionExit)
        return plan.exitLevel === undefined ? (
          <strong>Position exit</strong>
        ) : (
          <>
            <strong className="mono">{levelPrice(plan.exitLevel)}</strong>
            <small>{plan.exitLabel}</small>
          </>
        );
      if (!plan.targets.length)
        return plan.targetCondition ? (
          <span title={plan.targetCondition}>Indicator exit</span>
        ) : (
          "—"
        );
      return (
        <div className="scan-targets">
          {plan.targets.map((target) => (
            <span key={target.label} title={target.label}>
              {target.short && <small>{target.short}</small>}
              <strong className="mono">{levelPrice(target.price)}</strong>
            </span>
          ))}
        </div>
      );
    },
  }),
  helper.display({
    id: "validity",
    header: "Timing",
    cell: ({ row }) => (
      <span className="validity">
        {scanPlan(row.original).timing ||
          (stateOf(row.original) !== "EXIT"
            ? text(row.original.entry_validity)
            : "—")}
      </span>
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
const states: Record<ScanFilter, { label: string; caption: string }> = {
  ALL: { label: "All setups", caption: "Symbols scanned" },
  ARMED: { label: "Buy", caption: "Long entry setup" },
  WAIT: { label: "Wait", caption: "Watching for a setup" },
  EXIT: { label: "Sell / Exit", caption: "Short entries and position exits" },
  HISTORY: { label: "History pending", caption: "100 weeks required" },
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
    estimateSize: () => 58,
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

function Inspector({ item, onClose }: { item: Evidence; onClose: () => void }) {
  const { chart } = useWorkspace();
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [visible, setVisible] = useState(["EMA 100", "EMA 200"]);
  const [pivot, setPivot] = useState("");
  const [fullWindow, setFullWindow] = useState(false);
  const fullButton = useRef<HTMLButtonElement>(null);
  const chartZoom = useRef<ChartZoom>(null);
  const closeFullWindow = () => setFullWindow(false);
  const symbol = text(item.symbol);
  const state = stateOf(item);
  const unavailable = item.signal === "ERROR";
  const interval =
    item.interval === "15m" || item.mode === "intraday" ? "15m" : "1d";
  const asOf = text(item.bar_at, "");
  useEffect(() => {
    if (unavailable) return;
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
  }, [chart, symbol, asOf, interval, item, unavailable]);
  const plan = useMemo(() => scanPlan(item), [item]);
  const { entry, stop } = plan;
  const risk = plan.assessment.risk;
  const ratio = plan.assessment.furthest?.rewardR;
  const levels = useMemo<Level[]>(() => {
    const primary = (
      plan.positionExit
        ? [
            {
              label: "Exit signal close",
              price: plan.exitClose,
              color: "#f37682",
            },
            { label: plan.exitLabel, price: plan.exitLevel, color: "#a694df" },
          ]
        : [
            { label: plan.entryLabel, price: entry, color: "#76a9ff" },
            { label: plan.stopLabel, price: stop, color: "#f37682" },
            ...plan.targets.map(({ label, price }) => ({
              label,
              price,
              color: "#35d2a5",
            })),
          ]
    ).flatMap((level) =>
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
  }, [entry, stop, plan, item, candles, pivot]);
  const chartContent = (
    <section className="chart-section">
      <div className="section-line">
        <h3>Price action</h3>
        <div className="chart-actions">
          <span className="small-tag">
            {interval === "15m" ? "15 MIN" : "1 DAY"}
          </span>
          <div
            className="chart-sizes"
            role="group"
            aria-label="Chart window size"
          >
            <button
              type="button"
              aria-pressed={!fullWindow}
              onClick={fullWindow ? closeFullWindow : undefined}
            >
              Half window
            </button>
            <button
              ref={fullWindow ? undefined : fullButton}
              type="button"
              aria-pressed={fullWindow}
              onClick={() => setFullWindow(true)}
            >
              Full window
            </button>
          </div>
        </div>
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
        <div className="chart-placeholder">Loading completed candles…</div>
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
          sharedZoom={chartZoom}
        />
      )}
      <div className="pivot-select">
        <span>Pivots</span>
        {["Day", "Week", "Month"].map((value) => (
          <button
            key={value}
            aria-pressed={pivot === value}
            onClick={() => setPivot((old) => (old === value ? "" : value))}
          >
            {value}
          </button>
        ))}
      </div>
    </section>
  );
  return (
    <aside
      className="inspector panel"
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
      <Link
        className="button inspector-report"
        href={stockReportHref(symbol, item.horizon, item.strategy_id)}
      >
        <FileChartColumn size={14} /> Open stock report
      </Link>
      {!unavailable && item.data_status === "STALE" && (
        <p className="banner amber-banner">
          <CircleAlert size={14} /> {errorReason(item)}
        </p>
      )}
      {unavailable ? (
        <div
          className={`banner ${state === "HISTORY" ? "amber-banner" : "danger"}`}
        >
          <CircleAlert size={17} />
          <div>
            <strong>{errorReason(item)}</strong>
            <span>
              {weeklyCoverage(item) || text(item.error_code)}{" "}
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
          {plan.positionExit ? (
            <section className="risk-section">
              <h3>
                {sideOf(item) === "SHORT"
                  ? "Cover signal"
                  : "Sell / exit signal"}
              </h3>
              <div className="risk-levels trade-levels">
                <div>
                  <span>Signal close</span>
                  <strong>{levelPrice(plan.exitClose)}</strong>
                </div>
                {plan.exitLevel !== undefined && (
                  <div>
                    <span>{plan.exitLabel}</span>
                    <strong>{levelPrice(plan.exitLevel)}</strong>
                  </div>
                )}
                {plan.timing && (
                  <div>
                    <span>Exit timing</span>
                    <strong>{plan.timing}</strong>
                  </div>
                )}
              </div>
              {plan.exitReason && <p>{plan.exitReason}</p>}
              {item.interval === "1wk" && (
                <p>Use the R2 target recorded when the position opened.</p>
              )}
              {asOf && (
                <p>Signal observed {ist(asOf, item.interval === "1wk")}</p>
              )}
            </section>
          ) : (
            <section className="risk-section">
              <div className="section-line">
                <h3>Entry &amp; exit plan</h3>
                <span className="ratio-label">
                  {plan.targets.filter(t => t.rewardR !== undefined).map(t => `${t.short || "Target"}: ${fmt(t.rewardR)}R`).join(" · ") || "No fixed reward/risk"}
                </span>
              </div>
              {ratio && (
                <div
                  className="risk-ruler"
                  style={
                    {
                      "--entry": `${plan.assessment.entryPercent}%`,
                    } as React.CSSProperties
                  }
                >
                  <div className="risk-bar" />
                  <i className="stop-mark" />
                  <i className="entry-mark" />
                  <i className="target-mark" title="Furthest target" />
                  {plan.targets.filter(t => t.price !== plan.assessment.furthest?.price).map(t => <i key={t.label} className="target-stage" title={`${t.label}: ${fmt(t.rewardR)}R`} style={{ left: `${100 * (risk! + t.reward) / (risk! + plan.assessment.furthest!.reward)}%` }} />)}
                </div>
              )}
              <div className="risk-levels trade-levels">
                <div>
                  <span>{plan.entryLabel}</span>
                  <strong>{levelPrice(entry)}</strong>
                </div>
                <div>
                  <span>{plan.stopLabel}</span>
                  <strong className="negative">{levelPrice(stop)}</strong>
                  {risk !== undefined && <small>Risk {money(risk)} · {fmt(plan.assessment.riskPercent)}%</small>}
                </div>
                {plan.targets.map(({ label, price, reward, rewardPercent, rewardR }) => (
                  <div key={label}>
                    <span>{label}</span>
                    <strong className="positive">{levelPrice(price)}</strong>
                    <small>Reward {money(reward)} · {fmt(rewardPercent)}% · {rewardR !== undefined ? `${fmt(rewardR)}R` : "R unavailable"}</small>
                  </div>
                ))}
              </div>
              {plan.timing && (
                <p>
                  {plan.timing}
                  {plan.timing.endsWith("open")
                    ? " determines the entry fill."
                    : " · valid for the next candle only."}
                </p>
              )}
              {plan.targetCondition && <p>{plan.targetCondition}</p>}
              {plan.assessment.issues.map(issue => <p className="negative" key={issue}>{issue}</p>)}
              {plan.assessment.riskDiffers && <p>Risk is recalculated from the displayed entry and stop; the saved risk field differs.</p>}
              <p>Each R value uses its own target and the displayed entry/stop, before costs. Conditional stops can exit beyond their reference after confirmation; next-session fills can change these proportions.</p>
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
          )}
          {!fullWindow && chartContent}
          <Overlay
            open={fullWindow}
            full
            onClose={closeFullWindow}
            finalFocus={fullButton}
            title={`${symbol} chart`}
          >
            {fullWindow && chartContent}
          </Overlay>
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
      {(item.stock_rating != null || item.rating_reason != null) && (
        <details className="metric-details">
          <summary>
            Institutional rating <ChevronDown size={15} />
          </summary>
          <dl>
            <div>
              <dt>Combined rating</dt>
              <dd>{human(text(item.stock_rating, "Unrated"))}</dd>
            </div>
            <div>
              <dt>Score / 100</dt>
              <dd>{fmt(item.rating_score)}</dd>
            </div>
            <div>
              <dt>Disclosed activity</dt>
              <dd>{human(text(item.institutional_activity, "Unavailable"))}</dd>
            </div>
            <div>
              <dt>Disclosure time</dt>
              <dd>{ist(item.rating_disclosure_time)}</dd>
            </div>
          </dl>
          <p className="muted">
            {text(
              item.rating_reason,
              "Institutional trade evidence is unavailable.",
            )}
          </p>
        </details>
      )}
    </aside>
  );
}

export default function Scanner() {
  const { universe, summaries, batch, read, catalog, notify } = useWorkspace();
  const candidates = summaries.filter(
    (entry) =>
      entry.kind === "scan" &&
      entry.status === "completed" &&
      !entry.scan_retry_of &&
      !/-p\d{3}$/.test(entry.batch_id) &&
      sameUniverse(entry.stock_list, universe),
  );
  const latest = candidates[0]?.batch_id;
  const [archive, setArchive] = useState<{
    universe: string;
    runs: BatchSummary[];
  } | null>(null);
  const [selectedRun, selectRun] = useState<{ universe: string; id: string }>();
  const archived = archive?.universe === universe ? archive.runs : [];
  const history = [
    ...new Map(
      [...candidates, ...archived].map((item) => [item.batch_id, item]),
    ).values(),
  ]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 10);
  const chosenRun =
    selectedRun?.universe === universe &&
    history.some((item) => item.batch_id === selectedRun.id)
      ? selectedRun.id
      : "";
  const runId = chosenRun || latest || archived[0]?.batch_id;
  const lastRecheck = summaries.find(
    (entry) =>
      runId &&
      entry.scan_retry_of === runId &&
      entry.status === "completed" &&
      !/-p\d{3}$/.test(entry.batch_id),
  )?.batch_id;
  const activeRecheck = summaries.some(
    (entry) =>
      Boolean(runId) && entry.scan_retry_of === runId && running(entry),
  );
  const [rechecking, setRechecking] = useState(false);
  const [result, setResult] = useState<Batch | null>(null);
  const [loadError, setLoadError] = useState("");
  const [archiveError, setArchiveError] = useState("");
  const [filter, setFilter] = useState<ScanFilter>("ALL");
  const [strategyFilter, setStrategyFilter] = useState("");
  const [search, setSearch] = useState("");
  const [choice, setChoice] = useState<null | false | string>(null);
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({
      kind: "scan",
      limit: "10",
      stock_list: universe,
      completed_only: "true",
      primary_only: "true",
    });
    read<{ batches: BatchSummary[] }>(`reports/batches?${query}`, {
      signal: controller.signal,
    })
      .then(({ batches }) => {
        if (!controller.signal.aborted) {
          setArchive({ universe, runs: batches });
          setArchiveError("");
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) setArchiveError(error.message);
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
  }, [runId, lastRecheck, batch]);
  const current = runId && result?.batch_id === runId ? result : null;
  const rows = useMemo(() => {
    const saved = current?.report?.rows ?? [];
    if (!current?.scan_recheck) return saved;
    const rechecked = new Map(
      current.scan_recheck.rows.map((row) => [row.symbol, row]),
    );
    return saved.map((row) =>
      row.signal === "ERROR" ? (rechecked.get(row.symbol) ?? row) : row,
    );
  }, [current]);
  const resultStrategies = useMemo(
    () => [
      ...new Set(
        rows.flatMap((row) =>
          typeof row.strategy_id === "string" ? [row.strategy_id] : [],
        ),
      ),
    ],
    [rows],
  );
  const selectedStrategy = resultStrategies.includes(strategyFilter)
    ? strategyFilter
    : "";
  const totals = useMemo(
    () =>
      rows.reduce<Record<Exclude<ScanFilter, "ALL">, number>>(
        (counts, row) => {
          counts[filterOf(row)]++;
          return counts;
        },
        { ARMED: 0, WAIT: 0, EXIT: 0, HISTORY: 0, ERROR: 0 },
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
          (filter === "ALL" || filterOf(row) === filter) &&
          (!selectedStrategy || row.strategy_id === selectedStrategy) &&
          text(row.symbol, "")
            .toUpperCase()
            .includes(search.trim().toUpperCase()),
      ),
    [rows, filter, search, selectedStrategy],
  );
  const active = choice
    ? (rows.find((row) => setupKey(row) === choice) ?? null)
    : null;
  const completedCount = rows.length - totals.ERROR - totals.HISTORY;
  const recovered =
    current?.scan_recheck?.rows.filter((row) => row.signal !== "ERROR")
      .length ?? 0;
  async function recheck() {
    if (!runId || rechecking || activeRecheck) return;
    setRechecking(true);
    try {
      const job = await read<{ requested_symbols: number }>(
        `reports/batches/${encodeURIComponent(runId)}/retry-errors`,
        { method: "POST" },
      );
      notify(`Recheck queued for ${job.requested_symbols} symbols`);
    } catch (error) {
      notify((error as Error).message);
    } finally {
      setRechecking(false);
    }
  }
  const strategy =
    catalog.strategies.find((item) => item.strategy_id === current?.strategy_id)
      ?.name ?? current?.strategy_id;
  const selectState = (state: ScanFilter) => {
    setFilter(state);
    if (state !== "ALL" && active && filterOf(active) !== state)
      setChoice(false);
  };
  const diagnostics = (state: "HISTORY" | "ERROR") => {
    const symbols = rows.filter((row) => stateOf(row) === state);
    return (
      <>
        <div className="popover-title">
          {state === "HISTORY"
            ? "Symbols awaiting weekly history"
            : "Failed symbols"}
        </div>
        {current?.scan_recheck_available && symbols.length > 0 && (
          <div className="recheck-action">
            <button
              className="button"
              type="button"
              disabled={rechecking || activeRecheck}
              onClick={() => void recheck()}
            >
              {rechecking || activeRecheck
                ? "Recheck in progress"
                : "Recheck unresolved symbols"}
            </button>
            <small>Uses the saved scan’s data cutoff.</small>
          </div>
        )}
        {symbols.length ? (
          <ul className="diagnostic-list">
            {symbols.map((row, index) => {
              const coverage = weeklyCoverage(row);
              return (
                <li key={`${text(row.symbol)}-${index}`}>
                  <strong>{text(row.symbol)}</strong>
                  <span>{errorReason(row)}</span>
                  {coverage && <span>{coverage}</span>}
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="popover-title subtle">
            {state === "HISTORY"
              ? "No symbols awaiting weekly history"
              : "No failures in this scan"}
          </div>
        )}
      </>
    );
  };
  const diagnosticState = totals.ERROR ? "ERROR" : "HISTORY";
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
      <div className="panel scan-history">
        <label>
          Scanner run
          <select
            value={chosenRun}
            onChange={(event) => {
              selectRun({ universe, id: event.target.value });
              setChoice(null);
              setFilter("ALL");
              setStrategyFilter("");
              setLoadError("");
            }}
          >
            <option value="">
              {history.length ? "Latest completed scan" : "No completed scans"}
            </option>
            {history.map((run) => (
              <option key={run.batch_id} value={run.batch_id}>
                {ist(run.created_at)} ·{" "}
                {catalog.strategies.find(
                  (item) => item.strategy_id === run.strategy_id,
                )?.name ?? run.strategy_id}{" "}
                · {run.batch_id.slice(-8)}
              </option>
            ))}
          </select>
        </label>
        {resultStrategies.length > 1 && (
          <label>
            Result strategy
            <select
              value={selectedStrategy}
              onChange={(event) => {
                setStrategyFilter(event.target.value);
                setChoice(null);
              }}
            >
              <option value="">All strategies</option>
              {resultStrategies.map((id) => (
                <option key={id} value={id}>
                  {catalog.strategies.find((entry) => entry.strategy_id === id)
                    ?.name ?? id}
                </option>
              ))}
            </select>
          </label>
        )}
        <Link href="/backtests#scanner-queue" className="button">
          Scanner backtest queue
        </Link>
        {archiveError && <small className="warning">{archiveError}</small>}
      </div>
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
          return state === "ERROR" || state === "HISTORY" ? (
            <ContextPopover
              key={state}
              className={className}
              label={label}
              pressed={filter === state}
              onTrigger={() => selectState(state)}
            >
              {diagnostics(state)}
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
              {current?.scan_recheck && <> · {fmt(recovered, 0)} recovered</>}
            </span>
            {totals[diagnosticState] > 0 ? (
              <ContextPopover
                className="inline-button"
                label={
                  <>
                    <CircleAlert size={13} />
                    {totals[diagnosticState]}{" "}
                    {diagnosticState === "ERROR"
                      ? "diagnostics"
                      : "awaiting history"}
                  </>
                }
              >
                {diagnostics(diagnosticState)}
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
            onClose={() => setChoice(false)}
          />
        )}
      </div>
    </>
  );
}
