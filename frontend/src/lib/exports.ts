import { type Trade, summary } from "./analytics";
import { disclaimer, fmt, type Batch } from "./model";

export async function exportPdf(
  run: Batch,
  accounts: Batch[],
  trades: Trade[],
  strategy: string,
) {
  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF();
  const footer = () => {
    doc.setFontSize(8).setTextColor(90);
    doc.text(disclaimer, 17, 284);
  };
  const heading = () => {
    doc.setFillColor(17, 24, 39).rect(0, 0, 210, 41, "F");
    doc
      .setTextColor(255)
      .setFontSize(19)
      .text("TrendForge / Backtest summary", 17, 21);
    doc.setFontSize(10).text(strategy, 17, 31);
    footer();
  };
  heading();
  doc
    .setTextColor(50)
    .setFontSize(9)
    .text(`Run ${run.batch_id}  |  ${run.stock_list}`, 17, 52);
  if (accounts.length > 1)
    doc.text(
      "Each account uses its own starting capital. Metrics are reported by account.",
      17,
      59,
    );
  let y = 72;
  for (const account of accounts) {
    if (y > 235) {
      doc.addPage();
      heading();
      y = 58;
    }
    const report = account.report!;
    const s = summary(
      report,
      trades.filter((trade) => trade.account === account.batch_id),
    );
    doc.setTextColor(22, 33, 50).setFontSize(11).text(account.batch_id, 17, y);
    doc
      .setFontSize(9)
      .text(
        `Net P&L  INR ${fmt(s.net)}    Gross P&L  INR ${fmt(s.gross)}    Return  ${fmt(s.rate)}%`,
        17,
        y + 7,
      );
    doc.text(
      `Win rate  ${fmt(s.winRate, 1)}%    Profit factor  ${fmt(s.factor)}    Max drawdown  ${fmt(s.drawdown)}%`,
      17,
      y + 13,
    );
    doc.text(
      `Universe coverage  ${fmt(s.included, 0)} / ${fmt(account.requested_symbols, 0)}    Trades  ${trades.filter((trade) => trade.account === account.batch_id).length}`,
      17,
      y + 19,
    );
    y += 30;
  }
  doc.save(`${run.batch_id}.pdf`);
}
