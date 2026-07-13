import { describe, expect, it } from "vitest";
import {
  isValidDomain,
  normalizeDomain,
  parseCompetitors,
  validateProjectDraft,
} from "./validation";

describe("project form validation", () => {
  it("normalizes URL-shaped domains", () => {
    expect(normalizeDomain(" HTTPS://Example.COM/ ")).toBe("example.com");
  });

  it("rejects malformed domains", () => {
    expect(isValidDomain("not a domain")).toBe(false);
    expect(isValidDomain("example.com")).toBe(true);
  });

  it("deduplicates competitor input", () => {
    expect(parseCompetitors("Rival.com, https://rival.com/, other.io")).toEqual([
      "rival.com",
      "other.io",
    ]);
  });

  it("normalizes a complete valid project draft", () => {
    expect(
      validateProjectDraft({
        name: "  Acme  ",
        domain: "https://Acme.com/",
        competitors: "rival.com, acme.com, RIVAL.com",
      }),
    ).toEqual({
      draft: { name: "Acme", domain: "acme.com", competitors: ["rival.com"] },
      errors: {},
    });
  });

  it("reports field-specific project errors", () => {
    const result = validateProjectDraft({
      name: " ",
      domain: "not a domain",
      competitors: "also invalid",
    });
    expect(result.draft).toBeNull();
    expect(result.errors).toEqual({
      name: "Enter a project name.",
      domain: "Enter a valid domain such as example.com.",
      competitors: "also invalid is not a valid competitor domain.",
    });
  });
});
