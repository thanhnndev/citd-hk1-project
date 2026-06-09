/**
 * Resume endpoint - sends user input back to a paused LangGraph.
 * 
 * When the backend calls interrupt(), the graph pauses and waits for user input.
 * This endpoint accepts the user's response (e.g., geolocation) and resumes
 * the graph execution via Command(resume=...).
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_PORT = process.env.HN_BACKEND_HOST_PORT ?? "48721";
const BACKEND_URL = process.env.HN_BACKEND_URL ?? `http://localhost:${BACKEND_PORT}`;

export async function POST(request: NextRequest) {
  const body = await request.json();
  const { session_id, resume_value } = body;

  if (!session_id || !resume_value) {
    return NextResponse.json(
      { error: "Missing session_id or resume_value" },
      { status: 400 }
    );
  }

  try {
    const response = await fetch(`${BACKEND_URL}/chat/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id, resume_value }),
    });

    if (!response.ok) {
      const error = await response.text();
      return NextResponse.json(
        { error: "Resume failed", details: error },
        { status: response.status }
      );
    }

    const result = await response.json();
    return NextResponse.json(result);
  } catch (error) {
    console.error("Resume request failed:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
