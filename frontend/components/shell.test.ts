import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ErrorBox, Score, Status } from "./shell";
import { ApiError } from "../lib/api";

describe("shared status components", () => {
  it("renders machine statuses as readable text", () => {
    expect(renderToStaticMarkup(createElement(Status, { value: "in_progress" }))).toContain(
      "in progress",
    );
  });

  it("renders an explicit empty score", () => {
    expect(renderToStaticMarkup(createElement(Score, { value: null }))).toContain("—");
  });

  it("marks errors as alerts", () => {
    expect(renderToStaticMarkup(createElement(ErrorBox, { message: "Audit failed" }))).toContain(
      'role="alert"',
    );
  });

  it("renders support metadata and retry actions for API errors", () => {
    const error = new ApiError("Rate limited", 429, {
      code: "rate_limited",
      requestId: "req_123",
      retryAfter: "10",
    });
    const markup = renderToStaticMarkup(
      createElement(ErrorBox, { error, onRetry: () => undefined }),
    );

    expect(markup).toContain("req_123");
    expect(markup).toContain("rate_limited");
    expect(markup).toContain("Try again");
  });
});
