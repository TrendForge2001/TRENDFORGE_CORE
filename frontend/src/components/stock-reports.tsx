"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  ChartNoAxesCombined,
  CircleAlert,
  Download,
  ExternalLink,
  Search,
} from "lucide-react";
import {
  fmt,
  human,
  ist,
  money,
  number,
  percent,
  stockReportHref,
  text,
  type Candle,
  type Evidence,
  type StockMembership,
  type StockReportHorizon,
} from "@/lib/model";
import {
  downloadCore,
  saveDownload,
  stockMembers,
  useWorkspace,
  type Read,
} from "./workspace-state";
import {
  PriceChart,
  ReportHistoryChart,
  type ChartZoom,
  type Level,
} from "./price-chart";
import { Overlay } from "./ui/overlay";

type ReportScope = {
  symbol: string;
  horizon: StockReportHorizon;
  strategy: string;
};
type Financial = {
  period: string;
  period_end: string;
  revenue_cr?: number | null;
  net_profit_cr?: number | null;
};
type Ownership = {
  period: string;
  period_end: string;
  complete: boolean;
  categories: { category: string; percent: number | null }[];
};
type StockReport = {
  schema_version: string;
  symbol: string;
  company_name: string;
  generated_at: string;
  horizon: StockReportHorizon;
  strategy: {
    strategy_id: string;
    name: string;
    entry_rules: string[];
    exit_rules: string[];
    stoploss_rules?: string[];
    target_rules?: string[];
  };
  price: {
    value: number | null;
    basis: string;
    bar_date: string | null;
    source: string;
  };
  market_quote?: { last_price: number | null; timestamp: string | null };
  technical: Evidence;
  market_error?: Evidence | null;
  rating?: Evidence;
  technical_assessment?: Evidence;
  display_plan: Evidence & { targets?: (number | null)[] };
  trade_plan: Evidence & {
    pivot_levels?: Record<string, number>;
    indicator_references?: Record<string, number>;
    conditions?: { condition: string; passed: boolean }[];
  };
  paper_review_available: boolean;
  candles: Candle[];
  company: {
    status: string;
    source?: string;
    source_url?: string;
    fetched_at?: string;
    facts_as_of?: string;
    reporting_basis?: string;
    metrics?: Evidence;
    shareholding?: Ownership[];
    annual?: Financial[];
    quarterly?: Financial[];
  };
  news: {
    title: string;
    url: string;
    source: string;
    published_at?: string;
    publication_date?: string;
  }[];
  overview: string[];
  risk_notes: string[];
  strategy_provenance?: Evidence;
  evaluation_diagnostics?: Evidence[];
};
const validSymbol = (symbol: string) =>
  /^[A-Z0-9][A-Z0-9&._-]{0,29}$/.test(symbol) && !symbol.includes("..");
const shortTerm = "short_term";
const longTerm = "long_term";
const windowChoices = {
  "3 months": 63,
  "6 months": 126,
  "1 year": 252,
} as const;
const linkToSource = (url?: string) => {
  try {
    const verified = new URL(url ?? "");
    return ["https:", "http:"].includes(verified.protocol)
      ? verified.href
      : undefined;
  } catch {
    return undefined;
  }
};
function reportQuery(scope: ReportScope) {
  const params = new URLSearchParams({ horizon: scope.horizon });
  if (scope.strategy) params.set("strategy_id", scope.strategy);
  return params;
}
async function fetchStockReport(
  read: Read,
  scope: ReportScope,
  signal: AbortSignal,
  refresh = false,
) {
  const params = reportQuery(scope);
  if (refresh) params.set("refresh", "true");
  const result = await read<StockReport>(
    `reports/stocks/${encodeURIComponent(scope.symbol)}?${params}`,
    { signal },
  );
  if (
    result.schema_version !== "stock-report-v1" ||
    result.symbol !== scope.symbol
  )
    throw new Error("TrendForge Core returned an incomplete stock report.");
  return result;
}
const homeScope = { symbol: "", horizon: shortTerm, strategy: "" } as const;
const Money = ({ value }: { value: unknown }) => (
  <>{number(value) === undefined ? "Unavailable" : money(value)}</>
);

