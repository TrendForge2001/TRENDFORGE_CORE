"use client";

import { useEffect, useState } from "react";
import { Download, Play } from "lucide-react";
import {
  fmt,
  horizonNames,
  human,
  ist,
  text,
  type Evidence,
} from "@/lib/model";
import { downloadCore, useWorkspace } from "./workspace-state";

const queuePath = "reports/backtest-queue";
type Queue = {
  pending_stocks: number;
  strategies: {
    strategy_id: string;
    strategy: string;
    horizon: string;
    pending_stocks: number;
    profitability: string;
  }[];
  jobs: {
    job_id: string;
    strategy_id: string;
    horizon: string;
    created_at: string;
    status: string;
    strategy_provenance?: Evidence;
  }[];
};

export function ScannerQueue() {
  const { catalog, notify, read } = useWorkspace();
  const [open, setOpen] = useState(false);
  const [queue, setQueue] = useState<Queue>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [revision, refresh] = useState(0);
  useEffect(() => {
    const reveal = () => {
      if (window.location.hash === "#scanner-queue") setOpen(true);
    };
    reveal();
    window.addEventListener("hashchange", reveal);
    return () => window.removeEventListener("hashchange", reveal);
  }, []);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function update() {
      try {
        const next = await read<Queue>(queuePath, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setQueue(next);
        setError("");
        timer = setTimeout(update, 6000);
      } catch (failure) {
        if (controller.signal.aborted) return;
        setError((failure as Error).message);
        timer = setTimeout(update, 12000);
      }
    }
    void update();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [open, read, revision]);

  async function runQueue() {
    setBusy("starting");
    try {
      const result = await read<{ status: string }>(`${queuePath}/start`, {
        method: "POST",
        body: "{}",
      });
      notify(
        result.status === "running"
          ? "Scanner backtest queue is already running"
          : "Scanner backtest queue started",
      );
      refresh((old) => old + 1);
    } catch (failure) {
      notify((failure as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function excel(jobId?: string) {
    setBusy(jobId ?? "queued");
    try {
      await downloadCore(
        jobId
          ? `${queuePath}/${encodeURIComponent(jobId)}/trades.xlsx`
          : `${queuePath}/queued-stocks.xlsx`,
        jobId
          ? "trendforge-backtest-trades.xlsx"
          : "trendforge-queued-stock-strategies.xlsx",
      );
    } catch (failure) {
      notify((failure as Error).message);
    } finally {
      setBusy("");
    }
  }
  return (
    <details
      id="scanner-queue"
      className="panel stock-section scanner-queue"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        Scanner backtest queue{" "}
        {queue && (
          <span className="small-tag">
            {fmt(queue.pending_stocks, 0)} pending
          </span>
        )}
      </summary>
      {error && (
        <p className="banner danger" role="alert">
          {error}
        </p>
      )}
      {!queue && !error && (
        <p role="status" className="muted">
          Loading queued symbols…
        </p>
      )}
      {queue && (
        <>
          <div className="stock-actions">
            <button
              className="button primary"
              disabled={!queue.pending_stocks || !!busy}
              onClick={() => void runQueue()}
            >
              <Play size={14} />
              {busy === "starting" ? "Starting…" : "Backtest queued stocks"}
            </button>
            <button
              className="button"
              disabled={!queue.pending_stocks || !!busy}
              onClick={() => void excel()}
            >
              <Download size={14} />
              Export protected queue
            </button>
          </div>
          {queue.strategies.length ? (
            <div className="queue-table">
              <table>
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Horizon</th>
                    <th>Pending</th>
                    <th>Profitability</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.strategies.map((item) => (
                    <tr key={`${item.strategy_id}:${item.horizon}`}>
                      <td>{item.strategy}</td>
                      <td>
                        {horizonNames[item.horizon] ?? human(item.horizon)}
                      </td>
                      <td>{fmt(item.pending_stocks, 0)}</td>
                      <td>{item.profitability}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">
              No scanner candidates are queued for historical backtesting.
            </p>
          )}
          {queue.jobs.length > 0 && (
            <ul className="queue-jobs">
              {queue.jobs.map((job) => (
                <li key={job.job_id}>
                  <div>
                    <strong>
                      {catalog.strategies.find(
                        (s) => s.strategy_id === job.strategy_id,
                      )?.name ?? job.strategy_id}
                    </strong>
                    <small>
                      {ist(job.created_at)} ·{" "}
                      {horizonNames[job.horizon] ?? human(job.horizon)} ·{" "}
                      {human(job.status)}
                      {job.strategy_provenance?.policy_version != null &&
                        ` · ${text(job.strategy_provenance.policy_version)}`}
                    </small>
                  </div>
                  {job.status === "completed" && (
                    <button
                      className="button"
                      disabled={!!busy}
                      onClick={() => void excel(job.job_id)}
                    >
                      <Download size={14} />
                      Protected trades
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </details>
  );
}
