import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import { middleware } from "./middleware";

describe("content security policy", () => {
  it("does not upgrade local HTTP assets in a production build", () => {
    const response = middleware(new NextRequest("http://localhost:3000/"));
    const policy = response.headers.get("Content-Security-Policy");
    expect(policy).not.toContain("upgrade-insecure-requests");
    expect(policy).toContain("style-src-attr 'unsafe-inline'");
    expect(policy).toMatch(/style-src-elem 'self' 'nonce-[^']+'/);
  });

  it("upgrades insecure assets for an HTTPS request", () => {
    const response = middleware(new NextRequest("https://visibility.example.com/"));
    expect(response.headers.get("Content-Security-Policy")).toContain("upgrade-insecure-requests");
  });
});