function ReportPrices({ report }: { report: StockReport }) {
  const [windowName, setWindow] =
    useState<keyof typeof windowChoices>("6 months");
  const [full, setFull] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const zoom = useRef<ChartZoom>(null);
  const levels = useMemo(() => {
    const selected = report.display_plan ?? report.trade_plan;
    const list: Level[] = [];
    const add = (
      label: string,
      value: unknown,
      color: string,
      pivot = false,
    ) => {
      const price = number(value);
      if (price !== undefined) list.push({ label, price, color, pivot });
    };
    add("Entry", selected.entry, "#78a7ff");
    add("Stop reference", selected.stop_reference, "#f37682");
    selected.targets?.forEach((target, i) =>
      add(`Target ${i + 1}`, target, "#35d2a5"),
    );
    Object.entries(report.trade_plan.pivot_levels ?? {}).forEach(
      ([name, value]) => add(name, value, "#b29afd", true),
    );
    return list;
  }, [report]);
  const candles = useMemo(
    () => report.candles.slice(-windowChoices[windowName]),
    [report, windowName],
  );
  const chart = (
    <div className="chart-section report-price-section">
      <div className="section-line">
        <div className="chart-sizes" role="group" aria-label="Chart history">
          {Object.keys(windowChoices).map((key) => (
            <button
              type="button"
              key={key}
              aria-pressed={windowName === key}
              onClick={() => setWindow(key as keyof typeof windowChoices)}
            >
              {key}
            </button>
          ))}
        </div>
        <button
          ref={full ? undefined : toggle}
          className="button"
          onClick={() => setFull(!full)}
        >
          {full ? "Return to report" : "Full window"}
        </button>
      </div>
      <ReportPriceWindow candles={candles} levels={levels} zoom={zoom} />
    </div>
  );
  return (
    <section
      className="panel stock-section"
      aria-label="Price and pivot references"
    >
      <h2>Price &amp; pivot references</h2>
      {!candles.length ? (
        <p className="muted">
          No completed prices are available for this report.
        </p>
      ) : (
        <>
          {!full && chart}
          <Overlay
            open={full}
            full
            title={`${report.symbol} chart`}
            finalFocus={toggle}
            onClose={() => setFull(false)}
          >
            {full && chart}
          </Overlay>
        </>
      )}
    </section>
  );
}

const noAverages: string[] = [];
function ReportPriceWindow({
  candles,
  levels,
  zoom,
}: {
  candles: Candle[];
  levels: Level[];
  zoom: { current: ChartZoom };
}) {
  const range = useMemo<[string, string]>(
    () => [candles[0].date, candles[candles.length - 1].date],
    [candles],
  );
  return (
    <PriceChart
      candles={candles}
      levels={levels}
      visible={noAverages}
      sharedZoom={zoom}
      range={range}
    />
  );
}

function SourceNote({ company }: { company: StockReport["company"] }) {
  const href = linkToSource(company.source_url);
  return (
    <p className="stock-source">
      Source{" "}
      {href ? (
        <a href={href} target="_blank" rel="noreferrer">
          {text(company.source, "Company data")}
        </a>
      ) : (
        text(company.source, "Unavailable")
      )}
      {company.reporting_basis && ` · ${company.reporting_basis}`}
      {company.facts_as_of && ` · As of ${company.facts_as_of}`}
      {company.fetched_at && ` · Fetched ${ist(company.fetched_at, true)}`}
    </p>
  );
}

