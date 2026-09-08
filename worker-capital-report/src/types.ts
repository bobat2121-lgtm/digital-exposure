export const ISSUERS = {
  MSTR: { ticker: "MSTR", issuer: "Strategy", cik: "0001050446" },
  ASST: { ticker: "ASST", issuer: "Strive", cik: "0001920406" },
} as const;
export type Ticker = keyof typeof ISSUERS;
export type Issuer = typeof ISSUERS[Ticker];
/** Explicit gross BTC quantities. Missing is unknown; sales are never inferred from a holdings decline. */
export interface BitcoinActivity {
  weekly_btc_purchases?: number;
  weekly_btc_sales?: number;
}
export type Facts = Record<string, number> & BitcoinActivity;
export interface SecurityActivity {
  issuedShares?: number;
  netIssuanceProceedsUsd?: number;
  repurchasedShares?: number;
  repurchaseCashUsd?: number;
}
export interface Extraction {
  parserVersion: string;
  periodStart: string | null;
  periodEnd: string | null;
  priorBalanceDate: string | null;
  balanceDate: string | null;
  facts: Facts;
  priorFacts: Facts;
  securities: Record<string, SecurityActivity>;
  missing: string[];
  issues: string[];
  extractionValidated: boolean;
}
export interface Filing {
  issuer: string;
  ticker: Ticker;
  cik: string;
  accession: string;
  form: "8-K" | "8-K/A";
  filedDate: string;
  reportDate: string | null;
  acceptedAt: string;
  firstSeenAt: string;
  documentFetchedAt: string | null;
  primaryDocumentUrl: string;
  documents: { url: string; fetchedAt: string; sha256: string }[];
  status: "baseline" | "pending" | "ready_for_review" | "partial" | "not_weekly" | "document_error";
  baseline: boolean;
  extracted: Extraction | null;
  attempts: number;
  nextDocumentAttemptAt: number;
  error: string | null;
}
export interface PollState {
  ticker: Ticker;
  initializedAt: string | null;
  lastAttemptAt: string | null;
  lastSuccessAt: string | null;
  lastDiscoveryAt: string | null;
  backoffUntil: number;
  failures: number;
  error: string | null;
  pollCount: number;
  etag: string | null;
  lastModified: string | null;
}
export function initialState(ticker: Ticker): PollState {
  return { ticker, initializedAt: null, lastAttemptAt: null, lastSuccessAt: null,
    lastDiscoveryAt: null, backoffUntil: 0, failures: 0, error: null,
    pollCount: 0, etag: null, lastModified: null };
}
