import { documentUrl } from "./sec";
import { ISSUERS, type Filing, type Ticker } from "./types";
const DAY = 86_400_000;
export interface ReceiptKey { ticker: Ticker; accession: string; sha256: string }
export interface NotificationFiling extends ReceiptKey { url: string }
export interface PublicationEvent { week: string; filing: NotificationFiling }
export function awareTime(value: string | null | undefined): number {
  return typeof value === "string" && /(Z|[+-]\d{2}:\d{2})$/.test(value) ? Date.parse(value) : NaN;
}
export function easternDay(time: number): { date: string; weekday: string } {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", weekday: "short" }).formatToParts(time);
  const value = (key: string) => parts.find(part => part.type === key)?.value ?? "";
  return { date: `${value("year")}-${value("month")}-${value("day")}`, weekday: value("weekday") };
}
export function recentMondays(now: number): string[] {
  return Array.from({ length: 15 }, (_, i) => easternDay(now - i * DAY)).filter(day => day.weekday === "Mon").map(day => day.date);
}
/** Checks the persisted SEC receipt, never caller-provided URLs or extracted numbers. */
export function validateReceipt(filing: Filing | null, ack: ReceiptKey, now: number): { week: string; filing: NotificationFiling } | null {
  if (!filing || filing.baseline !== false || filing.form !== "8-K" || filing.ticker !== ack.ticker || filing.accession !== ack.accession
    || filing.cik !== ISSUERS[ack.ticker].cik || !["ready_for_review", "partial"].includes(filing.status)) return null;
  const accepted = awareTime(filing.acceptedAt), fetched = awareTime(filing.documentFetchedAt);
  if (!Number.isFinite(accepted) || !Number.isFinite(fetched) || accepted > now || fetched > now || fetched < accepted || now - accepted > 14 * DAY) return null;
  const day = easternDay(accepted);
  if (day.weekday !== "Mon") return null;
  const facts = filing.extracted?.facts;
  if (!facts || !Number.isFinite(facts.btc_holdings) || facts.btc_holdings <= 0
    || !Number.isFinite(facts.weekly_btc_purchases) || facts.weekly_btc_purchases < 0) return null;
  const receipt = filing.documents[0];
  if (!receipt || receipt.sha256 !== ack.sha256 || receipt.url !== filing.primaryDocumentUrl || awareTime(receipt.fetchedAt) !== fetched) return null;
  try {
    const primary = new URL(filing.primaryDocumentUrl).pathname.split("/").pop() ?? "";
    if (filing.primaryDocumentUrl !== documentUrl(ack.ticker, ack.accession, primary)) return null;
  } catch { return null; }
  return { week: day.date, filing: { ...ack, url: filing.primaryDocumentUrl } };
}

/** Same bounded projection for the public API and internal publication checks. */
export async function publishedFeed(env: Env) {
  const records = (await Promise.all((["MSTR", "ASST"] as const).map(ticker => env.ISSUER_POLLER.getByName(ticker).filings(100)))).flat();
  return { schemaVersion: 1, generatedAt: new Date().toISOString(), publicationMode: "reported_facts_for_review",
    filings: records.sort((a, b) => b.acceptedAt.localeCompare(a.acceptedAt)).slice(0, 100) };
}
export function eligiblePublication(filing: Filing, now: number, activation: string): PublicationEvent | null {
  const activeAfter = awareTime(activation), seen = awareTime(filing.firstSeenAt), fetched = awareTime(filing.documentFetchedAt);
  if (!Number.isFinite(activeAfter) || activeAfter > now || !Number.isFinite(seen) || seen < activeAfter || seen > now || fetched < activeAfter) return null;
  const hash = filing.documents[0]?.sha256;
  if (!hash || !/^[a-f0-9]{64}$/.test(hash)) return null;
  return validateReceipt(filing, { ticker: filing.ticker, accession: filing.accession, sha256: hash }, now);
}
export function verifyPublishedPair(records: Filing[], candidates: NotificationFiling[], week: string, now: number, activation: string): NotificationFiling[] | null {
  const pair: NotificationFiling[] = [];
  for (const ticker of ["MSTR", "ASST"] as const) {
    const matches = records.filter(f => f.ticker === ticker).sort((a, b) => b.acceptedAt.localeCompare(a.acceptedAt));
    let chosen: NotificationFiling | null = null;
    for (const filing of matches) {
      const event = eligiblePublication(filing, now, activation);
      if (event?.week === week && candidates.some(c => c.ticker === ticker && c.accession === event.filing.accession && c.sha256 === event.filing.sha256 && c.url === event.filing.url)) {
        chosen = event.filing; break;
      }
    }
    if (!chosen) return null;
    pair.push(chosen);
  }
  return pair;
}