function CompanyEvidence({ company }: { company: StockReport["company"] }) {
  const [periodIndex, setPeriod] = useState("");
  const [frequency, setFrequency] = useState<"annual" | "quarterly">("annual");
  const [metric, setMetric] = useState<"revenue_cr" | "net_profit_cr">(
    "revenue_cr",
  );
  const periods = company.shareholding ?? [];
  const period =
    periods.find((item) => item.period_end === periodIndex) ?? periods.at(-1);
  const metrics = company.metrics ?? {};
  const financials = useMemo(
    () =>
      (company[frequency] ?? []).flatMap((item) => {
        const value = number(item[metric]);
        return value === undefined ? [] : [{ date: item.period_end, value }];
      }),
    [company, frequency, metric],
  );
  return (
    <>
      <section className="panel stock-section">
        <h2>Fundamentals</h2>
        <dl className="stock-metrics">
          <div>
            <dt>P/E ratio</dt>
            <dd>{fmt(metrics.pe)}</dd>
          </div>
          <div>
            <dt>Sector P/E</dt>
            <dd>{fmt(metrics.sector_pe)}</dd>
          </div>
          <div>
            <dt>Dividend yield</dt>
            <dd>{percent(metrics.dividend_yield_pct)}</dd>
          </div>
          <div>
            <dt>Market cap (₹ Cr)</dt>
            <dd>{fmt(metrics.market_cap_cr)}</dd>
          </div>
        </dl>
        {company.status !== "available" && (
          <p className="muted">Company fundamentals are unavailable.</p>
        )}
        <SourceNote company={company} />
      </section>
      <section className="panel stock-section">
        <div className="section-line stock-section-heading">
          <h2>Shareholding</h2>
          {period && (
            <label>
              Quarter{" "}
              <select
                aria-label="Quarter"
                value={period.period_end}
                onChange={(event) => setPeriod(event.target.value)}
              >
                {periods.map((item) => (
                  <option key={item.period_end} value={item.period_end}>
                    {item.period}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {period?.complete ? (
          <dl className="ownership-bars">
            {period.categories.map(({ category, percent: stake }) => (
              <div key={category}>
                <dt>{category}</dt>
                <dd>
                  {stake === null ? (
                    <span />
                  ) : (
                    <meter
                      min={0}
                      max={100}
                      value={stake}
                      aria-label={`${category} share of ownership`}
                    />
                  )}
                  <strong className="mono">{percent(stake)}</strong>
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="muted">
            A complete ownership breakdown is unavailable for this quarter.
          </p>
        )}
        <SourceNote company={company} />
      </section>
      <section className="panel stock-section">
        <div className="section-line stock-section-heading">
          <h2>Financials</h2>
          <div className="stock-selects">
            <label>
              Measure{" "}
              <select
                aria-label="Measure"
                value={metric}
                onChange={(event) =>
                  setMetric(event.target.value as typeof metric)
                }
              >
                <option value="revenue_cr">Revenue</option>
                <option value="net_profit_cr">Net profit</option>
              </select>
            </label>
            <label>
              Period{" "}
              <select
                aria-label="Period"
                value={frequency}
                onChange={(event) =>
                  setFrequency(event.target.value as typeof frequency)
                }
              >
                <option value="annual">Yearly</option>
                <option value="quarterly">Quarterly</option>
              </select>
            </label>
          </div>
        </div>
        {financials.length ? (
          <>
            <ReportHistoryChart
              values={financials}
              bars
              label={`${metric === "net_profit_cr" ? "Net profit" : "Revenue"} in crore rupees`}
              unit="₹ Cr"
            />
            <dl className="stock-metrics stock-periods">
              {financials.map((item) => (
                <div key={item.date}>
                  <dt>
                    {company[frequency]?.find(
                      (row) => row.period_end === item.date,
                    )?.period ?? item.date}
                  </dt>
                  <dd>₹{fmt(item.value, 0)} Cr</dd>
                </div>
              ))}
            </dl>
          </>
        ) : (
          <p className="muted">
            No dated financial figures are available for this selection.
          </p>
        )}
        <SourceNote company={company} />
      </section>
    </>
  );
}

function PriceParticipation({ candles }: { candles: Candle[] }) {
  const [metric, setMetric] = useState<"returns" | "volume">("returns");
  const points = useMemo(() => {
    const baseline = candles[0]?.close;
    if (!baseline) return [];
    return candles.flatMap((candle) => {
      const value =
        metric === "volume"
          ? number(candle.volume)
          : (candle.close / baseline - 1) * 100;
      return value === undefined ? [] : [{ date: candle.date, value }];
    });
  }, [candles, metric]);
  return (
    <section className="panel stock-section">
      <div className="section-line stock-section-heading">
        <h2>Price &amp; volume history</h2>
        <div
          className="chart-sizes"
          role="group"
          aria-label="Price and volume view"
        >
          <button
            type="button"
            aria-pressed={metric === "returns"}
            onClick={() => setMetric("returns")}
          >
            Past returns
          </button>
          <button
            type="button"
            aria-pressed={metric === "volume"}
            onClick={() => setMetric("volume")}
          >
            Past volume
          </button>
        </div>
      </div>
      {points.length ? (
        <ReportHistoryChart
          values={points}
          bars={metric === "volume"}
          unit={metric === "volume" ? "shares" : "%"}
          label={
            metric === "volume"
              ? "Shares traded by date"
              : "% return from the first completed close"
          }
        />
      ) : (
        <p className="muted">No historical values are available.</p>
      )}
    </section>
  );
}

function StockReportContent({ report }: { report: StockReport }) {
  const { notify } = useWorkspace();
  const [exporting, setExporting] = useState(false);
  const scope: ReportScope = {
    symbol: report.symbol,
    horizon: report.horizon,
    strategy: report.strategy.strategy_id,
  };
  const plan = report.display_plan ?? report.trade_plan;
  const conditions = report.trade_plan.conditions ?? [];
  const references = Object.entries(
    report.trade_plan.indicator_references ?? {},
  );
  const rating = report.rating ?? {};
  const paper = `/app/classic/paper_session?${new URLSearchParams({ review_symbol: report.symbol })}`;
  async function downloadHtml() {
    setExporting(true);
    try {
      await downloadCore(
        `reports/stocks/${encodeURIComponent(report.symbol)}/report.html?${reportQuery(scope)}`,
        `${report.symbol}_TrendForge_Report.html`,
      );
    } catch (error) {
      notify((error as Error).message);
    } finally {
      setExporting(false);
    }
  }
  return (
    <div className="stock-report-content">
      <section className="panel stock-section stock-hero">
        <div>
          <span className="small-tag">
            NSE · {report.horizon === longTerm ? "Long Term" : "Short Term"}
          </span>
          <h2>{report.symbol}</h2>
          <p className="muted">{report.company_name}</p>
        </div>
        <dl className="stock-metrics">
          <div>
            <dt>{report.price.basis}</dt>
            <dd>
              <Money value={report.price.value} />
            </dd>
            <small>
              {report.price.bar_date ?? "No date"} · {report.price.source}
            </small>
          </div>
          <div>
            <dt>Strategy signal</dt>
            <dd>{human(text(report.technical.signal, "Unavailable"))}</dd>
            <small>{report.strategy.name}</small>
          </div>
          <div>
            <dt>Combined rating</dt>
            <dd>{human(text(rating.rating, "Unrated"))}</dd>
            <small>
              {number(rating.score) !== undefined
                ? `${fmt(rating.score)} score`
                : "Score unavailable"}
            </small>
          </div>
        </dl>
        {report.market_error?.data_reason != null && (
          <p className="banner amber-banner">
            <CircleAlert size={15} />
            {text(report.market_error.data_reason)}
          </p>
        )}
        {number(report.market_quote?.last_price) !== undefined && (
          <p className="subtle">
            Observed LTP {money(report.market_quote?.last_price)} ·{" "}
            {ist(report.market_quote?.timestamp)}
          </p>
        )}
        <div className="stock-actions">
          <button
            className="button"
            onClick={() => void downloadHtml()}
            disabled={exporting}
          >
            <Download size={15} />
            {exporting ? "Preparing…" : "Save report"}
          </button>
          <button
            className="button"
            onClick={() =>
              saveDownload(
                new Blob([JSON.stringify(report, null, 2)], {
                  type: "application/json",
                }),
                `${report.symbol}_report.json`,
              )
            }
          >
            <Download size={15} />
            Download evidence
          </button>
          {report.paper_review_available && (
            <a className="button" href={paper}>
              Review paper trade <ExternalLink size={14} />
            </a>
          )}
        </div>
      </section>
      <ReportPrices report={report} />
      <div className="stock-report-pair">
        <section className="panel stock-section">
          <h2>Overview</h2>
          <ul className="stock-bullets">
            {report.overview.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
        <section className="panel stock-section">
          <h2>Risks &amp; trade plan</h2>
          <p className="muted">{human(text(plan.status, "Unavailable"))}</p>
          <dl className="stock-metrics">
            <div>
              <dt>Entry reference</dt>
              <dd>
                <Money value={plan.entry} />
              </dd>
            </div>
            <div>
              <dt>Stop reference</dt>
              <dd>
                <Money value={plan.stop_reference} />
              </dd>
            </div>
            <div>
              <dt>Targets</dt>
              <dd>
                {plan.targets
                  ?.filter((value) => value !== null)
                  .map(money)
                  .join(" · ") || "See exit rules"}
              </dd>
            </div>
          </dl>
          {typeof plan.reason === "string" && <p>{plan.reason}</p>}
          {typeof plan.data_note === "string" && (
            <p className="muted">{plan.data_note}</p>
          )}
          {typeof plan.exit_condition === "string" && (
            <p className="muted">{plan.exit_condition}</p>
          )}
          {conditions.length > 0 && (
            <details className="stock-details">
              <summary>
                Entry checks · {conditions.filter((item) => item.passed).length}
                /{conditions.length} passed
              </summary>
              <ul className="stock-bullets">
                {conditions.map((item) => (
                  <li key={item.condition}>
                    {item.passed ? "Pass" : "Wait"} · {human(item.condition)}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <details className="stock-details">
            <summary>Approved entry and exit conditions</summary>
            <ul className="stock-bullets">
              {[
                ...report.strategy.entry_rules,
                ...report.strategy.exit_rules,
                ...(report.strategy.target_rules ?? []),
                ...(report.strategy.stoploss_rules ?? []),
                ...report.risk_notes,
              ].map((rule, i) => (
                <li key={i}>{rule}</li>
              ))}
            </ul>
          </details>
          {references.length > 0 && (
            <details className="stock-details">
              <summary>Indicator and yearly pivot references</summary>
              <dl className="stock-metrics">
                {references.map(([key, value]) => (
                  <div key={key}>
                    <dt>{key.replaceAll("_", " ")}</dt>
                    <dd>{money(value)}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </section>
      </div>
      <section className="panel stock-section">
        <h2>Recent news</h2>
        {report.news.length ? (
          <ul className="stock-news">
            {report.news.map((item) => {
              const href = linkToSource(item.url);
              return (
                <li key={item.url}>
                  {href ? (
                    <a href={href} target="_blank" rel="noreferrer">
                      {item.title} <ExternalLink size={13} />
                    </a>
                  ) : (
                    <strong>{item.title}</strong>
                  )}
                  <small>
                    {item.source} ·{" "}
                    {item.published_at
                      ? ist(item.published_at)
                      : (item.publication_date ?? "Date unavailable")}
                  </small>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="muted">No recent dated articles are available.</p>
        )}
      </section>
      <CompanyEvidence company={report.company} />
      <PriceParticipation candles={report.candles} />
      <section className="panel stock-section">
        <h2>Evaluation &amp; data coverage</h2>
        <p className="muted">
          {text(
            rating.reason,
            "Actual institutional trade evidence is unavailable.",
          )}
        </p>
        <dl className="stock-metrics">
          <div>
            <dt>Institutional activity</dt>
            <dd>{human(text(rating.activity_signal, "Unavailable"))}</dd>
          </div>
          <div>
            <dt>Coverage</dt>
            <dd>{human(text(rating.data_coverage, "Unavailable"))}</dd>
          </div>
          <div>
            <dt>Disclosure time</dt>
            <dd>{ist(rating.disclosure_time)}</dd>
          </div>
          <div>
            <dt>Technical assessment</dt>
            <dd>
              {human(text(report.technical_assessment?.status, "Unavailable"))}
            </dd>
          </div>
        </dl>
        {report.evaluation_diagnostics?.length ? (
          <ul className="stock-evaluation">
            {report.evaluation_diagnostics.map((row, i) => (
              <li key={i}>
                <strong>{human(text(row.component))}</strong>
                <span className="small-tag">{human(text(row.status))}</span>
                <span>{text(row.reason)}</span>
              </li>
            ))}
          </ul>
        ) : null}
        {report.strategy_provenance && (
          <details className="stock-details">
            <summary>Strategy provenance</summary>
            <dl className="stock-metrics">
              {Object.entries(report.strategy_provenance)
                .filter(([, value]) => typeof value === "string")
                .map(([key, value]) => (
                  <div key={key}>
                    <dt>{human(key)}</dt>
                    <dd>{text(value)}</dd>
                  </div>
                ))}
            </dl>
          </details>
        )}
      </section>
    </div>
  );
}

export default function StockReports() {
  const { catalog, catalogError, read, universe } = useWorkspace();
  const query = useSearchParams();
  const linkedSymbol = query.get("symbol")?.trim().toUpperCase() ?? "";
  const linkedHorizon =
    query.get("horizon") === longTerm ? longTerm : shortTerm;
  const linkedStrategy = query.get("strategy_id") ?? "";
  const [scope, setScope] = useState<ReportScope>(homeScope);
  const [report, setReport] = useState<StockReport | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [memberList, setMembers] = useState<{
    universe: string;
    data: StockMembership;
  } | null>(null);
  const [memberError, setMemberError] = useState("");
  const [loadingMembers, setLoadingMembers] = useState(false);
  const controller = useRef<AbortController>(null);
  const strategies = catalog.strategies.filter(
    (item) => item.scanner && item.horizons.includes(scope.horizon),
  );
  const selected =
    strategies.find((item) => item.strategy_id === scope.strategy)
      ?.strategy_id ??
    catalog.stock_report_defaults?.[scope.horizon] ??
    strategies[0]?.strategy_id ??
    "";

  useEffect(() => {
    if (!linkedSymbol) return;
    if (!catalog.stock_report_defaults) return;
    const strategy = catalog.strategies.some(
      (item) =>
        item.scanner &&
        item.strategy_id === linkedStrategy &&
        item.horizons.includes(linkedHorizon),
    )
      ? linkedStrategy
      : "";
    const initial: ReportScope = {
      symbol: linkedSymbol,
      horizon: linkedHorizon,
      strategy,
    };
    setScope(initial);
    if (!validSymbol(linkedSymbol)) {
      setReport(null);
      setError("Enter a valid NSE stock symbol.");
      return;
    }
    const request = new AbortController();
    controller.current?.abort();
    controller.current = request;
    setLoading(true);
    setError("");
    setReport(null);
    void fetchStockReport(read, initial, request.signal)
      .then((result) => {
        if (!request.signal.aborted) setReport(result);
      })
      .catch((failure: Error) => {
        if (!request.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!request.signal.aborted) setLoading(false);
      });
    return () => request.abort();
  }, [linkedSymbol, linkedHorizon, linkedStrategy, catalog, read]);
  useEffect(() => () => controller.current?.abort(), []);

  function changeScope(next: ReportScope) {
    controller.current?.abort();
    setScope(next);
    setReport(null);
    setError("");
    setLoading(false);
  }

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const symbol = scope.symbol.trim().toUpperCase();
    if (!validSymbol(symbol)) {
      setError("Enter a valid NSE stock symbol.");
      return;
    }
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setScope({ ...scope, symbol });
    setReport(null);
    setError("");
    setLoading(true);
    try {
      const result = await fetchStockReport(
        read,
        { ...scope, symbol, strategy: selected },
        request.signal,
        true,
      );
      if (!request.signal.aborted) setReport(result);
    } catch (failure) {
      if (!request.signal.aborted) setError((failure as Error).message);
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }

  async function browseMembers() {
    setLoadingMembers(true);
    setMemberError("");
    try {
      setMembers({ universe, data: await stockMembers(universe) });
    } catch (failure) {
      setMemberError((failure as Error).message);
    } finally {
      setLoadingMembers(false);
    }
  }
  const membership = memberList?.universe === universe ? memberList.data : null;
  return (
    <>
      <header className="page-heading">
        <div>
          <div className="breadcrumb">
            Workspace <span>/</span> Stock Reports
          </div>
          <h1>Stock Reports</h1>
          <p>
            Review the price, technical setup, company data and source evidence
            for an NSE stock.
          </p>
        </div>
        <Link href="/scanner" className="button">
          <ChartNoAxesCombined size={15} />
          Scanner Workbench
        </Link>
      </header>
      <section className="panel stock-section stock-lookup">
        <form onSubmit={generate}>
          <label>
            NSE stock symbol
            <input
              value={scope.symbol}
              onChange={(event) =>
                changeScope({
                  ...scope,
                  symbol: event.target.value.toUpperCase(),
                })
              }
              list="report-stock-members"
              placeholder="e.g. INDUSTOWER"
              maxLength={30}
              required
            />
          </label>
          <datalist id="report-stock-members">
            {membership?.rows.map(({ symbol, stock_name }) => (
              <option key={symbol} value={symbol}>
                {stock_name}
              </option>
            ))}
          </datalist>
          <label>
            Report horizon
            <select
              value={scope.horizon}
              onChange={(event) =>
                changeScope({
                  ...scope,
                  horizon: event.target.value as StockReportHorizon,
                  strategy: "",
                })
              }
            >
              <option value="short_term">Short Term</option>
              <option value="long_term">Long Term</option>
            </select>
          </label>
          <label>
            Report strategy
            <select
              value={selected}
              onChange={(event) =>
                changeScope({ ...scope, strategy: event.target.value })
              }
            >
              {!strategies.length && <option value="">Default strategy</option>}
              {strategies.map((item) => (
                <option key={item.strategy_id} value={item.strategy_id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="button primary" disabled={loading}>
            <Search size={15} />
            {loading ? "Preparing…" : "Generate stock report"}
          </button>
        </form>
        <div className="stock-member-tools">
          <button
            className="inline-button"
            onClick={() => void browseMembers()}
            disabled={loadingMembers}
          >
            {loadingMembers ? "Loading members…" : `Browse ${universe} members`}
          </button>
          {membership && (
            <span className="subtle">
              {membership.rows.length} members
              {membership.source && ` · ${membership.source}`}
            </span>
          )}
        </div>
        {membership && (
          <div className="stock-member-list" aria-label={`${universe} members`}>
            {membership.rows
              .filter((member) =>
                `${member.symbol} ${member.stock_name ?? ""}`
                  .toUpperCase()
                  .includes(scope.symbol.trim()),
              )
              .slice(0, 20)
              .map(({ symbol }) => (
                <Link
                  className="small-tag"
                  key={symbol}
                  href={stockReportHref(symbol, scope.horizon, selected)}
                >
                  {symbol}
                </Link>
              ))}
          </div>
        )}
        {(memberError || membership?.source_warning) && (
          <p className="muted">{memberError || membership?.source_warning}</p>
        )}
        {(error || catalogError) && (
          <p className="banner danger" role="alert">
            {error || catalogError}
          </p>
        )}
      </section>
      {loading && (
        <p className="stock-loading" role="status">
          Preparing price, strategy and company evidence…
        </p>
      )}
      {report && (
        <StockReportContent key={report.generated_at} report={report} />
      )}
      {!report && !loading && !error && (
        <div className="panel empty compact">
          <Search size={22} />
          <strong>Choose a stock to generate a report</strong>
        </div>
      )}
    </>
  );
}
