import { NextRequest, NextResponse } from "next/server";

const BACKEND = `http://localhost:${process.env.HN_BACKEND_HOST_PORT ?? "48721"}`;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const res = await fetch(`${BACKEND}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}
