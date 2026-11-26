"use client";

import { useEffect, useRef } from "react";
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type AutoscaleInfoProvider,
  type LogicalRange,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Candle, Point } from "@/lib/model";

export type Level = {
  label: string;
  price: number;
  color: string;
  pivot?: boolean;
};
export type Marker = {
  date: string;
  label: string;
  kind: "signal" | "entry" | "exit";
};
export type ChartZoom = { candles: Candle[]; range: LogicalRange } | null;
const palette = {
  green: "#35d2a5",
  red: "#f37682",
  blue: "#78a7ff",
  purple: "#b29afd",
  amber: "#f6bb65",
  cyan: "#69c8de",
};
const averages = [
  { key: "EMA 100", length: 100, color: palette.blue },
  { key: "EMA 200", length: 200, color: palette.purple },
  { key: "VWMA 20", length: 20, color: palette.amber },
  { key: "VWMA 50", length: 50, color: palette.cyan },
];
export const indicators = averages.map(({ key, color }) => ({ key, color }));
const timestamp = (date: string, daily = false) =>
  (Date.parse(daily ? date.slice(0, 10) : date) / 1000) as UTCTimestamp;
const istTick = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const chartOptions = {
  layout: {
    textColor: "#8b9bb0",
    background: { type: ColorType.Solid, color: "#101824" },
    fontFamily: "JetBrains Mono Variable, monospace",
    fontSize: 10,
    attributionLogo: true,
  },
  grid: { vertLines: { color: "#1d2938" }, horzLines: { color: "#1d2938" } },
  rightPriceScale: {
    borderColor: "#283546",
    scaleMargins: { top: 0.11, bottom: 0.22 },
  },
  timeScale: { borderColor: "#283546", rightOffset: 5, minBarSpacing: 4 },
  crosshair: {
    mode: CrosshairMode.Normal,
    vertLine: { color: "#72859b66", labelBackgroundColor: "#29384c" },
    horzLine: { color: "#72859b66", labelBackgroundColor: "#29384c" },
  },
} as const;

