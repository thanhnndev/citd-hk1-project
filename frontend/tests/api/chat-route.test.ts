/**
 * Negative tests for POST /api/chat route handler.
 *
 * Tests cover:
 * - Successful proxied response (200)
 * - Backend 500 error passthrough
 * - Backend 400 error passthrough
 * - Backend unreachable (network error) → 502
 * - Malformed / empty body → 502 (catch-all)
 * - Fetch timeout → 502
 *
 * Since `next/server` cannot be loaded outside the Next.js runtime,
 * the route handler's core logic is reproduced inline (identical to
 * `src/app/api/chat/route.ts`) and tested with mocked globals.
 *
 * Run: node --test --experimental-strip-types frontend/tests/api/chat-route.test.ts
 */

import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

/* ── Inline replica of the route handler logic ─────────────────────── */
/* This must stay in sync with src/app/api/chat/route.ts.             */

const BACKEND_PORT = process.env.HN_BACKEND_HOST_PORT ?? "48721";
const BACKEND_URL = `http://localhost:${BACKEND_PORT}/chat`;

interface MockRequest {
  jsonBody: unknown;
  jsonError?: Error | null;
  json(): Promise<unknown>;
}

interface MockResponse {
  status: number;
  body: unknown;
  headers: Record<string, string>;
}

function mockNextResponseJson(
  body: unknown,
  init?: { status?: number },
): MockResponse {
  return {
    body,
    status: init?.status ?? 200,
    headers: { "content-type": "application/json" },
  };
}

async function routeHandlerPost(req: MockRequest): Promise<MockResponse> {
  try {
    const body = await req.json();

    const backendRes = await fetch(BACKEND_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await backendRes.json();

    return mockNextResponseJson(data, { status: backendRes.status });
  } catch {
    return mockNextResponseJson(
      { error: "Backend unavailable" },
      { status: 502 },
    );
  }
}

/* ── Helpers ───────────────────────────────────────────────────────── */

function validReq(): MockRequest {
  return {
    jsonBody: {
      session_id: "sess-test",
      message: "Where to eat?",
      language: "vi",
    },
    json() {
      return Promise.resolve(this.jsonBody);
    },
  };
}

function sampleChatResponse(): Record<string, unknown> {
  return {
    session_id: "test-session-123",
    message: "Here are some places near you.",
    citations: [
      { source: "OpenStreetMap", url: "https://example.com", snippet: null },
    ],
    places: [],
    reasoning_log: null,
    intent: "search",
    langfuse_trace_id: null,
    latency_ms: 42,
  };
}

/* ── Tests ─────────────────────────────────────────────────────────── */

describe("POST /api/chat — negative & edge-case tests", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("returns 200 with ChatResponse shape when backend succeeds", async () => {
    const payload = sampleChatResponse();

    globalThis.fetch = async () =>
      ({
        status: 200,
        ok: true,
        json: async () => payload,
      }) as Response;

    const res = await routeHandlerPost(validReq());

    assert.equal(res.status, 200);
    assert.deepEqual(res.body, payload);
    assert.equal(res.headers["content-type"], "application/json");
  });

  it("passes through backend 500 error as 500", async () => {
    const errorPayload = { error: "Internal backend failure" };

    globalThis.fetch = async () =>
      ({
        status: 500,
        ok: false,
        json: async () => errorPayload,
      }) as Response;

    const res = await routeHandlerPost(validReq());

    assert.equal(res.status, 500);
    assert.deepEqual(res.body, errorPayload);
  });

  it("passes through backend 400 error as 400", async () => {
    const errorPayload = {
      error: "validation_error",
      detail: "message field is required",
    };

    globalThis.fetch = async () =>
      ({
        status: 400,
        ok: false,
        json: async () => errorPayload,
      }) as Response;

    const res = await routeHandlerPost(validReq());

    assert.equal(res.status, 400);
    assert.deepEqual(res.body, errorPayload);
  });

  it("returns 502 when backend is unreachable (network error)", async () => {
    globalThis.fetch = async () => {
      const err = new Error("fetch failed: ECONNREFUSED");
      err.name = "TypeError";
      throw err;
    };

    const res = await routeHandlerPost(validReq());

    assert.equal(res.status, 502);
    assert.deepEqual(res.body, { error: "Backend unavailable" });
  });

  it("returns 502 when fetch throws a timeout error", async () => {
    globalThis.fetch = async () => {
      const err = new Error("The operation was aborted due to timeout");
      err.name = "TimeoutError";
      throw err;
    };

    const res = await routeHandlerPost(validReq());

    assert.equal(res.status, 502);
    assert.deepEqual(res.body, { error: "Backend unavailable" });
  });

  it("returns 502 when request body is not valid JSON (empty/malformed body)", async () => {
    const badReq: MockRequest = {
      jsonBody: null,
      jsonError: new SyntaxError("Unexpected end of JSON input"),
      json() {
        if (this.jsonError) throw this.jsonError;
        return Promise.resolve(this.jsonBody);
      },
    };

    // fetch should NOT be called because json() throws first
    globalThis.fetch = async () => {
      throw new Error("fetch should not be called for malformed body");
    };

    const res = await routeHandlerPost(badReq);

    // The catch-all handler returns 502 for any error, including JSON parse
    assert.equal(res.status, 502);
    assert.deepEqual(res.body, { error: "Backend unavailable" });
  });

  it("returns 502 when backend response is not valid JSON", async () => {
    globalThis.fetch = async () =>
      ({
        status: 200,
        ok: true,
        json: async () => {
          throw new SyntaxError("Unexpected token < in JSON");
        },
      }) as unknown as Response;

    const res = await routeHandlerPost(validReq());

    assert.equal(res.status, 502);
    assert.deepEqual(res.body, { error: "Backend unavailable" });
  });
});

console.log("chat-route negative tests loaded");
