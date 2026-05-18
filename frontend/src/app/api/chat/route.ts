/**
 * Next.js route handler: POST /api/chat
 *
 * Proxies the request to the FastAPI backend, forwarding the JSON body
 * and passing through the response status + body.  The backend host/port
 * is configurable via HN_BACKEND_HOST_PORT (default 48721).
 *
 * On network failure (backend unreachable) returns 502 with
 * `{ error: 'Backend unavailable' }` so the UI can surface it.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_PORT = process.env.HN_BACKEND_HOST_PORT ?? "48721";
const BACKEND_URL = `http://localhost:${BACKEND_PORT}/chat`;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const backendRes = await fetch(BACKEND_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await backendRes.json();

    return NextResponse.json(data, { status: backendRes.status });
  } catch {
    return NextResponse.json(
      { error: "Backend unavailable" },
      { status: 502 },
    );
  }
}