export function PriceChart({
  candles,
  levels,
  visible,
  markers,
  interval = "1d",
  range,
  sharedZoom,
}: {
  candles: Candle[];
  levels: Level[];
  visible: string[];
  markers?: Marker[];
  interval?: string;
  range?: [string, string];
  sharedZoom?: { current: ChartZoom };
}) {
  const root = useRef<HTMLDivElement>(null);
  const ownZoom = useRef<ChartZoom>(null);
  const zoom = sharedZoom ?? ownZoom;
  useEffect(() => {
    if (!root.current || !candles.length) return;
    const daily = interval !== "15m";
    const time = (date: string) => timestamp(date, daily);
    const chart = createChart(root.current, {
      ...chartOptions,
      autoSize: true,
      localization: daily
        ? {}
        : {
            timeFormatter: (stamp: UTCTimestamp) =>
              `${new Date(stamp * 1000).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata" })} ${istTick.format(stamp * 1000)}`,
          },
      timeScale: {
        ...chartOptions.timeScale,
        timeVisible: !daily,
        secondsVisible: false,
        ...(daily
          ? {}
          : {
              tickMarkFormatter: (stamp: UTCTimestamp, type: number) =>
                type >= 3 ? istTick.format(stamp * 1000) : null,
            }),
      },
    });
    const price = chart.addSeries(CandlestickSeries, {
      upColor: palette.green,
      downColor: palette.red,
      wickUpColor: palette.green,
      wickDownColor: palette.red,
      borderVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    price.setData(
      candles.map(({ date, ...candle }) => ({ ...candle, time: time(date) })),
    );
    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "",
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    volume
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.83, bottom: 0 } });
    volume.setData(
      candles.flatMap((c) =>
        c.volume == null
          ? []
          : [
              {
                time: time(c.date),
                value: c.volume,
                color: c.close >= c.open ? "#35d2a543" : "#f3768243",
              },
            ],
      ),
    );
    for (const avg of averages) {
      if (!visible.includes(avg.key)) continue;
      const series = chart.addSeries(LineSeries, {
        color: avg.color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      const values: { time: Time; value: number }[] = [];
      let ema = 0,
        totalVolume = 0,
        weighted = 0;
      for (let i = 0; i < candles.length; i++) {
        const c = candles[i];
        if (avg.key.startsWith("EMA")) {
          if (i < avg.length) ema += c.close / avg.length;
          else ema += ((c.close - ema) * 2) / (avg.length + 1);
          if (i >= avg.length - 1)
            values.push({ time: time(c.date), value: ema });
        } else {
          const prev = candles[i - avg.length];
          totalVolume += (c.volume ?? 0) - (prev?.volume ?? 0);
          weighted +=
            c.close * (c.volume ?? 0) -
            (prev ? prev.close * (prev.volume ?? 0) : 0);
          if (i >= avg.length - 1 && totalVolume > 0)
            values.push({ time: time(c.date), value: weighted / totalVolume });
        }
      }
      series.setData(values);
    }
    for (const level of levels)
      price.createPriceLine({
        price: level.price,
        color: level.color,
        title: level.label,
        lineStyle: level.pivot ? LineStyle.Dotted : LineStyle.Dashed,
        axisLabelVisible: true,
        lineWidth: 1,
      });
    if (levels.length) {
      const includeTradeLevels: AutoscaleInfoProvider = (original) => {
        const info = original();
        if (!info?.priceRange) return info;
        const tradeLevels = levels.filter(
          (level) => !level.pivot && !level.label.startsWith("Exit"),
        );
        return {
          ...info,
          priceRange: {
            minValue: Math.min(
              info.priceRange.minValue,
              ...tradeLevels.map((level) => level.price),
            ),
            maxValue: Math.max(
              info.priceRange.maxValue,
              ...tradeLevels.map((level) => level.price),
            ),
          },
        };
      };
      price.applyOptions({ autoscaleInfoProvider: includeTradeLevels });
    }
    if (markers) {
      const candleTimes = new Set(candles.map((c) => time(c.date)));
      const data: SeriesMarker<Time>[] = markers.flatMap((mark) =>
        candleTimes.has(time(mark.date))
          ? [
              {
                time: time(mark.date),
                position:
                  mark.kind === "exit"
                    ? ("aboveBar" as const)
                    : ("belowBar" as const),
                color:
                  mark.kind === "exit"
                    ? palette.red
                    : mark.kind === "entry"
                      ? palette.green
                      : palette.blue,
                shape:
                  mark.kind === "exit"
                    ? ("arrowDown" as const)
                    : mark.kind === "entry"
                      ? ("arrowUp" as const)
                      : ("circle" as const),
                text: mark.label,
              },
            ]
          : [],
      );
      createSeriesMarkers(
        price,
        data.sort((a, b) => Number(a.time) - Number(b.time)),
      );
    }
    const scale = chart.timeScale();
    const start = range
      ? candles.findIndex((c) => time(c.date) >= time(range[0]))
      : -1;
    const end = range
      ? candles.findLastIndex((c) => time(c.date) <= time(range[1]))
      : -1;
    if (zoom.current?.candles === candles)
      scale.setVisibleLogicalRange(zoom.current.range);
    else
      scale.setVisibleLogicalRange(
        start >= 0 && end >= start
          ? { from: Math.max(0, start - 12), to: end + 12 }
          : { from: Math.max(0, candles.length - 100), to: candles.length + 4 },
      );
    return () => {
      const visibleRange = scale.getVisibleLogicalRange();
      if (visibleRange) zoom.current = { candles, range: visibleRange };
      chart.remove();
    };
  }, [candles, levels, visible, markers, interval, range, zoom]);
  return (
    <div
      ref={root}
      className="price-chart"
      aria-label="Interactive candlestick chart with trade levels and volume"
      role="img"
    />
  );
}

export function PerformanceChart({
  curve,
  benchmark,
  initialCapital,
}: {
  curve: Point[];
  benchmark: Point[];
  initialCapital?: number;
}) {
  const equity = useRef<HTMLDivElement>(null);
  const drawdown = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!equity.current || !drawdown.current || curve.length < 2) return;
    const start =
      initialCapital && initialCapital > 0 ? initialCapital : curve[0].equity;
    const snapshots = new Map<number, number>();
    curve.forEach((point) =>
      snapshots.set(timestamp(point.date, true), point.equity),
    );
    const daily = [...snapshots].sort(([a], [b]) => a - b);
    const chart = createChart(equity.current, {
      ...chartOptions,
      autoSize: true,
      rightPriceScale: {
        ...chartOptions.rightPriceScale,
        minimumWidth: 62,
        scaleMargins: { top: 0.14, bottom: 0.11 },
      },
      timeScale: { ...chartOptions.timeScale, visible: false },
    });
    const underwater = createChart(drawdown.current, {
      ...chartOptions,
      autoSize: true,
      rightPriceScale: {
        ...chartOptions.rightPriceScale,
        minimumWidth: 62,
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
    });
    const spec = {
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat: {
        type: "custom" as const,
        formatter: (value: number) => `${value.toFixed(1)}%`,
      },
    };
    const result = chart.addSeries(AreaSeries, {
      ...spec,
      topColor: "#35d2a540",
      bottomColor: "#35d2a500",
      lineColor: palette.green,
      lineWidth: 2,
    });
    result.setData(
      daily.map(([date, amount]) => ({
        time: date as UTCTimestamp,
        value: (amount / start - 1) * 100,
      })),
    );
    if (benchmark.length) {
      const baseline = benchmark[0].equity;
      const comparison = chart.addSeries(LineSeries, {
        ...spec,
        color: palette.blue,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
      });
      comparison.setData(
        benchmark.map((c) => ({
          time: timestamp(c.date, true),
          value: (c.equity / baseline - 1) * 100,
        })),
      );
    }
    let peak = start;
    const draw = underwater.addSeries(AreaSeries, {
      ...spec,
      topColor: "#f3768208",
      bottomColor: "#f3768250",
      lineColor: palette.red,
      lineWidth: 1,
    });
    draw.setData(
      curve
        .filter(
          (point, i) =>
            i === 0 || Date.parse(point.date) > Date.parse(curve[i - 1].date),
        )
        .reduce<{ time: UTCTimestamp; value: number }[]>((points, point) => {
          peak = Math.max(peak, point.equity);
          const time = timestamp(point.date, true);
          const value = (point.equity / peak - 1) * 100;
          const previous = points.at(-1);
          if (previous?.time === time)
            previous.value = Math.min(previous.value, value);
          else points.push({ time, value });
          return points;
        }, []),
    );
    chart.timeScale().fitContent();
    underwater.timeScale().fitContent();
    let syncing = false;
    const sync = (source: typeof chart, target: typeof chart) =>
      source.timeScale().subscribeVisibleTimeRangeChange((range) => {
        if (!range || syncing) return;
        syncing = true;
        target.timeScale().setVisibleRange(range);
        syncing = false;
      });
    sync(chart, underwater);
    sync(underwater, chart);
    return () => {
      chart.remove();
      underwater.remove();
    };
  }, [curve, benchmark, initialCapital]);
  return (
    <>
      <div
        className="equity-chart"
        ref={equity}
        role="img"
        aria-label="Equity return over time"
      />
      <div className="chart-subtitle">Underwater drawdown</div>
      <div
        className="drawdown-chart"
        ref={drawdown}
        role="img"
        aria-label="Drawdown over time"
      />
    </>
  );
}
