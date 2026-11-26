/* Financial regression cases over the actual TypeScript used by Workbench. */
const assert = require("node:assert/strict");
const { test, after } = require("node:test");
const { mkdtempSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const root = path.resolve(__dirname, ".."), frontend = path.join(root, "frontend");
const compiled = mkdtempSync(path.join(tmpdir(), "tf-levels-"));
execFileSync(process.execPath, [path.join(frontend, "node_modules/typescript/bin/tsc"),
  "--module", "commonjs", "--moduleResolution", "node", "--target", "es2022",
  "--skipLibCheck", "--types", "node", "--outDir", compiled,
  "src/lib/trade-levels.ts", "src/lib/analytics.ts"], { cwd: frontend, stdio: "pipe" });
const { assessLevels, recordedInitialRisk } = require(path.join(compiled, "trade-levels.js"));
const { groupTrades } = require(path.join(compiled, "analytics.js"));
after(() => rmSync(compiled, { recursive: true, force: true }));
const target = (price, short = "T1") => ({ label: short, short, price });

test("breakout entry uses its displayed stop distance, not a stale cached risk", () => {
  const result = assessLevels(105, 98, [target(109)], "LONG", 2);
  assert.equal(result.risk, 7);
  assert.equal(result.riskDiffers, true);
  assert.ok(Math.abs(result.targets[0].rewardR - 0.5714285714285714) < 1e-12);
});
test("each staged target has an independent ratio and a proportional ruler", () => {
  const result = assessLevels(110, 100, [target(115), target(130, "T2"), target(150, "T3")]);
  assert.deepEqual(result.targets.map(t => t.rewardR), [0.5, 2, 4]);
  assert.equal(result.entryPercent, 20);
  assert.equal(result.furthest.price, 150);
});
test("zero placeholders and invalid-side targets never become chart targets", () => {
  const result = assessLevels(100, 90, [target(0), target(95, "T2"), target(120, "T3")]);
  assert.deepEqual(result.targets.map(t => t.price), [120]);
  assert.equal(result.issues.length, 1);
});
test("a reversed long bracket cannot produce a positive ratio through abs()", () => {
  const result = assessLevels(100, 110, [target(90)], "LONG");
  assert.equal(result.risk, undefined);
  assert.equal(result.targets.length, 0);
  assert.equal(result.entryPercent, undefined);
});
test("short geometry is valid only with stop above and target below entry", () => {
  const result = assessLevels(100, 110, [target(80)], "SHORT");
  assert.equal(result.risk, 10);
  assert.equal(result.targets[0].rewardR, 2);
  assert.equal(result.targets[0].rewardPercent, 20);
});
test("indicator exits do not invent a fixed target or an R multiple", () => {
  const result = assessLevels(100, 90, []);
  assert.equal(result.risk, 10);
  assert.equal(result.furthest, undefined);
  assert.equal(result.entryPercent, undefined);
});
test("missing, non-finite and duplicate references remain explicit", () => {
  assert.equal(assessLevels(Infinity, 90, [target(120)]).risk, undefined);
  assert.equal(assessLevels(100, NaN, [target(120)]).targets[0].rewardR, undefined);
  assert.equal(assessLevels(100, 90, [target(120), target(120, "T2")]).targets.length, 1);
});
test("partial exits share the original risk denominator and do not double costs", () => {
  const fills = [{trade_number:1,symbol:"EXAMPLE",side:"LONG",entry_at:"2026-11-20",exit_at:"2026-11-23",entry_price:100,initial_stoploss:90,entry_quantity:4,quantity:2,exit_price:105,net_pnl:8},
    {trade_number:1,symbol:"EXAMPLE",side:"LONG",entry_at:"2026-11-20",exit_at:"2026-11-25",entry_price:100,initial_stoploss:90,entry_quantity:4,quantity:2,exit_price:107,net_pnl:12}];
  assert.equal(recordedInitialRisk(fills), 40);
  const grouped = groupTrades(fills, "independent-account")[0];
  assert.equal(grouped.net, 20);
  assert.equal(grouped.riskMultiple, 0.5);
});
test("unverified historical stops and wrong-side initial stops cannot supply Net R", () => {
  const fill = {side:"LONG",entry_price:100,initial_stoploss:110,entry_quantity:4};
  assert.equal(recordedInitialRisk([fill]), undefined);
  assert.equal(recordedInitialRisk([{...fill,initial_stoploss:90,entry_quantity:0,quantity:4}]), undefined);
  assert.equal(recordedInitialRisk([{...fill,initial_stoploss:90,initial_stop_basis:"unverified_legacy_stop"}]), undefined);
});
