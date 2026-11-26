import { number, type Evidence } from "./model";

export const positivePrice = (value: unknown) => {
  const price = number(value);
  return price !== undefined && price > 0 ? price : undefined;
};

export type TargetLevel = { label: string; short?: string; price?: number };
export type AssessedTarget = TargetLevel & {
  price: number;
  reward: number;
  rewardPercent: number;
  rewardR?: number;
};

export function assessLevels(
  entryValue: unknown,
  stopValue: unknown,
  levels: TargetLevel[],
  side = "LONG",
  savedRisk?: unknown,
) {
  const entry = positivePrice(entryValue), stop = positivePrice(stopValue);
  const sign = side === "SHORT" || side === "SELL" ? -1 : 1;
  const issues: string[] = [];
  const distance = entry !== undefined && stop !== undefined ? sign * (entry - stop) : undefined;
  const risk = distance !== undefined && distance > 0 ? distance : undefined;
  if (entry !== undefined && stop !== undefined && risk === undefined)
    issues.push("The saved stop is on the wrong side of the entry; reward/risk is unavailable.");
  const seen = new Set<number>();
  const targets: AssessedTarget[] = [];
  for (const level of levels) {
    const price = positivePrice(level.price);
    if (price === undefined || entry === undefined || seen.has(price)) continue;
    seen.add(price);
    const reward = sign * (price - entry);
    if (reward <= 0) {
      issues.push(`${level.label} is not beyond the entry in the trade direction; it is excluded from reward/risk.`);
      continue;
    }
    const rewardR = risk === undefined ? undefined : reward / risk;
    targets.push({ ...level, price, reward, rewardPercent: (reward / entry) * 100, rewardR: rewardR !== undefined && Number.isFinite(rewardR) ? rewardR : undefined });
  }
  const recorded = number(savedRisk);
  const riskDiffers = risk !== undefined && recorded !== undefined && Math.abs(recorded - risk) > 1e-6;
  const furthest = targets.reduce<AssessedTarget | undefined>((last, target) => !last || target.reward > last.reward ? target : last, undefined);
  return {
    entry, stop, risk, riskPercent: risk !== undefined && entry ? (risk / entry) * 100 : undefined,
    targets, issues, riskDiffers, furthest,
    entryPercent: risk !== undefined && furthest ? 100 * risk / (risk + furthest.reward) : undefined,
  };
}

export function recordedInitialRisk(fills: Evidence[]) {
  if (!fills.length) return undefined;
  const first = fills[0], entry = positivePrice(first.entry_price), stop = positivePrice(first.initial_stoploss);
  const side = first.side;
  if (entry === undefined || stop === undefined || !["LONG", "BUY", "SHORT", "SELL"].includes(String(side))) return undefined;
  if (first.initial_stop_basis === "unverified_legacy_stop") return undefined;
  const sign = side === "SHORT" || side === "SELL" ? -1 : 1;
  const distance = sign * (entry - stop);
  const quantity = number(first.entry_quantity) ?? fills.reduce((sum, fill) => sum + (number(fill.quantity) ?? 0), 0);
  if (distance <= 0 || !Number.isFinite(quantity) || quantity <= 0 || !Number.isInteger(quantity)) return undefined;
  return distance * quantity;
}
