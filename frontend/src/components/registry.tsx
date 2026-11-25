"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ClipboardCheck,
  Database,
  Fingerprint,
  GitCompare,
  Layers3,
  Shield,
  SlidersHorizontal,
} from "lucide-react";
import { points } from "@/lib/analytics";
import {
  fmt,
  horizonNames,
  human,
  ist,
  number,
  text,
  type Batch,
  type Evidence,
  type Point,
  type Strategy,
} from "@/lib/model";
import { useWorkspace } from "./workspace-state";

function Sparkline({ values }: { values: Point[] }) {
  const samples = values.filter(
    (_, i) => i % Math.max(1, Math.floor(values.length / 36)) === 0,
  );
  const min = Math.min(...samples.map((point) => point.equity));
  const gap = Math.max(
    1,
    Math.max(...samples.map((point) => point.equity)) - min,
  );
  return (
    <svg
      viewBox="0 0 100 27"
      width="100"
      height="27"
      role="img"
      aria-label="Latest backtest equity trend"
    >
      <polyline
        points={samples
          .map(
            (p, i) =>
              `${(i / (samples.length - 1)) * 100},${25 - ((p.equity - min) / gap) * 23}`,
          )
          .join(" ")}
        fill="none"
        stroke={
          values.at(-1)!.equity >= values[0].equity
            ? "var(--green)"
            : "var(--red)"
        }
        strokeWidth="1.6"
      />
    </svg>
  );
}

function StrategyCard({
  strategy,
  onLaunch,
  runId,
}: {
  strategy: Strategy;
  onLaunch: (strategy: Strategy) => void;
  runId?: string;
}) {
  const { batch } = useWorkspace();
  const [trend, setTrend] = useState<{ id: string; values: Point[] }>({
    id: "",
    values: [],
  });
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    batch(runId, false, controller.signal)
      .then((run) => {
        if (!controller.signal.aborted)
          setTrend({ id: runId, values: points(run.report?.equity_curve) });
      })
      .catch(() => {});
    return () => controller.abort();
  }, [batch, runId]);
  const canLaunch =
    (strategy.backtest_horizons ?? strategy.horizons).length > 0;
  return (
    <article className="panel strategy-card">
      <div className="section-line">
        <span
          className={`lifecycle lifecycle-${strategy.lifecycle.toLowerCase()}`}
        >
          {strategy.lifecycle}
        </span>
        <span className="small-tag">{strategy.direction}</span>
      </div>
      <h2>{strategy.name}</h2>
      <div className="strategy-horizons">
        {strategy.horizons
          .map((key) => horizonNames[key] ?? human(key))
          .join(" · ") || strategy.modes.map(human).join(" · ")}
      </div>
      <p>{strategy.description}</p>
      <dl>
        <div>
          <dt>Entry</dt>
          <dd>{strategy.entry_rules[0] ?? "Entry criteria pending review."}</dd>
        </div>
        <div>
          <dt>Exit</dt>
          <dd>{strategy.exit_rules[0] ?? "Exit criteria pending review."}</dd>
        </div>
      </dl>
      <div className="strategy-actions">
        <div>
          {trend.id === runId && trend.values.length > 1 ? (
            <Sparkline values={trend.values} />
          ) : (
            <small>{runId ? "Equity unavailable" : "No saved backtest"}</small>
          )}
        </div>
        <button
          className="button"
          disabled={!canLaunch}
          onClick={() => onLaunch(strategy)}
        >
          <Activity size={14} />
          Run Backtest
        </button>
      </div>
    </article>
  );
}

