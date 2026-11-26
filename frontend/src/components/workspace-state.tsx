"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  combineScanReports,
  text,
  universes,
  type Batch,
  type BatchSummary,
  type Candle,
  type Catalog,
  type StockMembership,
  type Universe,
} from "@/lib/model";

export type Launch = {
  kind: "scan" | "backtest";
  strategy_id: string;
  horizon: string;
  strategy_ids?: string[];
  institutional_signal?: string;
  short_borrow_available?: boolean;
  cost_bps?: number;
  slippage_bps?: number;
  initial_capital?: number;
  risk_fraction?: number;
  max_positions?: number;
  move_stop_after_partial?: boolean;
};
export type Read = <T>(path: string, options?: RequestInit) => Promise<T>;
export const running = (batch: BatchSummary) =>
  batch.status === "running" || batch.status === "queued";
const CORE = "/app/workbench/api/core";
const PAGE = 50;

async function fetchCore(path: string, options?: RequestInit) {
  const response = await fetch(`${CORE}/${path}`, {
    ...options,
    cache: "no-store",
    redirect: "manual",
    headers: {
      "X-TrendForge-Workbench": "1",
      "Content-Type": "application/json",
    },
  });
  if (response.type === "opaqueredirect") {
    window.location.assign(
      `/owner/laptop?next=${encodeURIComponent(window.location.pathname)}`,
    );
    throw new Error(
      "Your owner session has expired. Sign in again to continue.",
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const info = Array.isArray(body?.detail)
      ? body.detail
          .map((field: { msg?: string }) => field.msg)
          .filter(Boolean)
          .join(". ")
      : body?.detail;
    throw new Error(text(info, `TrendForge Core returned ${response.status}`));
  }
  return response;
}

const read: Read = async (path, options) =>
  (await fetchCore(path, options)).json();

export async function stockMembers(universe: string, signal?: AbortSignal) {
  return read<StockMembership>(
    `workspace/watchlist/${encodeURIComponent(universe)}/constituents`,
    { signal },
  );
}

function getBatch(id: string, metadata: boolean, signal?: AbortSignal) {
  return read<Batch>(
    `reports/batches/${encodeURIComponent(id)}/workbench${metadata ? "?metadata_only=true" : ""}`,
    { signal },
  );
}

function marketRegime(candles: Candle[]) {
  if (candles.length < 50)
    return { label: "Unavailable", tone: "neutral", sync: "" };
  const ema = candles
    .slice(50)
    .reduce(
      (value, candle) => value + ((candle.close - value) * 2) / 51,
      candles.slice(0, 50).reduce((sum, candle) => sum + candle.close, 0) / 50,
    );
  const last = candles.at(-1)!;
  const distance = last.close / ema - 1;
  if (Math.abs(distance) <= 0.005)
    return { label: "Chop", tone: "amber", sync: last.date };
  return {
    label: distance > 0 ? "Bullish" : "Bearish",
    tone: distance > 0 ? "green" : "red",
    sync: last.date,
  };
}

type WorkspaceState = {
  universe: Universe;
  setUniverse: (value: Universe) => void;
  catalog: Catalog;
  catalogError: string;
  summaries: BatchSummary[];
  busy: boolean;
  historyError: string;
  hasMore: boolean;
  loadMore: () => Promise<void>;
  regime: { label: string; tone: string; sync: string };
  jobs: BatchSummary[];
  launch: (payload: Launch) => Promise<void>;
  toast: string;
  notify: (message: string) => void;
  read: Read;
  download: (
    id: string,
    format: "csv" | "xlsx" | "consolidated",
  ) => Promise<void>;
  batch: (
    id: string,
    metadata?: boolean,
    signal?: AbortSignal,
  ) => Promise<Batch>;
  chart: (
    symbol: string,
    interval: string,
    opts: { start?: string; end?: string; signal?: AbortSignal },
  ) => Promise<Candle[]>;
  benchmark: (
    start?: string,
    end?: string,
    signal?: AbortSignal,
  ) => Promise<Candle[]>;
};
const Context = createContext<WorkspaceState | null>(null);
export function useWorkspace() {
  const value = useContext(Context);
  if (!value) throw new Error("TrendForge workspace context is missing");
  return value;
}

export const saveDownload = (file: Blob, filename: string) => {
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
};

export async function downloadCore(path: string, filename: string) {
  const response = await fetchCore(path);
  saveDownload(await response.blob(), filename);
}

const download: WorkspaceState["download"] = (id, format) => {
  const filename =
    format === "consolidated" ? "consolidated.xlsx" : `report.${format}`;
  return downloadCore(
    `reports/batches/${encodeURIComponent(id)}/${filename}`,
    format === "consolidated" ? `${id}-consolidated.xlsx` : `${id}.${format}`,
  );
};

const batch: WorkspaceState["batch"] = async (id, metadata = false, signal) => {
  const parent = await getBatch(id, metadata, signal);
  if (
    !metadata &&
    parent.kind === "scan" &&
    parent.report?.report_type === "research_partition_manifest"
  ) {
    const ids = parent.report.rows
      .map((row) => text(row.batch_id, ""))
      .filter(Boolean);
    return combineScanReports(
      parent,
      await Promise.all(ids.map((child) => getBatch(child, false, signal))),
    );
  }
  return parent;
};

const chart: WorkspaceState["chart"] = async (
  symbol,
  interval,
  { start, end, signal },
) => {
  const params = new URLSearchParams({
    interval: interval === "15m" ? "15m" : "1d",
  });
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  return (
    await read<{ candles: Candle[] }>(
      `workbench/candles/${encodeURIComponent(symbol)}?${params}`,
      { signal },
    )
  ).candles;
};

const benchmark: WorkspaceState["benchmark"] = async (start, end, signal) => {
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  return (
    await read<{ candles: Candle[] }>(`workbench/benchmark?${params}`, {
      signal,
    })
  ).candles;
};

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [catalog, setCatalog] = useState<Catalog>({
    version: "",
    strategies: [],
  });
  const [catalogError, setCatalogError] = useState("");
  const [universe, updateUniverse] = useState<Universe>("NIFTY 500");
  const setUniverse = (value: Universe) => {
    updateUniverse(value);
    localStorage.setItem("trendforge-universe", value);
  };
  const [summaries, setSummaries] = useState<BatchSummary[]>([]);
  const [extra, setExtra] = useState<BatchSummary[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [regime, setRegime] = useState({
    label: "Syncing",
    tone: "neutral",
    sync: "",
  });
  const [toast, setToast] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const loadedPage = useRef(false);
  const notify = useCallback((message: string) => {
    setToast(message);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(""), 4200);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  useEffect(() => {
    const controller = new AbortController();
    read<Catalog>("workbench/catalog", { signal: controller.signal })
      .then((next) => {
        if (controller.signal.aborted) return;
        setCatalog(next);
        const saved = localStorage.getItem("trendforge-universe");
        if (
          saved &&
          (next.stock_lists?.map((list) => list.name) ?? universes).some(
            (name) => name === saved,
          )
        )
          updateUniverse(saved);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setCatalogError(error.message);
      });
    let timeout: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const data = await read<{ batches: BatchSummary[] }>(
          `reports/batches?limit=${PAGE}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setSummaries(data.batches);
        setHistoryError("");
        if (!loadedPage.current) {
          loadedPage.current = true;
          setHasMore(data.batches.length === PAGE);
        }
        timeout = setTimeout(poll, data.batches.some(running) ? 1800 : 5000);
      } catch (error) {
        if (controller.signal.aborted) return;
        setHistoryError((error as Error).message);
        timeout = setTimeout(poll, 8000);
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timeout);
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const refresh = () =>
      void benchmark(undefined, undefined, controller.signal)
        .then((candles) => {
          if (!controller.signal.aborted) setRegime(marketRegime(candles));
        })
        .catch(() => {
          if (!controller.signal.aborted)
            setRegime({ label: "Unavailable", tone: "neutral", sync: "" });
        });
    refresh();
    const interval = setInterval(refresh, 120_000);
    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, []);

  const launch = async ({
    kind,
    institutional_signal,
    ...parameters
  }: Launch) => {
    const payload = await stockMembers(universe);
    let symbols = [
      ...new Set(payload.rows.map((row) => row.symbol).filter(Boolean)),
    ];
    if (institutional_signal) {
      const selection = await read<{ symbols: string[] }>(
        `institutional/big-shark/selector?${new URLSearchParams({ signal: institutional_signal })}`,
      );
      const matching = new Set(selection.symbols);
      symbols = symbols.filter((symbol) => matching.has(symbol));
    }
    if (!symbols.length)
      throw new Error("No stocks match the selected list and filters.");
    const job = await read<
      Pick<BatchSummary, "batch_id" | "status" | "created_at">
    >(`reports/${kind}`, {
      method: "POST",
      body: JSON.stringify({ ...parameters, stock_list: universe, symbols }),
    });
    setSummaries((old) => [
      {
        ...job,
        kind,
        stock_list: universe,
        strategy_id: parameters.strategy_id,
        horizon: parameters.horizon,
        phase: "queued",
        requested_symbols: symbols.length,
      },
      ...old.filter((item) => item.batch_id !== job.batch_id),
    ]);
    notify(`${kind === "scan" ? "Scan" : "Backtest"} queued`);
  };
  const history = useMemo(
    () =>
      [
        ...new Map(
          [...extra, ...summaries].map((item) => [item.batch_id, item]),
        ).values(),
      ].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [extra, summaries],
  );
  const loadMore = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const data = await read<{ batches: BatchSummary[] }>(
        `reports/batches?limit=${PAGE}&offset=${history.length}`,
      );
      setExtra((old) => [...old, ...data.batches]);
      setHasMore(data.batches.length === PAGE);
      setHistoryError("");
    } catch (error) {
      setHistoryError((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const jobs = summaries.filter((item) => !/-p\d{3}$/.test(item.batch_id));
  return (
    <Context.Provider
      value={{
        universe,
        setUniverse,
        catalog,
        catalogError,
        summaries: history,
        busy,
        historyError,
        hasMore,
        loadMore,
        regime,
        jobs,
        launch,
        toast,
        notify,
        read,
        download,
        batch,
        chart,
        benchmark,
      }}
    >
      {children}
    </Context.Provider>
  );
}
