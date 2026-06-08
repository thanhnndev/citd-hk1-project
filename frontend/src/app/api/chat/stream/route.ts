/**
 * Next.js route handler: GET /api/chat/stream
 *
 * Proxies the FastAPI SSE stream as a raw ReadableStream passthrough.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BACKEND_PORT = process.env.HN_BACKEND_HOST_PORT ?? "48721";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const message = searchParams.get("message")?.trim();
  const sessionId = searchParams.get("session_id")?.trim();
  const language = searchParams.get("language")?.trim() ?? "vi";
  const budget = searchParams.get("budget")?.trim();
  const accessibility = searchParams.get("accessibility")?.trim();
  const lat = searchParams.get("lat")?.trim();
  const lng = searchParams.get("lng")?.trim();
  const history = searchParams.get("history")?.trim();
  const requestId = request.headers.get("x-request-id") ?? crypto.randomUUID();

  if (!message || !sessionId) {
    return NextResponse.json({ error: "missing_params" }, { status: 400 });
  }

  const backendParams = new URLSearchParams({
    message,
    session_id: sessionId,
    language,
  });
  if (budget) backendParams.set("budget", budget);
  if (accessibility) backendParams.set("accessibility", accessibility);
  if (lat && lng) {
    backendParams.set("lat", lat);
    backendParams.set("lng", lng);
  }
  if (history) backendParams.set("history", history);

  const backendUrl = `http://localhost:${BACKEND_PORT}/chat/stream?${backendParams.toString()}`;

  let backendRes: globalThis.Response;
  try {
    backendRes = await fetch(backendUrl, {
      cache: "no-store",
      headers: {
        "Accept": "text/event-stream",
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
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
      "X-Request-ID": requestId,
    },
  });
}