export function Strategies({
  onLaunch,
}: {
  onLaunch: (strategy: Strategy) => void;
}) {
  const { catalog, catalogError, summaries } = useWorkspace();
  const [filter, setFilter] = useState("Active");
  const items = catalog.strategies.filter((item) =>
    filter === "Active"
      ? item.lifecycle !== "RESEARCH"
      : item.lifecycle === filter,
  );
  const recent = useMemo(() => {
    const ids = new Map<string, string>();
    summaries
      .filter((run) => run.status === "completed" && run.kind === "backtest")
      .forEach((run) => {
        if (!ids.has(run.strategy_id)) ids.set(run.strategy_id, run.batch_id);
      });
    return ids;
  }, [summaries]);
  return (
    <>
      <header className="page-heading">
        <div>
          <div className="breadcrumb">
            Workspace <span>/</span> Strategies
          </div>
          <h1>Strategy Registry</h1>
          <p>Review strategy rules and launch a historical backtest.</p>
        </div>
        <span className="version-tag">
          <Layers3 size={14} />
          {catalog.version}
        </span>
      </header>
      <div
        className="lifecycle-tabs"
        aria-label="Filter strategies by lifecycle"
      >
        {["Active", "PRODUCTION", "PAPER", "RESEARCH"].map((label) => (
          <button
            key={label}
            aria-pressed={filter === label}
            className={filter === label ? "active" : ""}
            onClick={() => setFilter(label)}
          >
            {label === "Active"
              ? "Production + Paper"
              : human(label.toLowerCase())}
            <span>
              {
                catalog.strategies.filter((item) =>
                  label === "Active"
                    ? item.lifecycle !== "RESEARCH"
                    : item.lifecycle === label,
                ).length
              }
            </span>
          </button>
        ))}
      </div>
      {items.length ? (
        <div className="strategy-grid">
          {items.map((strategy) => (
            <StrategyCard
              key={strategy.strategy_id}
              strategy={strategy}
              runId={recent.get(strategy.strategy_id)}
              onLaunch={onLaunch}
            />
          ))}
        </div>
      ) : (
        <div className="panel empty">
          <Layers3 size={24} />
          <strong>
            {catalogError ||
              (!catalog.version
                ? "Loading strategy registry…"
                : `No ${filter.toLowerCase()} strategies`)}
          </strong>
        </div>
      )}
    </>
  );
}

const flatten = (item: Evidence, prefix = ""): [string, unknown][] =>
  Object.entries(item).flatMap(([key, value]) => {
    const name = prefix ? `${prefix}.${key}` : key;
    return value && typeof value === "object" && !Array.isArray(value)
      ? flatten(value as Evidence, name)
      : [[name, value]];
  });
const display = (value: unknown) =>
  value === undefined
    ? "—"
    : typeof value === "string"
      ? value
      : JSON.stringify(value);
