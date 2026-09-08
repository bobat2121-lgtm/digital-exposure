import { describe, expect, it } from "vitest";
import { extractWeekly } from "../src/parser";
import strategy from "./fixtures/strategy-20260831.html?raw";
import strive from "./fixtures/strive-20260831.html?raw";
import strategyHoliday from "./fixtures/strategy-20260908.html?raw";
import striveHoliday from "./fixtures/strive-20260908.html?raw";
describe("actual SEC weekly HTML fixtures", () => {
  it("extracts Strategy's holiday zero-ATM and zero-BTC disclosure with approximate ending holdings", () => {
    const result = extractWeekly(strategyHoliday, "MSTR");
    expect(result.issues).toEqual([]); expect(result.missing).toEqual([]); expect(result.extractionValidated).toBe(true);
    expect(result.periodStart).toBe("2026-08-31"); expect(result.balanceDate).toBe("2026-09-07");
    expect(result.facts).toMatchObject({ btc_holdings: 845050, weekly_btc_purchases: 0, weekly_btc_sales: 0,
      common_issued_shares: 0, common_issuance_proceeds_usd: 0, usd_reserve_usd: 5100000000, usd_cash_usd: 1440000000 });
    for (const ticker of ["MSTR", "STRC", "STRF", "STRK", "STRD"]) expect(result.securities[ticker]).toMatchObject({ issuedShares: 0, netIssuanceProceedsUsd: 0 });
    expect(result.securities.STRC).toMatchObject({ repurchasedShares: 1810885, repurchaseCashUsd: 176300000 });
    expect(result.facts).not.toHaveProperty("effective_common_shares");
  });
  it("extracts Strive's actual holiday report and keeps both dated balances reconciled", () => {
    const result = extractWeekly(striveHoliday, "ASST");
    expect(result.issues).toEqual([]); expect(result.missing).toEqual([]); expect(result.extractionValidated).toBe(true);
    expect(result.priorBalanceDate).toBe("2026-08-28"); expect(result.balanceDate).toBe("2026-09-04");
    expect(result.facts).toMatchObject({ btc_holdings: 24531, weekly_btc_purchases: 1375 });
    expect(result.priorFacts).toMatchObject({ btc_holdings: 23156, effective_common_shares: 93262570 });
    expect(result.facts).not.toHaveProperty("weekly_btc_sales");
  });
  it("extracts Strategy holdings and both issuance and repurchase tables", () => {
    const result = extractWeekly(strategy, "MSTR");
    expect(result.issues).toEqual([]); expect(result.missing).toEqual([]);
    expect(result.extractionValidated).toBe(true);
    expect(result.periodStart).toBe("2026-08-24"); expect(result.balanceDate).toBe("2026-08-30");
    expect(result.facts).toMatchObject({ btc_holdings: 845050, weekly_btc_purchases: 4603,
      common_issued_shares: 4531421, common_issuance_proceeds_usd: 602800000,
      common_repurchased_shares: 0, common_repurchases_cash_usd: 0, usd_reserve_usd: 5100000000, usd_cash_usd: 1610000000 });
    expect(result.securities.STRC).toEqual({ issuedShares: 0, netIssuanceProceedsUsd: 0, repurchasedShares: 1557177, repurchaseCashUsd: 151800000 });
    expect(result.facts).not.toHaveProperty("effective_common_shares");
    expect(result.facts).not.toHaveProperty("debt");
  });
  it("extracts Strive balance endpoints and reconciles A+B and diluted shares", () => {
    const result = extractWeekly(strive, "ASST");
    expect(result.issues).toEqual([]); expect(result.missing).toEqual([]);
    expect(result.extractionValidated).toBe(true);
    expect(result.priorBalanceDate).toBe("2026-08-21"); expect(result.balanceDate).toBe("2026-08-28");
    expect(result.facts).toMatchObject({ btc_holdings: 23156, weekly_btc_purchases: 1800, cash_and_equivalents_usd: 183500000,
      effective_common_shares: 93262570, assumed_diluted_shares: 96523351, held_strc_shares: 505000,
      sata_shares: 9073914, net_common_shares_change: 3579147, net_sata_shares_change: 803099 });
    expect(result.priorFacts).toMatchObject({ btc_holdings: 21356, effective_common_shares: 89683423 });
    expect(result.facts).not.toHaveProperty("common_issuance_proceeds_usd");
  });
  it("rejects conflicting financial columns instead of publishing them", () => {
    const result = extractWeekly(strive.replaceAll("93,262,570", "94,262,570"), "ASST");
    expect(result.extractionValidated).toBe(false);
    expect(result.issues.some(issue => issue.includes("reconcile"))).toBe(true);
  });
  it("never turns missing or changed table headers into zero activity", () => {
    const result = extractWeekly(strategy.replaceAll("Shares Sold", "New different heading"), "MSTR");
    expect(result.extractionValidated).toBe(false);
    expect(result.missing).toContain("common_issued_shares");
    expect(result.facts).not.toHaveProperty("common_issued_shares");
  });
  it("flags nonweekly filings without inventing facts", () => {
    const result = extractWeekly("<html><p>Item 5.02. New director appointed.</p></html>", "ASST");
    expect(result.extractionValidated).toBe(false); expect(result.facts).toEqual({});
  });
});
