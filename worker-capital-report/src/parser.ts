import { load } from "cheerio/slim";
import type { Extraction, Facts, Ticker } from "./types";

export const PARSER_VERSION = "sec-weekly-v5";
const MONTH = "(?:January|February|March|April|May|June|July|August|September|October|November|December)";
const DATE = `${MONTH}\\s+\\d{1,2},\\s+\\d{4}`;
const compact = (text: string): string => text.replace(/[\u00a0\u200b]/g, " ").replace(/\s+/g, " ").trim();
function isoDate(text: string): string | null {
  const stamp = Date.parse(`${text} 12:00:00 UTC`);
  return Number.isFinite(stamp) ? new Date(stamp).toISOString().slice(0, 10) : null;
}
interface Period { start: string; end: string }
const periodKey = (period: Period): string => `${period.start}/${period.end}`;
const nextDay = (iso: string): string => new Date(Date.parse(`${iso}T12:00:00Z`) + 86_400_000).toISOString().slice(0, 10);
function periodsIn(text: string): Period[] {
  const found = new Map<string, Period>();
  for (const match of text.matchAll(new RegExp(`(?:During Period|period from|period between)\\s+(${DATE})\\s+(?:to|through|and)\\s+(${DATE})`, "gi"))) {
    const start = isoDate(match[1]), end = isoDate(match[2]);
    if (start && end) found.set(`${start}/${end}`, { start, end });
  }
  return [...found.values()];
}
/**
 * A quarter-end week is reported in consecutive parts (Sep 28\u201330 and Oct 1\u20134, 2026), each with its own tables,
 * sometimes alongside a sentence covering the whole week. The parts must join day to day with no gap or overlap.
 * Returns the whole week and its parts (none for an ordinary week), or null when the periods do not fit together.
 */
