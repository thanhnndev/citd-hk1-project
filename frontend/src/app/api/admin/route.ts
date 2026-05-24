/**
 * Next.js API proxy route: /api/admin/*
 *
 * Forwards requests to the FastAPI backend at /admin/*, preserving
 * the path suffix, forwarding all headers (especially Authorization),
 * and proxying the request body for POST/PUT/PATCH.
 *
 * Returns the backend response with the same status code.
 * On network failure returns 502 with { detail: "Backend unavailable" }.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND = `http://localhost:${process.env.HN_BACKEND_HOST_PORT ?? "48721"}`;

function buildBackendUrl(request: NextRequest): string {
  // Strip /api/admin prefix and forward the rest to /admin/*
  const pathname = request.nextUrl.pathname.replace(/^\/api\/admin/, "/admin");
  const backendUrl = new URL(pathname, BACKEND);
  // Forward query string
  backendUrl.search = request.nextUrl.search;
  return backendUrl.toString();
}

function isBodyAllowed(method: string): boolean {
  return ["POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase());
}

export async function GET(request: NextRequest) {
  const url = buildBackendUrl(request);
  try {
    const headers = new Headers();
    request.headers.forEach((value, key) => {
      // Skip Next.js internal headers
      if (key.toLowerCase() !== "host") {
        headers.set(key, value);
      }
    });
    headers.set("Content-Type", "application/json");

    const res = await fetch(url, {
      method: "GET",
      headers,
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}

export async function POST(request: NextRequest) {
  const url = buildBackendUrl(request);
  try {
    const body = await request.json();
    const headers = new Headers();
    request.headers.forEach((value, key) => {
      if (key.toLowerCase() !== "host") {
        headers.set(key, value);
      }
    });
    headers.set("Content-Type", "application/json");

    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}

export async function PUT(request: NextRequest) {
  const url = buildBackendUrl(request);
  try {
    const body = await request.json();
    const headers = new Headers();
    request.headers.forEach((value, key) => {
      if (key.toLowerCase() !== "host") {
        headers.set(key, value);
      }
    });
    headers.set("Content-Type", "application/json");

    const res = await fetch(url, {
      method: "PUT",
      headers,
      body: JSON.stringify(body),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}

export async function DELETE(request: NextRequest) {
  const url = buildBackendUrl(request);
  try {
    const headers = new Headers();
    request.headers.forEach((value, key) => {
      if (key.toLowerCase() !== "host") {
        headers.set(key, value);
      }
    });
    headers.set("Content-Type", "application/json");

    const res = await fetch(url, {
      method: "DELETE",
      headers,
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}
