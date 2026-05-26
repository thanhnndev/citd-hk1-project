import { NextRequest, NextResponse } from "next/server";

const BACKEND = `http://localhost:${process.env.HN_BACKEND_HOST_PORT ?? "48721"}`;

export async function GET(request: NextRequest) {
  const authHeader = request.headers.get("Authorization");
  try {
    const res = await fetch(`${BACKEND}/auth/me`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}