export function Runs() {
  const {
    summaries,
    batch,
    hasMore,
    loadMore,
    busy,
    historyError,
    download,
    notify,
  } = useWorkspace();
  const candidates = summaries.filter((item) => item.status === "completed");
  const [choice, setChoice] = useState<[string, string]>(["", ""]);
  const sameKind = candidates.filter((item) => item.kind === "backtest");
  const initial = sameKind.length > 1 ? sameKind : candidates;
  const left = candidates.some((item) => item.batch_id === choice[0])
    ? choice[0]
    : (initial[0]?.batch_id ?? "");
  const right = candidates.some((item) => item.batch_id === choice[1])
    ? choice[1]
    : (initial.find((item) => item.batch_id !== left)?.batch_id ?? "");
  const [details, setDetails] = useState<(Batch | null)[]>([null, null]);
  const [failure, setFailure] = useState("");
  const [changes, setChanges] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all(
      [left, right].map((id) =>
        id ? batch(id, true, controller.signal) : Promise.resolve(null),
      ),
    )
      .then((result) => {
        if (!controller.signal.aborted) {
          setDetails(result);
          setFailure("");
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) setFailure(error.message);
      });
    return () => controller.abort();
  }, [left, right, batch]);
  const leftRun = left === details[0]?.batch_id ? details[0] : null,
    rightRun = right === details[1]?.batch_id ? details[1] : null;
  const pair = [leftRun, rightRun];
  const values = pair.map((run) => {
    const keys = [
      "initial_capital",
      "risk_fraction",
      "max_positions",
      "cost_bps",
      "slippage_bps",
      "move_stop_after_partial",
      "short_borrow_available",
    ];
    const requested = Object.fromEntries(
      keys.flatMap((key) =>
        run?.request?.[key] === undefined ? [] : [[key, run.request[key]]],
      ),
    );
    return Object.fromEntries(
      flatten({
        horizon: run?.horizon,
        strategy_id: run?.strategy_id,
        stock_list: run?.stock_list,
        period: run?.report?.period,
        ...requested,
        ...run?.report?.parameters,
      }),
    );
  });
  const fields = [...new Set(values.flatMap((item) => Object.keys(item)))]
    .sort()
    .filter(
      (key) => !changes || display(values[0][key]) !== display(values[1][key]),
    );
  return (
    <>
      <header className="page-heading">
        <div>
          <div className="breadcrumb">
            Workspace <span>/</span> Runs
          </div>
          <h1>Audit &amp; Exports</h1>
          <p>
            Compare recorded settings and verify the provenance of a completed
            run.
          </p>
        </div>
        {hasMore && (
          <button
            className="button"
            disabled={busy}
            onClick={() => void loadMore()}
          >
            Load older runs
          </button>
        )}
      </header>
      {!candidates.length ? (
        <div className="panel empty">
          <ClipboardCheck size={27} />
          <strong>No completed runs</strong>
          <span>
            {historyError || "Completed scans and backtests appear here."}
          </span>
        </div>
      ) : (
        <>
          <div className="audit-cards">
            {pair.map((run, i) => (
              <section className="panel audit-card" key={i}>
                <div className="section-line">
                  <h2>{i === 0 ? "Baseline run" : "Comparison run"}</h2>
                  <Fingerprint size={17} />
                </div>
                <label className="sr-only" htmlFor={`run-${i}`}>
                  {i === 0 ? "Baseline" : "Comparison"}
                </label>
                <select
                  id={`run-${i}`}
                  value={i === 0 ? left : right}
                  onChange={(event) =>
                    setChoice(
                      i === 0
                        ? [event.target.value, right]
                        : [left, event.target.value],
                    )
                  }
                >
                  <option value="">Select a completed run</option>
                  {candidates.map((item) => (
                    <option key={item.batch_id} value={item.batch_id}>
                      {ist(item.created_at, true)} · {human(item.kind)} ·{" "}
                      {item.batch_id}
                    </option>
                  ))}
                </select>
                {run && (
                  <>
                    <dl>
                      <div>
                        <dt>Run ID</dt>
                        <dd>{run.report?.run_id ?? run.batch_id}</dd>
                      </div>
                      <div>
                        <dt>Registry version</dt>
                        <dd>{text(run.report?.registry_version)}</dd>
                      </div>
                      <div>
                        <dt>SHA-256</dt>
                        <dd>{text(run.report?.sha256, "Unavailable")}</dd>
                      </div>
                    </dl>
                    <div className="row-actions">
                      {(["csv", "xlsx"] as const).map((format) => (
                        <button
                          key={format}
                          className="button"
                          onClick={() =>
                            void download(run.batch_id, format).catch((error) =>
                              notify(error.message),
                            )
                          }
                        >
                          Download {format === "csv" ? "CSV" : "Excel"}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </section>
            ))}
          </div>
          {failure ? (
            <div className="banner danger">{failure}</div>
          ) : (
            <section className="panel diff">
              <div className="results-header">
                <div>
                  <h2>
                    <GitCompare size={16} /> Parameter diff
                  </h2>
                  <span>Recorded run settings</span>
                </div>
                <label className="switch-label">
                  <input
                    type="checkbox"
                    checked={changes}
                    onChange={(event) => setChanges(event.target.checked)}
                  />{" "}
                  Changed only
                </label>
              </div>
              {leftRun && rightRun ? (
                <div className="ledger-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Parameter</th>
                        <th>Baseline</th>
                        <th>Comparison</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fields.map((key) => (
                        <tr
                          key={key}
                          className={
                            display(values[0][key]) !== display(values[1][key])
                              ? "changed"
                              : ""
                          }
                        >
                          <td className="mono">{key}</td>
                          <td className="mono">{display(values[0][key])}</td>
                          <td className="mono">{display(values[1][key])}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!fields.length && (
                    <div className="empty compact">
                      <strong>No changed parameters</strong>
                    </div>
                  )}
                </div>
              ) : (
                <div className="empty compact">
                  <strong>Choose two runs to compare</strong>
                </div>
              )}
            </section>
          )}
        </>
      )}
    </>
  );
}

export function Health() {
  const { read, regime, summaries } = useWorkspace();
  const [data, setData] = useState<Evidence | null>(null);
  const [error, setError] = useState("");
  const recent = summaries.find(
    (item) => item.kind === "backtest" && item.status === "completed",
  );
  const { batch } = useWorkspace();
  const [run, setRun] = useState<Batch | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    read<Evidence>("production/health", { signal: controller.signal })
      .catch(() => read<Evidence>("health", { signal: controller.signal }))
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [read]);
  useEffect(() => {
    if (!recent) return;
    const controller = new AbortController();
    batch(recent.batch_id, false, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setRun(result);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [recent?.batch_id, batch]);
  const costs = run?.report?.parameters ?? {};
  const exclusions = run?.report?.history_alignment?.excluded_symbols ?? [];
  return (
    <>
      <header className="page-heading">
        <div>
          <div className="breadcrumb">
            Workspace <span>/</span> Health
          </div>
          <h1>Risk &amp; Data Health</h1>
          <p>
            Inspect feed freshness, recorded guardrails, and candle coverage.
          </p>
        </div>
      </header>
      <div className="health-grid">
        <section className="panel health-card">
          <h2>
            <Database size={17} /> Market data
          </h2>
          <dl>
            <div>
              <dt>Core status</dt>
              <dd>{text(data?.status, error ? "Unavailable" : "Checking…")}</dd>
            </div>
            <div>
              <dt>Last completed NIFTY 50 candle</dt>
              <dd>
                {regime.sync
                  ? `${ist(regime.sync, true)} · ${data?.status ? "IST" : "Daily"}`
                  : "Unavailable"}
              </dd>
            </div>
            <div>
              <dt>NIFTY 50 vs 50-EMA</dt>
              <dd className={`regime-${regime.tone}`}>{regime.label}</dd>
            </div>
          </dl>
          {error && <div className="banner danger">{error}</div>}
        </section>
        <section className="panel health-card">
          <h2>
            <Shield size={17} /> Research guardrails
          </h2>
          <p>
            {run
              ? `Last recorded backtest · ${run.batch_id}`
              : "Guardrails appear when a completed run is available."}
          </p>
          <dl>
            <div>
              <dt>Cost</dt>
              <dd>
                {number(costs.cost_bps) === undefined
                  ? "—"
                  : `${fmt(costs.cost_bps, 0)} bps`}
              </dd>
            </div>
            <div>
              <dt>Slippage</dt>
              <dd>
                {number(costs.slippage_bps) === undefined
                  ? "—"
                  : `${fmt(costs.slippage_bps, 0)} bps`}
              </dd>
            </div>
            <div>
              <dt>Maximum concurrent positions</dt>
              <dd>{fmt(costs.max_positions, 0)}</dd>
            </div>
          </dl>
        </section>
      </div>
      <section className="panel diff">
        <div className="results-header">
          <div>
            <h2>
              <SlidersHorizontal size={16} /> Candle calendar diagnostics
            </h2>
            <span>Latest recorded universe exclusions</span>
          </div>
        </div>
        {exclusions.length ? (
          <ul className="diagnostic-list health-exclusions">
            {exclusions.map((item, i) => (
              <li key={`${item.symbol}-${i}`}>
                <strong>{item.symbol}</strong>
                <span>{human(item.reason)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="empty compact">
            <strong>
              {run?.report?.history_alignment?.excluded_symbols
                ? "No exclusions recorded"
                : "Calendar diagnostics unavailable"}
            </strong>
          </div>
        )}
      </section>
    </>
  );
}
