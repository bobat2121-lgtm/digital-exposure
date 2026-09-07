import { describe, expect, it } from "vitest";
import { allowedSecUrl, boundedText, documentUrl, parseSubmissions, validUserAgent } from "../src/sec";
export function submissions(accessions = ["0001193125-26-375463"], forms = ["8-K"], ticker = "MSTR"): string {
  return JSON.stringify({ cik: ticker === "MSTR" ? "1050446" : "1920406", filings: { recent: {
    accessionNumber: accessions, form: forms,
    filingDate: accessions.map(() => "2026-08-31"), reportDate: accessions.map(() => "2026-08-31"),
    acceptanceDateTime: accessions.map(() => "2026-08-31T12:00:15.000Z"),
    primaryDocument: accessions.map(() => ticker === "MSTR" ? "mstr-20260831.htm" : "asst-20260831.htm"),
  } } });
}
describe("bounded and trusted SEC requests", () => {
  it("allows only the two issuers and generated SEC paths", () => {
    expect(allowedSecUrl(documentUrl("MSTR", "0001193125-26-375463", "mstr-20260831.htm"))).toBe(true);
    expect(allowedSecUrl("https://data.sec.gov/submissions/CIK0001920406.json")).toBe(true);
    expect(allowedSecUrl("https://evil.example/Archives/edgar/data/1050446/000119312526375463/mstr.htm")).toBe(false);
    expect(allowedSecUrl("https://data.sec.gov/submissions/CIK0000000000.json")).toBe(false);
    expect(() => documentUrl("MSTR", "0001193125-26-375463", "../secret.htm")).toThrow();
  });
  it("requires a declared real contact and does not accept a browser disguise", () => {
    expect(validUserAgent("Mozilla/5.0")).toBe(false);
    expect(validUserAgent("Company test@example.com")).toBe(false);
    expect(validUserAgent("Digital report finance@digital-credit.test")).toBe(true);
  });
  it("records amendments as separate accessions with exact acceptance timestamps", () => {
    const records = parseSubmissions(submissions(["0001193125-26-375463", "0001193125-26-375464"], ["8-K", "8-K/A"]), "MSTR", Date.parse("2026-09-01T00:00Z"), false);
    expect(records).toHaveLength(2); expect(records[1].form).toBe("8-K/A");
    expect(records[0].acceptedAt).toBe("2026-08-31T12:00:15.000Z");
    expect(records[0].firstSeenAt).toBe("2026-09-01T00:00:00.000Z");
  });
  it("rejects malformed submissions and a foreign CIK", () => {
    expect(() => parseSubmissions(submissions().replace('"1050446"', '"1920406"'), "MSTR", 0, true)).toThrow(/CIK/);
    expect(() => parseSubmissions(submissions().replace(".000Z", ""), "MSTR", 0, true)).toThrow(/timezone/);
    expect(() => parseSubmissions(submissions().replace('"form":["8-K"]', '"form":[]'), "MSTR", 0, true)).toThrow(/length/);
  });
  it("caps streaming bodies before parsing", async () => {
    await expect(boundedText(new Response("long response"), 3)).rejects.toThrow(/size/);
  });
});
