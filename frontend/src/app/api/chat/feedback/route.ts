/**
 * Next.js route handler: POST /api/chat/feedback
 *
 * Proxies feedback submissions to the FastAPI backend /chat/feedback endpoint.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_PORT = process.env.HN_BACKEND_HOST_PORT ?? "48721";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const requestId = request.headers.get("x-request-id") ?? crypto.randomUUID();

    const backendUrl = `http://localhost:${BACKEND_PORT}/chat/feedback`;

    const response = await fetch(backendUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
        "X-API-Key": process.env.HN_API_KEY ?? "",
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const error = await response.text();
      return NextResponse.json(
        { error: "Feedback submission failed", details: error },
        { status: response.status }
      );
    }

    const result = await response.json();
    return NextResponse.json(result);
  } catch (error) {
    console.error("Feedback proxy error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
