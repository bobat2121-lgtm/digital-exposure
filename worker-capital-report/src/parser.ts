import { load } from "cheerio/slim";
import type { Extraction, Facts, Ticker } from "./types";

export const PARSER_VERSION = "sec-weekly-v1";
const MONTH = "(?:January|February|March|April|May|June|July|August|September|October|November|December)";
const DATE = `${MONTH}\\s+\\d{1,2},\\s+\\d{4}`;
const compact = (text: string): string => text.replace(/[\u00a0\u200b]/g, " ").replace(/\s+/g, " ").trim();
function isoDate(text: string): string | null {
  const stamp = Date.parse(`${text} 12:00:00 UTC`);
  return Number.isFinite(stamp) ? new Date(stamp).toISOString().slice(0, 10) : null;
}
function numeric(text: string): number | null {
  let value = compact(text).replace(/\s+\(\d+\)$/, "").replace(/^\$\s*/, "");
  if (/^[-—–]$/.test(value)) return 0;
  const negative = /^\([\d,.]+\)$/.test(value);
  if (negative) value = value.slice(1, -1);
  if (!/^-?\d[\d,]*(?:\.\d+)?$/.test(value)) return null;
  const result = Number(value.replaceAll(",", "")) * (negative ? -1 : 1);
  return Number.isFinite(result) ? result : null;
}
function values(cells: string[]): number[] {
  return cells.map(numeric).filter((value): value is number => value !== null);
}
interface Table { text: string; rows: string[][] }
function htmlTables(html: string): { text: string; tables: Table[] } {
  const $ = load(html);
  $("script,style,ix\\:hidden,header").remove();
  const tables = $("table").toArray().map(table => {
    const rows = $(table).find("tr").toArray()
      .filter(row => $(row).closest("table")[0] === table)
      .map(row => $(row).children("td,th").toArray().map(cell => compact($(cell).text())));
    return { text: rows.flat().join(" "), rows };
  });
  return { text: compact($.root().text()), tables };
}
function put(facts: Facts, key: string, value: number, issues: string[]): void {
  if (key in facts && facts[key] !== value) issues.push(`Conflicting ${key} values`);
  else facts[key] = value;
}
function validate(extraction: Extraction, required: string[]): Extraction {
  extraction.missing = required.filter(key => !(key in extraction.facts));
  if (!extraction.periodStart || !extraction.periodEnd || !extraction.balanceDate) extraction.missing.push("reporting_period");
  if (extraction.periodStart && extraction.periodEnd && extraction.periodStart > extraction.periodEnd)
    extraction.issues.push("Reporting period is reversed");
  for (const [key, value] of Object.entries(extraction.facts)) {
    if (!key.startsWith("net_") && value < 0) extraction.issues.push(`Negative ${key}`);
    if (key.includes("shares") && !Number.isSafeInteger(value)) extraction.issues.push(`Non-integral ${key}`);
  }
  extraction.extractionValidated = extraction.missing.length === 0 && extraction.issues.length === 0;
  return extraction;
}
export function extractWeekly(html: string, ticker: Ticker): Extraction {
  const { text, tables } = htmlTables(html);
  const e: Extraction = { parserVersion: PARSER_VERSION, periodStart: null, periodEnd: null,
    priorBalanceDate: null, balanceDate: null, facts: {}, priorFacts: {}, securities: {},
    missing: [], issues: [], extractionValidated: false };
  const dates = [...text.matchAll(new RegExp(`(?:During Period|period from)\\s+(${DATE})\\s+(?:to|through)\\s+(${DATE})`, "gi"))];
  if (dates.length) {
    e.periodStart = isoDate(dates[0][1]); e.periodEnd = isoDate(dates[0][2]); e.balanceDate = e.periodEnd;
    if (dates.some(match => isoDate(match[1]) !== e.periodStart || isoDate(match[2]) !== e.periodEnd))
      e.issues.push("Multiple reporting periods require review");
  }
  if (ticker === "ASST") {
    const mapping: [RegExp, string, number][] = [
      [/^Cash and cash equivalents \(in thousands\)$/i, "cash_and_equivalents_usd", 1000],
      [/^Fair value of STRC Stock \(in thousands\)$/i, "held_strc_fair_value_usd", 1000],
      [/^Shares of STRC held$/i, "held_strc_shares", 1],
      [/^Bitcoin held$/i, "btc_holdings", 1],
      [/^Class A common stock$/i, "common_shares_class_a", 1],
      [/^Class B common stock$/i, "common_shares_class_b", 1],
      [/^Effective Common Shares Outstanding(?: \(\d+\))?$/i, "effective_common_shares", 1],
      [/^Options(?: \(\d+\))?$/i, "options", 1],
      [/^Unvested employee stock awards(?: \(\d+\))?$/i, "unvested_employee_awards", 1],
      [/^Assumed Fully Diluted Shares(?: \(\d+\))?$/i, "assumed_diluted_shares", 1],
      [/^Shares Underlying Traditional Warrants(?: \(\d+\))?$/i, "traditional_warrant_shares", 1],
      [/^SATA Stock$/i, "sata_shares", 1],
    ];
    for (const table of tables.filter(t => /Bitcoin held/i.test(t.text) && /Effective Common Shares Outstanding/i.test(t.text))) {
      const asOf = [...table.text.matchAll(new RegExp(`As of\\s+(${DATE})`, "gi"))];
      if (asOf.length !== 2) { e.issues.push("Strive balance table needs two dated columns"); continue; }
      const prior = isoDate(asOf[0][1]), current = isoDate(asOf[1][1]);
      if (e.balanceDate && e.balanceDate !== current) e.issues.push("Strive table and purchase period dates disagree");
      e.priorBalanceDate = prior; e.balanceDate = current;
      for (const row of table.rows) {
        const cells = row.filter(Boolean);
        const definition = mapping.find(([pattern]) => pattern.test(cells[0] ?? ""));
        if (!definition) continue;
        const [, key, scale] = definition;
        const parsed = values(cells.slice(1));
        if (parsed.length !== 3) { e.issues.push(`Strive ${key} has unexpected columns`); continue; }
        const [before, after, delta] = parsed.map(v => v * scale);
        if (Math.abs(after - before - delta) > 0.005) e.issues.push(`Strive ${key} change does not reconcile`);
        put(e.facts, key, after, e.issues); put(e.priorFacts, key, before, e.issues);
        if (key === "effective_common_shares") put(e.facts, "net_common_shares_change", delta, e.issues);
        if (key === "sata_shares") put(e.facts, "net_sata_shares_change", delta, e.issues);
      }
    }
    const purchase = text.match(/\bStrive purchased\s+([\d,]+(?:\.\d+)?)\s+bitcoin\b/i);
    if (purchase) e.facts.weekly_btc_purchases = Number(purchase[1].replaceAll(",", ""));
    for (const facts of [e.facts, e.priorFacts]) {
      if (["common_shares_class_a", "common_shares_class_b", "effective_common_shares"].every(key => key in facts)
          && facts.common_shares_class_a + facts.common_shares_class_b !== facts.effective_common_shares)
        e.issues.push("Strive common share classes do not reconcile");
      if (["effective_common_shares", "options", "unvested_employee_awards", "assumed_diluted_shares"].every(key => key in facts)
          && facts.effective_common_shares + facts.options + facts.unvested_employee_awards !== facts.assumed_diluted_shares)
        e.issues.push("Strive assumed diluted shares do not reconcile");
    }
    return validate(e, ["btc_holdings", "weekly_btc_purchases", "cash_and_equivalents_usd", "held_strc_shares",
      "effective_common_shares", "sata_shares", "net_common_shares_change", "net_sata_shares_change"]);
  }
  for (const table of tables) {
    if (/Shares Sold/i.test(table.text) && /Net Proceeds\s*\(in millions\)/i.test(table.text)) {
      const hasNotional = /Notional Value/i.test(table.text);
      for (const row of table.rows) {
        const cells = row.filter(Boolean);
        const match = cells[0]?.match(/^(MSTR|STRC|STRF|STRK|STRD|STRE) Stock(?: \(\d+\))?$/);
        if (!match) continue;
        const parsed = values(cells.slice(1));
        if (parsed.length !== (hasNotional ? 4 : 3)) { e.issues.push(`${match[1]} issuance columns changed`); continue; }
        const prior = e.securities[match[1]] ?? {};
        e.securities[match[1]] = { ...prior, issuedShares: parsed[0], netIssuanceProceedsUsd: parsed[hasNotional ? 2 : 1] * 1_000_000 };
      }
    }
    if (/Shares Repurchased/i.test(table.text) && /Aggregate Purchase Price\s*\(in millions\)/i.test(table.text)) {
      for (const row of table.rows) {
        const cells = row.filter(Boolean);
        const match = cells[0]?.match(/^(MSTR|STRC|STRF|STRK|STRD|STRE) Stock(?: \(\d+\))?$/);
        if (!match) continue;
        const parsed = values(cells.slice(1));
        if (parsed.length !== 2) { e.issues.push(`${match[1]} repurchase columns changed`); continue; }
        e.securities[match[1]] = { ...e.securities[match[1]], repurchasedShares: parsed[0], repurchaseCashUsd: parsed[1] * 1_000_000 };
      }
    }
    if (/BTC Purchased/i.test(table.text) && /Aggregate BTC Holdings/i.test(table.text)) {
      const rows = table.rows.map(values).filter(row => row.length === 6);
      if (rows.length !== 1) e.issues.push("Strategy BTC table has unexpected numeric rows");
      else { put(e.facts, "weekly_btc_purchases", rows[0][0], e.issues); put(e.facts, "btc_holdings", rows[0][3], e.issues); }
    }
  }
  const cash = text.match(/balances of the USD Reserve and USD Cash were \$([\d,.]+) billion and \$([\d,.]+) billion, respectively/i);
  if (cash) { e.facts.usd_reserve_usd = Number(cash[1].replaceAll(",", "")) * 1e9; e.facts.usd_cash_usd = Number(cash[2].replaceAll(",", "")) * 1e9; }
  const common = e.securities.MSTR;
  if (common?.issuedShares !== undefined) e.facts.common_issued_shares = common.issuedShares;
  if (common?.netIssuanceProceedsUsd !== undefined) e.facts.common_issuance_proceeds_usd = common.netIssuanceProceedsUsd;
  if (common?.repurchasedShares !== undefined) e.facts.common_repurchased_shares = common.repurchasedShares;
  if (common?.repurchaseCashUsd !== undefined) e.facts.common_repurchases_cash_usd = common.repurchaseCashUsd;
  for (const [security, activity] of Object.entries(e.securities)) {
    for (const value of Object.values(activity)) if (!Number.isFinite(value) || value < 0) e.issues.push(`Invalid ${security} activity`);
    if (activity.issuedShares === 0 && activity.netIssuanceProceedsUsd !== 0) e.issues.push(`${security} issuance cash with zero shares`);
    if (activity.repurchasedShares === 0 && activity.repurchaseCashUsd !== 0) e.issues.push(`${security} repurchase cash with zero shares`);
  }
  return validate(e, ["btc_holdings", "weekly_btc_purchases", "common_issued_shares", "common_issuance_proceeds_usd"]);
}
