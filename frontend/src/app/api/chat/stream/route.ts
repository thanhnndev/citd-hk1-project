/**
 * Next.js route handler: GET /api/chat/stream
 *
 * Proxies the FastAPI SSE stream as a raw ReadableStream passthrough.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_PORT = process.env.HN_BACKEND_HOST_PORT ?? "48721";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const message = searchParams.get("message")?.trim();
  const sessionId = searchParams.get("session_id")?.trim();
  const language = searchParams.get("language")?.trim() ?? "vi";
  const requestId = request.headers.get("x-request-id") ?? crypto.randomUUID();

  if (!message || !sessionId) {
    return NextResponse.json({ error: "missing_params" }, { status: 400 });
  }

  const backendUrl =
    `http://localhost:${BACKEND_PORT}/chat/stream` +
    `?message=${encodeURIComponent(message)}` +
    `&session_id=${encodeURIComponent(sessionId)}` +
    `&language=${encodeURIComponent(language)}`;

  let backendRes: globalThis.Response;
  try {
    backendRes = await fetch(backendUrl, {
      headers: {
        "X-Request-ID": requestId,
        "X-API-Key": process.env.HN_API_KEY ?? "",
      },
    });
  } catch {
    return NextResponse.json({ error: "Backend unavailable" }, { status: 502 });
  }

  return new Response(backendRes.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Request-ID": requestId,
    },
  });
}
