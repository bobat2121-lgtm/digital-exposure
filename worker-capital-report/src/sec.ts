import { ISSUERS, type Filing, type Ticker } from "./types";
export const MAX_SUBMISSIONS_BYTES = 4 * 1024 * 1024;
export const MAX_DOCUMENT_BYTES = 8 * 1024 * 1024;
export class SecError extends Error {
  constructor(message: string, public status: number | null = null, public retryAfter: string | null = null) { super(message); }
}
export function validUserAgent(value: string | undefined): boolean {
  return !!value && value.length <= 200 && /^[\x20-\x7e]+$/.test(value)
    && /\S+@[^\s@]+\.[^\s@]+/.test(value) && !/example\.(com|org)|placeholder|your[-_ ]?(email|company)/i.test(value);
}
export function documentUrl(ticker: Ticker, accession: string, primary: string): string {
  if (!/^\d{10}-\d{2}-\d{6}$/.test(accession) || !/^[a-zA-Z0-9_.-]+\.(htm|html|txt)$/i.test(primary) || primary.includes(".."))
    throw new Error("Unsafe filing accession or primary document path");
  return `https://www.sec.gov/Archives/edgar/data/${Number(ISSUERS[ticker].cik)}/${accession.replaceAll("-", "")}/${primary}`;
}
export function allowedSecUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && !parsed.username && !parsed.password && !parsed.search && !parsed.hash
      && ((parsed.hostname === "data.sec.gov" && /^\/submissions\/CIK000(1050446|1920406)\.json$/.test(parsed.pathname))
        || (parsed.hostname === "www.sec.gov" && /^\/Archives\/edgar\/data\/(1050446|1920406)\/\d{18}\/[a-zA-Z0-9_.-]+\.(html?|txt)$/.test(parsed.pathname)));
  } catch { return false; }
}
export async function boundedText(response: Response, limit: number): Promise<string> {
  if (Number(response.headers.get("Content-Length")) > limit) throw new SecError("Response exceeds size limit");
  if (!response.body) throw new SecError("Empty response body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let size = 0, text = "";
  try {
    for (;;) {
      const result = await reader.read();
      if (result.done) break;
      size += result.value.byteLength;
      if (size > limit) { await reader.cancel(); throw new SecError("Response exceeds size limit"); }
      text += decoder.decode(result.value, { stream: true });
    }
    return text + decoder.decode();
  } finally { reader.releaseLock(); }
}
export async function fetchSec(url: string, userAgent: string, limit: number, conditional: Record<string, string> = {}): Promise<{ text: string | null; etag: string | null; lastModified: string | null }> {
  if (!allowedSecUrl(url) || !validUserAgent(userAgent)) throw new SecError("SEC request configuration invalid");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(url, { headers: { "User-Agent": userAgent, "Accept": "application/json,text/html;q=0.9", ...conditional },
      redirect: "manual", signal: controller.signal });
    if (response.status === 304) return { text: null, etag: response.headers.get("ETag"), lastModified: response.headers.get("Last-Modified") };
    if (!response.ok) { await response.body?.cancel(); throw new SecError(`SEC HTTP ${response.status}`, response.status, response.headers.get("Retry-After")); }
    const text = await boundedText(response, limit);
    if (/request rate threshold exceeded|undeclared automated tool|access denied/i.test(text.slice(0, 12000)))
      throw new SecError("SEC access policy response", 403);
    return { text, etag: response.headers.get("ETag"), lastModified: response.headers.get("Last-Modified") };
  } catch (error) {
    if (error instanceof SecError) throw error;
    throw new SecError(error instanceof Error && error.name === "AbortError" ? "SEC request timeout" : "SEC network request failed");
  } finally { clearTimeout(timeout); }
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new SecError("Malformed SEC submissions");
  return value as Record<string, unknown>;
}
export function parseSubmissions(text: string, ticker: Ticker, now: number, baseline: boolean): Filing[] {
  const root = object(JSON.parse(text));
  if (Number(root.cik) !== Number(ISSUERS[ticker].cik)) throw new SecError("SEC issuer CIK mismatch");
  const recent = object(object(root.filings).recent);
  const columns = ["accessionNumber", "form", "filingDate", "reportDate", "acceptanceDateTime", "primaryDocument"];
  const values = Object.fromEntries(columns.map(name => {
    if (!Array.isArray(recent[name])) throw new SecError(`Missing SEC ${name} column`);
    return [name, recent[name] as unknown[]];
  }));
  const count = values.form.length;
  if (count > 3000 || columns.some(name => values[name].length !== count)) throw new SecError("SEC submissions column length mismatch");
  const result: Filing[] = [];
  for (let i = 0; i < count; i++) {
    const form = values.form[i];
    if (form !== "8-K" && form !== "8-K/A") continue;
    if (columns.some(name => typeof values[name][i] !== "string")) throw new SecError("Invalid SEC filing metadata");
    const accession = String(values.accessionNumber[i]);
    const accepted = String(values.acceptanceDateTime[i]);
    if (!/(Z|[+-]\d{2}:\d{2})$/.test(accepted) || !Number.isFinite(Date.parse(accepted))) throw new SecError("SEC acceptance timestamp has no valid timezone");
    const filed = String(values.filingDate[i]);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(filed)) throw new SecError("Invalid SEC filing date");
    const primaryDocumentUrl = documentUrl(ticker, accession, String(values.primaryDocument[i]));
    result.push({ ...ISSUERS[ticker], accession, form, filedDate: filed, reportDate: String(values.reportDate[i]) || null,
      acceptedAt: new Date(accepted).toISOString(), firstSeenAt: new Date(now).toISOString(), documentFetchedAt: null,
      primaryDocumentUrl, documents: [], status: "pending", baseline, extracted: null, attempts: 0, nextDocumentAttemptAt: 0, error: null });
  }
  return result.sort((a, b) => b.acceptedAt.localeCompare(a.acceptedAt));
}