function resolvePeriods(found: Period[]): { week: Period; parts: Period[] } | null {
  if (!found.length) return null;
  const week = { start: found.map(p => p.start).sort()[0], end: found.map(p => p.end).sort().at(-1)! };
  const parts = found.filter(p => periodKey(p) !== periodKey(week)).sort((a, b) => a.start.localeCompare(b.start));
  if (!parts.length) return { week, parts };
  if (parts.length > 3 || Date.parse(week.end) - Date.parse(week.start) > 9 * 86_400_000) return null;
  let cursor = week.start;
  for (const part of parts) {
    if (part.start !== cursor || part.end < part.start) return null;
    cursor = nextDay(part.end);
  }
  return cursor === nextDay(week.end) ? { week, parts } : null;
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
function htmlTables(html: string): { text: string; tables: Table[]; paragraphs: string[] } {
  const $ = load(html);
  $("script,style,ix\\:hidden,header").remove();
  const tables = $("table").toArray().map(table => {
    const rows = $(table).find("tr").toArray()
      .filter(row => $(row).closest("table")[0] === table)
      .map(row => $(row).children("td,th").toArray().map(cell => compact($(cell).text())));
    return { text: `${compact($(table).find("caption").text())} ${rows.flat().join(" ")}`, rows };
  });
  const paragraphs = $("p,div,li").toArray().filter(element => !$(element).closest("table").length)
    .map(element => { const copy = $(element).clone(); copy.find("p,div,li,table").remove(); return compact(copy.text()); }).filter(Boolean);
  return { text: compact($.root().text()), tables, paragraphs };
}
function put(facts: Facts, key: string, value: number, issues: string[]): void {
  if (key in facts && facts[key] !== value) issues.push(`Conflicting ${key} values`);
  else facts[key] = value;
}
function validate(extraction: Extraction, required: string[]): Extraction {
  extraction.missing = required.filter(key => !(key in extraction.facts));
  if (!("weekly_btc_purchases" in extraction.facts) && !("weekly_btc_sales" in extraction.facts)) extraction.missing.push("weekly_btc_activity");
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
type BitcoinKey = "weekly_btc_purchases" | "weekly_btc_sales" | "btc_holdings";
function bitcoinQuantity(text: string): number | null {
  const value = compact(text).replace(/\s+\(\d+\)$/, "");
  if (/^(?:[-—–]|no)$/i.test(value)) return 0;
  if (!/^(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$/.test(value)) return null;
  const result = Number(value.replaceAll(",", ""));
  return Number.isFinite(result) ? result : null;
}
function bitcoinHeader(text: string): BitcoinKey | null {
  const label = compact(text).replace(/\s+\(\d+\)$/, "");
  if (/^(?:Weekly )?(?:BTC|Bitcoins?) (?:Purchased|Bought|Acquired)(?: During (?:the )?(?:Week|Period))?$/i.test(label)) return "weekly_btc_purchases";
  if (/^(?:Weekly )?(?:BTC|Bitcoins?) (?:Sold|Sales)(?: During (?:the )?(?:Week|Period))?$/i.test(label)) return "weekly_btc_sales";
  if (/^(?:(?:Aggregate|Total|Ending) )?(?:BTC|Bitcoin) (?:Holdings|Held)$/i.test(label)) return "btc_holdings";
  return null;
}
function putBitcoin(e: Extraction, key: BitcoinKey, text: string, facts: Facts = e.facts): void {
  const value = bitcoinQuantity(text);
  if (value === null) e.issues.push(`Invalid ${key} quantity`);
  else put(facts, key, value, e.issues);
}
/** SEC HTML often splits a price into a dollar-symbol cell and a number cell. */
function joinDollars(row: string[]): string[] {
  const cells: string[] = [];
  for (let column = 0; column < row.length; column++) {
    if (row[column] === "$" && column + 1 < row.length) cells.push(`$${row[++column]}`);
    else cells.push(row[column]);
  }
  return cells;
}
const BTC_FLOWS = ["weekly_btc_purchases", "weekly_btc_sales", "weekly_btc_cost_usd"];
const BTC_BALANCES = ["btc_holdings", "btc_cost_basis_usd", "btc_average_cost_usd"];
/** Quantity columns are identified by their labels, never by nearby dollar proceeds or balance changes. */
function bitcoinTables(e: Extraction, tables: Table[], parts: Period[]): void {
  if (!e.periodStart || !e.periodEnd) return;
  // A week reported in parts collects each part's figures separately, then adds up the flows below.
  const byPart = new Map<string, Facts>(parts.map(part => [periodKey(part), {}]));
  for (const table of tables) {
    if (/cumulative|year.to.date|quarter.to.date|since inception|lifetime/i.test(table.text)) continue;
    const rows = table.rows.map(row => row.filter(Boolean));
    if (!/During Period|period from|weekly|during (?:the )?(?:week|period)/i.test(table.text)) {
      // A separate "As of <date>" holdings table counts only on the balance date, never an earlier part's end.
      const asOf = [...table.text.matchAll(new RegExp(`As of\\s+(${DATE})`, "gi"))].map(match => isoDate(match[1]));
      if (asOf.length === 1 && asOf[0] === e.balanceDate) holdingsTable(e, rows);
      continue;
    }
    const own = periodsIn(table.text);
    let facts = e.facts;
    if (parts.length) {
      const part = own.length === 1 ? byPart.get(periodKey(own[0])) : undefined;
      if (part) facts = part;
      else if (!(own.length === 1 && own[0].start === e.periodStart && own[0].end === e.periodEnd)) {
        e.issues.push("BTC activity: table period does not match the reporting periods"); continue;
      }
    }
    for (let index = 0; index < rows.length; index++) {
      const headers = rows[index], keys = headers.map(bitcoinHeader);
      if (!keys.some(key => key === "weekly_btc_purchases" || key === "weekly_btc_sales")) continue;
      // A narrow, explicit label/value table can state each gross activity separately.
      const numericRowBelow = rows.slice(index + 1).some(row => row.length >= 2 && row.every(cell => numeric(cell) !== null || cell === "$"));
      if (headers.length === 2 && keys[0] && keys[1] === null && !numericRowBelow) {
        putBitcoin(e, keys[0], headers[1], facts); continue;
      }
      const data = rows.slice(index + 1).filter(row => row.some(cell => numeric(cell) !== null));
      if (data.length !== 1) { e.issues.push("BTC activity: table has unexpected data rows"); continue; }
      const cells = joinDollars(data[0]);
      if (cells.length !== headers.length) { e.issues.push("BTC activity: quantity columns changed"); continue; }
      keys.forEach((key, column) => { if (key) putBitcoin(e, key, cells[column], facts); });
      // The period's cost is the "Aggregate Purchase Price" column right after the purchased quantity.
      const bought = keys.indexOf("weekly_btc_purchases");
      const cost = bought >= 0 ? compact(headers[bought + 1] ?? "").replace(/\s+\(\d+\)$/, "")
        .match(/^Aggregate\s*Purchase\s*Price\s*\(in (millions|billions)\)$/i) : null;
      if (cost) {
        const amount = numeric(cells[bought + 1]);
        if (amount === null) e.issues.push("Invalid weekly_btc_cost_usd");
        else put(facts, "weekly_btc_cost_usd", Math.round(amount * (cost[1].toLowerCase() === "billions" ? 1e9 : 1e6)), e.issues);
      }
      costBasis(e, headers, keys, cells, facts);
    }
    // A row table may also disclose ending holdings, without implying that its change was a trade.
    for (const row of rows) if (row.length === 2 && bitcoinHeader(row[0]) === "btc_holdings") putBitcoin(e, "btc_holdings", row[1], facts);
  }
  if (!parts.length) return;
  const facts = parts.map(part => byPart.get(periodKey(part))!);
  for (const key of BTC_FLOWS) {
    const stated = facts.filter(part => key in part);
    if (!stated.length) continue;
    if (stated.length !== facts.length) { e.issues.push(`BTC activity: ${key} missing for part of the reporting period`); continue; }
    put(e.facts, key, stated.reduce((sum, part) => sum + part[key], 0), e.issues);
  }
  // Holdings are the last part's, which ends on the balance date.
  for (const key of BTC_BALANCES) if (key in facts.at(-1)!) put(e.facts, key, facts.at(-1)![key], e.issues);
}
/** Holdings are followed by their total and average cost ("Aggregate Purchase Price", "Average Purchase Price"). */
function costBasis(e: Extraction, headers: string[], keys: (BitcoinKey | null)[], cells: string[], facts: Facts): void {
  const held = keys.indexOf("btc_holdings");
  const label = (column: number): string => compact(headers[column] ?? "").replace(/\s+\(\d+\)$/, "");
  const basis = held >= 0 ? label(held + 1).match(/^Aggregate\s*Purchase\s*Price\s*\(in (millions|billions)\)$/i) : null;
  if (basis && /^Average\s*Purchase\s*Price$/i.test(label(held + 2))) putCostBasis(e, cells[held + 1], basis[1], cells[held + 2], facts);
}
/** "Aggregate BTC Holdings | Aggregate Purchase Price | Average Purchase Price" over one data row. */
function holdingsTable(e: Extraction, rows: string[][]): void {
  const index = rows.findIndex(row => row.some(cell => bitcoinHeader(cell) === "btc_holdings") && row.every(cell => numeric(cell) === null));
  if (index < 0) return;
  const headers = rows[index], keys = headers.map(bitcoinHeader);
  if (keys.some(key => key === "weekly_btc_purchases" || key === "weekly_btc_sales")) return;
  const data = rows.slice(index + 1).filter(row => row.some(cell => numeric(cell) !== null));
  if (data.length !== 1) { e.issues.push("BTC holdings: table has unexpected data rows"); return; }
  const cells = joinDollars(data[0]);
  if (cells.length !== headers.length) { e.issues.push("BTC holdings: columns changed"); return; }
  putBitcoin(e, "btc_holdings", cells[keys.indexOf("btc_holdings")]);
  costBasis(e, headers, keys, cells, e.facts);
}
function putCostBasis(e: Extraction, total: string, unit: string, average: string, facts: Facts = e.facts): void {
  const amount = numeric(total), each = numeric(average);
  if (amount === null || each === null) { e.issues.push("Invalid BTC cost basis"); return; }
  put(facts, "btc_cost_basis_usd", Math.round(amount * (/^billions?$/i.test(unit) ? 1e9 : 1e6)), e.issues);
  put(facts, "btc_average_cost_usd", each, e.issues);
}
function bitcoinProse(e: Extraction, paragraphs: string[], ticker: Ticker): void {
  if (!e.periodStart || !e.periodEnd) return;
  const issuer = ticker === "MSTR" ? "(?:Strategy|MicroStrategy|the Company)" : "(?:Strive|the Company)";
  for (const paragraph of paragraphs) {
    const holding = paragraph.match(new RegExp(`As of\\s+(${DATE}),?\\s+${issuer}\\s+(?:held|holds)\\s+(?:approximately\\s+)?([^\\s]+)\\s+(?:bitcoins?|BTC)\\b`, "i"));
    if (holding && isoDate(holding[1]) === e.balanceDate) putBitcoin(e, "btc_holdings", holding[2]);
    const basis = paragraph.match(new RegExp(`As of\\s+(${DATE}),?\\s+${issuer}\\s+(?:held|holds)\\s+(?:approximately\\s+)?[^\\s]+\\s+(?:bitcoins?|BTC)\\s+that were acquired at an aggregate purchase price of \\$([\\d,.]+)\\s+(billion|million) and an average purchase price of (?:approximately\\s+)?\\$([\\d,.]+)`, "i"));
    if (basis && isoDate(basis[1]) === e.balanceDate) putCostBasis(e, basis[2], basis[3], basis[4]);
    const weekly = /\bduring (?:the )?(?:reporting )?(?:period|week)\b|\bfor the week ended\b/i.test(paragraph);
    // Historical/cumulative and prospective statements are not this week's gross trades.
    if (!weekly || /since inception|year.to.date|quarter.to.date|cumulative|historically|intends? to|plans? to|expects? to/i.test(paragraph)) continue;
    const noTrades = new RegExp(`\\b${issuer}\\s+(?:did not sell any shares under its at-the-market offering program and\\s+)?did not (?:purchase|buy|acquire) or sell any (?:bitcoins?|BTC)\\b`, "i");
    if (noTrades.test(paragraph)) {
      put(e.facts, "weekly_btc_purchases", 0, e.issues);
      put(e.facts, "weekly_btc_sales", 0, e.issues);
    }
    const statement = new RegExp(`\\b${issuer}\\s+(?:has\\s+)?(sold|purchased|bought|acquired)\\s+(?:(?:an aggregate|a total) of\\s+)?(?:approximately\\s+)?([^\\s]+)\\s+(?:bitcoins?|BTC)\\b`, "gi");
    for (const match of paragraph.matchAll(statement)) {
      putBitcoin(e, match[1].toLowerCase() === "sold" ? "weekly_btc_sales" : "weekly_btc_purchases", match[2]);
      const coordinated = paragraph.slice((match.index ?? 0) + match[0].length).match(/^\s*(?:,?\s+and)(?:\s+(?:then|subsequently))?\s+(sold|purchased|bought|acquired)\s+(?:approximately\s+)?([^\s]+)\s+(?:bitcoins?|BTC)\b/i);
      if (coordinated) putBitcoin(e, coordinated[1].toLowerCase() === "sold" ? "weekly_btc_sales" : "weekly_btc_purchases", coordinated[2]);
    }
  }
}
export function extractWeekly(html: string, ticker: Ticker): Extraction {
  const { text, tables, paragraphs } = htmlTables(html);
  const e: Extraction = { parserVersion: PARSER_VERSION, periodStart: null, periodEnd: null,
    priorBalanceDate: null, balanceDate: null, facts: {}, priorFacts: {}, securities: {},
    missing: [], issues: [], extractionValidated: false };
  const found = periodsIn(text), resolved = resolvePeriods(found), parts = resolved?.parts ?? [];
  if (resolved) {
    e.periodStart = resolved.week.start; e.periodEnd = resolved.week.end; e.balanceDate = e.periodEnd;
  } else if (found.length) {
    e.periodStart = found[0].start; e.periodEnd = found[0].end; e.balanceDate = e.periodEnd;
    e.issues.push("Multiple reporting periods require review");
  }
  bitcoinTables(e, tables, parts);
  bitcoinProse(e, paragraphs, ticker);
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
    for (const facts of [e.facts, e.priorFacts]) {
      if (["common_shares_class_a", "common_shares_class_b", "effective_common_shares"].every(key => key in facts)
          && facts.common_shares_class_a + facts.common_shares_class_b !== facts.effective_common_shares)
        e.issues.push("Strive common share classes do not reconcile");
      if (["effective_common_shares", "options", "unvested_employee_awards", "assumed_diluted_shares"].every(key => key in facts)
          && facts.effective_common_shares + facts.options + facts.unvested_employee_awards !== facts.assumed_diluted_shares)
        e.issues.push("Strive assumed diluted shares do not reconcile");
    }
    return validate(e, ["btc_holdings", "cash_and_equivalents_usd", "held_strc_shares",
      "effective_common_shares", "sata_shares", "net_common_shares_change", "net_sata_shares_change"]);
  }
  // A week reported in parts has one issuance and one repurchase table per part; their activity adds up.
  const seen = { issuance: new Set<string>(), repurchase: new Set<string>() };
  const tablePart = (table: Table, kind: keyof typeof seen): boolean => {
    if (!parts.length) return true;
    const own = periodsIn(table.text);
    const key = own.length === 1 ? periodKey(own[0]) : "";
    if (!parts.some(part => periodKey(part) === key) || seen[kind].has(key)) {
      e.issues.push(`${kind === "issuance" ? "Issuance" : "Repurchase"} table period does not match the reporting periods`); return false;
    }
    seen[kind].add(key); return true;
  };
  const add = (previous: number | undefined, value: number): number => parts.length ? Math.round((previous ?? 0) + value) : value;
  for (const table of tables) {
    if (/Shares Sold/i.test(table.text) && /Net Proceeds\s*\(in millions\)/i.test(table.text) && tablePart(table, "issuance")) {
      const hasNotional = /Notional Value/i.test(table.text);
      for (const row of table.rows) {
        const cells = row.filter(Boolean);
        const match = cells[0]?.match(/^(MSTR|STRC|STRF|STRK|STRD|STRE) Stock(?: \(\d+\))?$/);
        if (!match) continue;
        const parsed = values(cells.slice(1));
        if (parsed.length !== (hasNotional ? 4 : 3)) { e.issues.push(`${match[1]} issuance columns changed`); continue; }
        const prior = e.securities[match[1]] ?? {};
        e.securities[match[1]] = { ...prior, issuedShares: add(prior.issuedShares, parsed[0]),
          netIssuanceProceedsUsd: add(prior.netIssuanceProceedsUsd, parsed[hasNotional ? 2 : 1] * 1_000_000) };
      }
    }
    if (/Shares Repurchased/i.test(table.text) && /Aggregate Purchase Price\s*\(in millions\)/i.test(table.text) && tablePart(table, "repurchase")) {
      for (const row of table.rows) {
        const cells = row.filter(Boolean);
        const match = cells[0]?.match(/^(MSTR|STRC|STRF|STRK|STRD|STRE) Stock(?: \(\d+\))?$/);
        if (!match) continue;
        const parsed = values(cells.slice(1));
        if (parsed.length !== 2) { e.issues.push(`${match[1]} repurchase columns changed`); continue; }
        const prior = e.securities[match[1]] ?? {};
        e.securities[match[1]] = { ...prior, repurchasedShares: add(prior.repurchasedShares, parsed[0]),
          repurchaseCashUsd: add(prior.repurchaseCashUsd, parsed[1] * 1_000_000) };
      }
    }
  }
  for (const kind of ["issuance", "repurchase"] as const)
    if (parts.length && seen[kind].size && seen[kind].size !== parts.length) e.issues.push(`${kind === "issuance" ? "Issuance" : "Repurchase"} table missing for part of the reporting period`);
  // Balances are stated in billions or, as USD Cash was on Oct 5, 2026, in millions.
  const scale = (unit: string): number => unit.toLowerCase() === "billion" ? 1e9 : 1e6;
  const cash = text.match(/balances of the USD Reserve and USD Cash were \$([\d,.]+) (billion|million) and \$([\d,.]+) (billion|million), respectively/i);
  if (cash) {
    e.facts.usd_reserve_usd = Math.round(Number(cash[1].replaceAll(",", "")) * scale(cash[2]));
    e.facts.usd_cash_usd = Math.round(Number(cash[3].replaceAll(",", "")) * scale(cash[4]));
  }
  const obligations = text.match(/Strategy used \$([\d,.]+) (million|billion) of the USD Reserve to fund (?:the payment of )?dividends/i);
  if (obligations) e.facts.usd_reserve_dividends_interest_usd = Math.round(Number(obligations[1].replaceAll(",", "")) * (obligations[2].toLowerCase() === "billion" ? 1e9 : 1e6));
  const noAtm = e.periodStart && e.periodEnd && paragraphs.some(paragraph =>
    /\bduring (?:the )?(?:reporting )?period\b/i.test(paragraph)
    && !/since inception|year.to.date|quarter.to.date|cumulative|historically|intends? to|plans? to|expects? to/i.test(paragraph)
    && /\b(?:Strategy|MicroStrategy|the Company) did not sell any shares under its at-the-market offering program\b/i.test(paragraph));
  if (noAtm) {
    // This explicit statement covers the issuer's ATM, including the securities reported in its activity tables.
    for (const security of new Set(["MSTR", ...Object.keys(e.securities)])) {
      const activity = e.securities[security] ?? {};
      if ((activity.issuedShares ?? 0) !== 0 || (activity.netIssuanceProceedsUsd ?? 0) !== 0) e.issues.push(`Conflicting ${security} no-issuance statement`);
      else e.securities[security] = { ...activity, issuedShares: 0, netIssuanceProceedsUsd: 0 };
    }
  }
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
  return validate(e, ["btc_holdings", "common_issued_shares", "common_issuance_proceeds_usd"]);
}
