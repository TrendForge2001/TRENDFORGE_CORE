"use client";

import Link from "next/link";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import {
  Activity,
  Check,
  ChevronDown,
  CircleHelp,
  ClipboardList,
  Clock3,
  Crosshair,
  FileChartColumn,
  FlaskConical,
  Layers3,
  ListChecks,
  PanelLeft,
  Play,
  PanelsTopLeft,
  LogOut,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import { z } from "zod";
import {
  disclaimer,
  fmt,
  horizonNames,
  human,
  ist,
  phases,
  preferredStrategy,
  universes,
  type Strategy,
  type View,
} from "@/lib/model";
import { running, useWorkspace, type Launch } from "./workspace-state";
import { Overlay } from "./ui/overlay";
import Scanner from "./scanner";
import StockReports from "./stock-reports";
import Backtests from "./backtests";
import { Health, Runs, Strategies } from "./registry";

const links = [
  { route: "scanner", label: "Scanner Workbench", icon: Crosshair },
  { route: "stocks", label: "Stock Reports", icon: FileChartColumn },
  { route: "backtests", label: "Backtest Lab", icon: FlaskConical },
  { route: "strategies", label: "Strategy Registry", icon: Layers3 },
  { route: "runs", label: "Audit & Exports", icon: ClipboardList },
  { route: "health", label: "Risk & Data Health", icon: ShieldCheck },
] as const;
const guardrails = z.object({
  initial_capital: z.number().min(1000).max(1_000_000_000),
  risk_percent: z.number().gt(0).max(2),
  max_positions: z.number().int().min(1).max(3),
  cost_bps: z.number().min(0).max(1000),
  slippage_bps: z.number().min(0).max(1000),
});
const defaults = {
  initial_capital: 100000,
  risk_percent: 0.5,
  max_positions: 3,
  cost_bps: 12,
  slippage_bps: 5,
};
const labels: Record<keyof typeof defaults, string> = {
  initial_capital: "Initial capital (₹)",
  risk_percent: "Risk per position (%)",
  max_positions: "Max positions",
  cost_bps: "Transaction cost (bps)",
  slippage_bps: "Slippage (bps)",
};
const bounds: Record<keyof typeof defaults, [number, number, number]> = {
  initial_capital: [1000, 1_000_000_000, 1],
  risk_percent: [0.001, 2, 0.001],
  max_positions: [1, 3, 1],
  cost_bps: [0, 1000, 0.01],
  slippage_bps: [0, 1000, 0.01],
};

function Launcher({
  kind,
  selected,
  onClose,
}: {
  kind: Launch["kind"];
  selected?: Strategy;
  onClose: () => void;
}) {
  const { catalog, catalogError, universe, launch } = useWorkspace();
  const options = catalog.strategies.filter((item) =>
    kind === "scan"
      ? item.scanner && item.horizons.length
      : (item.backtest_horizons ?? item.horizons).length,
  );
  const first =
    selected ??
    options.find((item) => item.strategy_id === preferredStrategy) ??
    options[0];
  const [strategyId, setStrategyId] = useState(first?.strategy_id ?? "");
  const [horizon, setHorizon] = useState("");
  const [borrow, setBorrow] = useState(false);
  const [move, setMove] = useState(false);
  const [scanPeers, setScanPeers] = useState(false);
  const [institutionalSignal, setInstitutionalSignal] = useState("");
  const [values, setValues] = useState<Record<keyof typeof defaults, string>>(
    Object.fromEntries(
      Object.entries(defaults).map(([key, value]) => [key, String(value)]),
    ) as Record<keyof typeof defaults, string>,
  );
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  const strategy =
    options.find((item) => item.strategy_id === strategyId) ?? first;
  const horizons =
    (kind === "backtest"
      ? (strategy?.backtest_horizons ?? strategy?.horizons)
      : strategy?.horizons) ?? [];
  const chosen = horizons.includes(horizon)
    ? horizon
    : horizons.includes("long_term")
      ? "long_term"
      : horizons[0];
  const needsBorrow = kind === "backtest" && strategy?.direction === "SHORT";
  const allowMove =
    !!strategy?.policy_overrides &&
    (chosen === "medium_term" || chosen === "long_term");
  const fixedCosts = !!strategy && strategy.strategy_id.includes("weekly");
  const peers = options.filter(
    (entry) =>
      entry.horizons.includes(chosen) && !entry.strategy_id.includes("weekly"),
  );
  const canBatch = kind === "scan" && !fixedCosts && peers.length > 1;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !strategy || !chosen) return;
    const payload: Launch = {
      kind,
      strategy_id: strategy.strategy_id,
      horizon: chosen,
    };
    if (kind === "scan") {
      if (canBatch && scanPeers)
        payload.strategy_ids = peers.map((entry) => entry.strategy_id);
      if (institutionalSignal)
        payload.institutional_signal = institutionalSignal;
    }
    if (kind === "backtest") {
      if (needsBorrow && !borrow) {
        setFailure(
          "Confirm the short borrow assumption to queue this historical run.",
        );
        return;
      }
      const raw = Object.fromEntries(
        Object.keys(defaults).map((name) => {
          const key = name as keyof typeof defaults;
          const value =
            (!strategy.policy_overrides &&
              key !== "cost_bps" &&
              key !== "slippage_bps") ||
            fixedCosts
              ? defaults[key]
              : values[key].trim()
                ? Number(values[key])
                : NaN;
          return [key, value];
        }),
      );
      const result = guardrails.safeParse(raw);
      if (!result.success) {
        const key = result.error.issues[0].path[0] as keyof typeof defaults;
        setFailure(`Enter a valid value for ${labels[key].toLowerCase()}.`);
        return;
      }
      const parsed = result.data;
      if (!fixedCosts)
        Object.assign(payload, {
          cost_bps: parsed.cost_bps,
          slippage_bps: parsed.slippage_bps,
        });
      if (strategy.policy_overrides)
        Object.assign(payload, {
          initial_capital: parsed.initial_capital,
          risk_fraction: parsed.risk_percent / 100,
          max_positions: parsed.max_positions,
        });
      if (allowMove) payload.move_stop_after_partial = move;
      if (needsBorrow) payload.short_borrow_available = true;
    }
    setFailure("");
    setBusy(true);
    try {
      await launch(payload);
      onClose();
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Overlay
      open
      onClose={onClose}
      side={kind === "backtest"}
      title={kind === "scan" ? "Run New Scan" : "Run Backtest"}
      description={universe}
    >
      <form className="launch-form" onSubmit={submit} noValidate>
        <label>
          Strategy
          <select
            required
            value={strategy?.strategy_id ?? ""}
            onChange={(event) => {
              setStrategyId(event.target.value);
              setHorizon("");
              setBorrow(false);
              setMove(false);
              setScanPeers(false);
            }}
          >
            {!options.length && (
              <option value="">No runnable strategies</option>
            )}
            {options.map((item) => (
              <option key={item.strategy_id} value={item.strategy_id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Trading horizon
          <select
            value={chosen ?? ""}
            onChange={(event) => {
              setHorizon(event.target.value);
              setMove(false);
              setScanPeers(false);
            }}
          >
            {horizons.map((key) => (
              <option key={key} value={key}>
                {horizonNames[key] ?? human(key)}
              </option>
            ))}
          </select>
        </label>
        {kind === "scan" && (
          <>
            <label>
              Big Shark stock selector
              <select
                value={institutionalSignal}
                onChange={(event) => setInstitutionalSignal(event.target.value)}
              >
                <option value="">All stocks</option>
                <option value="BUY">Buy</option>
                <option value="SELL">Sell</option>
                <option value="HOLD">Hold</option>
                <option value="NO_DATA">No data</option>
              </select>
            </label>
            {institutionalSignal && (
              <p className="subtle">
                Uses the current institutional snapshot for universe selection.
              </p>
            )}
            {canBatch && (
              <label className="switch-label">
                <input
                  type="checkbox"
                  checked={scanPeers}
                  onChange={(event) => setScanPeers(event.target.checked)}
                />
                Batch strategies in this horizon
              </label>
            )}
            {strategy && (
              <details className="launch-rules">
                <summary>Strategy rules</summary>
                <p>{strategy.description}</p>
                <ul>
                  {[...strategy.entry_rules, ...strategy.exit_rules].map(
                    (rule, index) => (
                      <li key={index}>{rule}</li>
                    ),
                  )}
                </ul>
              </details>
            )}
          </>
        )}
        {kind === "backtest" && (
          <>
            <h3>Account guardrails</h3>
            <div className="form-grid">
              {(Object.keys(defaults) as (keyof typeof defaults)[]).map(
                (key) => {
                  const fixed =
                    key === "cost_bps" || key === "slippage_bps"
                      ? fixedCosts
                      : !strategy?.policy_overrides;
                  return (
                    <label key={key}>
                      {labels[key]}
                      <input
                        disabled={fixed}
                        type="number"
                        min={bounds[key][0]}
                        max={bounds[key][1]}
                        step={bounds[key][2]}
                        value={fixed ? defaults[key] : values[key]}
                        onChange={(event) =>
                          setValues((old) => ({
                            ...old,
                            [key]: event.target.value,
                          }))
                        }
                      />
                    </label>
                  );
                },
              )}
            </div>
            {!strategy?.policy_overrides && (
              <p className="subtle">
                This engine uses its recorded account policy.
              </p>
            )}
            {fixedCosts && (
              <p className="subtle">
                Weekly comparison uses fixed fee and slippage assumptions.
              </p>
            )}
            {allowMove && (
              <label className="switch-label">
                <input
                  type="checkbox"
                  checked={move}
                  onChange={(event) => setMove(event.target.checked)}
                />
                Move stop to entry after partial profit
              </label>
            )}
            {needsBorrow && (
              <label className="switch-label">
                <input
                  type="checkbox"
                  checked={borrow}
                  onChange={(event) => setBorrow(event.target.checked)}
                />
                Assume shares are available to borrow
              </label>
            )}
          </>
        )}
        {(failure || catalogError) && (
          <div className="banner danger" role="alert">
            {failure || catalogError}
          </div>
        )}
        <div className="form-actions">
          <button className="button" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="button primary"
            type="submit"
            disabled={busy || !chosen}
          >
            <Play size={14} />
            {busy
              ? "Queuing…"
              : kind === "scan"
                ? "Queue scan"
                : "Queue backtest"}
          </button>
        </div>
      </form>
    </Overlay>
  );
}

function Jobs({ onClose }: { onClose: () => void }) {
  const { jobs, historyError } = useWorkspace();
  const active = jobs.filter(running);
  const recent = jobs.filter((job) => !running(job)).slice(0, 8);
  return (
    <Overlay
      open
      onClose={onClose}
      title="Jobs"
      description="Research job progress"
      side
    >
      {historyError && <div className="banner danger">{historyError}</div>}
      {!(active.length || recent.length) && (
        <div className="empty compact">
          <ListChecks size={27} />
          <strong>No recent jobs</strong>
          <span>Queued scans and backtests appear here.</span>
        </div>
      )}
      {[
        ["In progress", active],
        ["Recent", recent],
      ].map(([label, items]) => {
        const list = items as typeof active;
        if (!list.length) return null;
        return (
          <section className="job-section" key={label as string}>
            <h3>{label as string}</h3>
            {list.map((job) => {
              const total = job.phase_total ?? job.requested_symbols ?? 0;
              const done =
                job.status === "completed" ? total : (job.phase_completed ?? 0);
              const state = job.phase || job.status;
              return (
                <article className="job" key={job.batch_id}>
                  <div className="section-line">
                    <strong>
                      {job.stock_list} {job.kind}
                    </strong>
                    <span className={`small-tag job-${job.status}`}>
                      {human(job.status)}
                    </span>
                  </div>
                  <div className="job-step">
                    <span>
                      {phases[state] ??
                        (state === "scan"
                          ? "Evaluating symbols"
                          : human(state))}
                    </span>
                    {total > 0 && running(job) && (
                      <span className="mono">
                        {fmt(done, 0)} / {fmt(total, 0)}
                      </span>
                    )}
                  </div>
                  {running(job) && (
                    <progress
                      max={total || 1}
                      value={total ? Math.min(done, total) : undefined}
                      aria-label={`${job.stock_list} ${job.kind} progress`}
                    />
                  )}
                  {job.error_code && (
                    <small className="warning">{human(job.error_code)}
                      {job.child_batch_id && ` · ${job.child_batch_id.split("-").pop()}`}
                      {(job.child_error_code || job.failure_reason) &&
                        ` · ${human(job.child_error_code || job.failure_reason!)}`}
                    </small>
                  )}
                  <small className="mono" title={job.batch_id}>
                    {job.batch_id}
                  </small>
                </article>
              );
            })}
          </section>
        );
      })}
    </Overlay>
  );
}

export default function Workspace({ view }: { view: View }) {
  const { catalog, universe, setUniverse, regime, jobs, toast } =
    useWorkspace();
  const [collapsed, setCollapsed] = useState(false);
  const [jobsOpen, setJobsOpen] = useState(false);
  const [launcher, setLauncher] = useState<{
    kind: Launch["kind"];
    strategy?: Strategy;
  } | null>(null);
  useEffect(() => {
    setCollapsed(localStorage.getItem("trendforge-sidebar") === "collapsed");
  }, []);
  const active = jobs.filter(running).length;
  return (
    <div className={`workspace ${collapsed ? "collapsed" : ""}`}>
      <a href="#main" className="skip-link">
        Skip to workspace
      </a>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <TrendingUp size={19} />
          </div>
          <div className="brand-text">
            <strong>TRENDFORGE</strong>
            <small>Research workspace</small>
          </div>
          <button
            className="icon-button collapse-button"
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() =>
              setCollapsed((value) => {
                localStorage.setItem(
                  "trendforge-sidebar",
                  value ? "expanded" : "collapsed",
                );
                return !value;
              })
            }
          >
            <PanelLeft size={16} />
          </button>
        </div>
        <nav aria-label="Workspace" className="side-navigation">
          <p>WORKSPACE</p>
          {links.map(({ route, label, icon: Icon }) => (
            <Link
              key={route}
              href={`/${route}`}
              title={label}
              aria-current={view === route ? "page" : undefined}
              className={view === route ? "active" : ""}
            >
              <Icon size={17} />
              <span>{label}</span>
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <a
            className="connection-control"
            href="/app/classic/paper_session"
            title="Paper tools"
          >
            <span className="connection-icon">
              <PanelsTopLeft size={16} />
            </span>
            <span className="connection-text">
              <strong>Paper tools</strong>
            </span>
          </a>
          <a
            className="connection-control"
            href="/owner/logout"
            title="Sign out"
          >
            <span className="connection-icon">
              <LogOut size={16} />
            </span>
            <span className="connection-text">
              <strong>Sign out</strong>
            </span>
          </a>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="context-bar">
          <div className="context-left">
            <label className="universe-picker">
              <span>UNIVERSE</span>
              <select
                value={universe}
                onChange={(event) => setUniverse(event.target.value)}
              >
                {(
                  catalog.stock_lists ??
                  universes.map((name) => ({ name, label: name }))
                ).map(({ name, label }) => (
                  <option key={name} value={name}>
                    {label}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} />
            </label>
            <span
              className={`regime-pill regime-${regime.tone}`}
              title="NIFTY 50 compared with its 50-day EMA. Within 0.5% is Chop."
            >
              <i />
              <span>NIFTY 50 vs 50-EMA</span>
              <strong>{regime.label}</strong>
            </span>
          </div>
          <div className="context-right">
            <span className="freshness" title="Last completed NIFTY 50 candle">
              <Clock3 size={14} />
              {regime.sync
                ? `${ist(regime.sync, true)} · 15:30 IST`
                : "Sync unavailable"}
            </span>
            <button
              className="button primary scan-action"
              aria-label="Run New Scan"
              onClick={() => setLauncher({ kind: "scan" })}
            >
              <Play size={14} />
              <span>Run New Scan</span>
            </button>
            <button
              className="button jobs-button"
              aria-label={`Jobs (${active} active)`}
              onClick={() => setJobsOpen(true)}
            >
              <ListChecks size={16} />
              <span>Jobs</span>
              <b className="mono">{active}</b>
            </button>
          </div>
        </header>
        <main id="main" className="main-content">
          {view === "scanner" ? (
            <Scanner />
          ) : view === "stocks" ? (
            <Suspense fallback={<p role="status">Loading stock reports…</p>}>
              <StockReports />
            </Suspense>
          ) : view === "backtests" ? (
            <Backtests onLaunch={() => setLauncher({ kind: "backtest" })} />
          ) : view === "strategies" ? (
            <Strategies
              onLaunch={(strategy) =>
                setLauncher({ kind: "backtest", strategy })
              }
            />
          ) : view === "runs" ? (
            <Runs />
          ) : (
            <Health />
          )}
        </main>
        <footer className="footer">
          <div>
            <CircleHelp size={14} />
            {disclaimer}
          </div>
          <span>
            <i className="live" />
            TrendForge Core
          </span>
        </footer>
      </div>
      {jobsOpen && <Jobs onClose={() => setJobsOpen(false)} />}
      {launcher && (
        <Launcher
          kind={launcher.kind}
          selected={launcher.strategy}
          onClose={() => setLauncher(null)}
        />
      )}
      {toast && (
        <div className="toast" role="status">
          <Check size={17} />
          {toast}
        </div>
      )}
    </div>
  );
}
