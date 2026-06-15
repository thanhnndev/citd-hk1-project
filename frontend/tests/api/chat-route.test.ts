/**
 * Negative tests for POST /api/chat route handler.
 *
 * Tests cover:
 * - Successful proxied response (200)
 * - Backend 500 error mapped to structured JSON
 * - Backend 400 error mapped to structured JSON
 * - Backend unreachable (network error) → 502 with structured JSON
 * - Malformed / empty body → 502 (catch-all) with structured JSON
 * - Fetch timeout → 502 with structured JSON
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

    if (!backendRes.ok) {
      const errData = {
        type: "provider_unavailable",
        retryable: true,
        message_vi: `Máy chủ AI trả về lỗi (${backendRes.status}). Vui lòng thử lại sau.`,
        message_en: `AI server returned an error (${backendRes.status}). Please try again later.`,
        next_action: "retry"
      };
      return mockNextResponseJson(
        {
          error: "provider_unavailable",
          message: JSON.stringify(errData)
        },
        { status: backendRes.status }
      );
    }

    const data = await backendRes.json();

    return mockNextResponseJson(data, { status: backendRes.status });
  } catch {
    const errData = {
      type: "connection_offline",
      retryable: false,
      message_vi: "Hệ thống trợ lý du lịch Hàm Ninh hiện tại không thể kết nối. Yêu cầu của bạn chưa được thực hiện.",
      message_en: "The Ham Ninh travel assistant is currently unreachable. Your request was not processed.",
      next_action: "none"
    };
    return mockNextResponseJson(
      {
        error: "connection_offline",
        message: JSON.stringify(errData)
      },
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

  it("maps backend 500 error to structured JSON with 500 status", async () => {
    const errorPayload = { error: "Internal backend failure" };

    globalThis.fetch = async () =>
      ({
        status: 500,
        ok: false,
        json: async () => errorPayload,
      }) as Response;

    const res = await routeHandlerPost(validReq());

    assert.equal(res.status, 500);
    const body = res.body as { error: string; message: string };
    assert.equal(body.error, "provider_unavailable");
    const parsed = JSON.parse(body.message);
    assert.equal(parsed.type, "provider_unavailable");
    assert.equal(parsed.retryable, true);
    assert.match(parsed.message_vi, /lỗi \(500\)/);
  });

  it("maps backend 400 error to structured JSON with 400 status", async () => {
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
    const body = res.body as { error: string; message: string };
    assert.equal(body.error, "provider_unavailable");
    const parsed = JSON.parse(body.message);
    assert.equal(parsed.type, "provider_unavailable");
    assert.equal(parsed.retryable, true);
    assert.match(parsed.message_vi, /lỗi \(400\)/);
  });

  it("returns 502 with structured offline JSON when backend is unreachable", async () => {
    globalThis.fetch = async () => {
      const err = new Error("fetch failed: ECONNREFUSED");
      err.name = "TypeError";
      throw err;
    };

    const res = await routeHandlerPost(validReq());

    assert.equal(res.status, 502);
    const body = res.body as { error: string; message: string };
    assert.equal(body.error, "connection_offline");
    const parsed = JSON.parse(body.message);
    assert.equal(parsed.type, "connection_offline");
    assert.equal(parsed.retryable, false);
    assert.match(parsed.message_vi, /Hệ thống trợ lý du lịch Hàm Ninh hiện tại không thể kết nối/);
  });

  it("returns 502 with structured offline JSON when fetch throws a timeout error", async () => {
    globalThis.fetch = async () => {
      const err = new Error("The operation was aborted due to timeout");
      err.name = "TimeoutError";
      throw err;
    };

    const res = await routeHandlerPost(validReq());

    assert.equal(res.status, 502);
    const body = res.body as { error: string; message: string };
    assert.equal(body.error, "connection_offline");
    const parsed = JSON.parse(body.message);
    assert.equal(parsed.type, "connection_offline");
    assert.equal(parsed.retryable, false);
    assert.match(parsed.message_vi, /Hệ thống trợ lý du lịch Hàm Ninh hiện tại không thể kết nối/);
  });

  it("returns 502 with structured offline JSON when request body is not valid JSON (empty/malformed body)", async () => {
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

    assert.equal(res.status, 502);
    const body = res.body as { error: string; message: string };
    assert.equal(body.error, "connection_offline");
    const parsed = JSON.parse(body.message);
    assert.equal(parsed.type, "connection_offline");
    assert.equal(parsed.retryable, false);
    assert.match(parsed.message_vi, /Hệ thống trợ lý du lịch Hàm Ninh hiện tại không thể kết nối/);
  });

  it("returns 502 with structured offline JSON when backend response is not valid JSON", async () => {
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
    const body = res.body as { error: string; message: string };
    assert.equal(body.error, "connection_offline");
    const parsed = JSON.parse(body.message);
    assert.equal(parsed.type, "connection_offline");
    assert.equal(parsed.retryable, false);
    assert.match(parsed.message_vi, /Hệ thống trợ lý du lịch Hàm Ninh hiện tại không thể kết nối/);
  });
});

console.log("chat-route negative tests loaded");
