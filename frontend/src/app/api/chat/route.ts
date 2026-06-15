/**
 * Next.js route handler: POST /api/chat
 *
 * Proxies the request to the FastAPI backend.
 * Returns user-friendly, localized error messages when backend is offline
 * or returns an error response, hiding low-level server/port/HTTP jargon.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_PORT = process.env.HN_BACKEND_HOST_PORT ?? "48721";
const BACKEND_URL = `http://localhost:${BACKEND_PORT}/chat`;

export async function POST(request: NextRequest) {
  let requestId = request.headers.get("x-request-id") ?? crypto.randomUUID();
  try {
    const body = await request.json();

    const backendRes = await fetch(BACKEND_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
      body: JSON.stringify(body),
    });

    if (!backendRes.ok) {
      const errData = {
        type: "provider_unavailable",
        retryable: true,
        message_vi: "Hệ thống gợi ý du lịch đang gặp lỗi xử lý hoặc quá tải. Không có thông tin nào của bạn bị thay đổi. Bạn vui lòng thử lại sau vài giây.",
        message_en: "The travel recommendation system is currently busy or encountered a processing issue. None of your data was changed. Please try again in a few seconds.",
        next_action: "retry"
      };
      const response = NextResponse.json(
        {
          error: "provider_unavailable",
          message: JSON.stringify(errData)
        },
        { status: backendRes.status }
      );
      response.headers.set("x-request-id", requestId);
      return response;
    }

    const data = await backendRes.json();
    const response = NextResponse.json(data, { status: backendRes.status });
    response.headers.set("x-request-id", requestId);
    return response;
  } catch {
    const errData = {
      type: "connection_offline",
      retryable: false,
      message_vi: "Hệ thống trợ lý du lịch Hàm Ninh hiện tại không thể kết nối. Yêu cầu của bạn chưa được thực hiện.",
      message_en: "The Ham Ninh travel assistant is currently unreachable. Your request was not processed.",
      next_action: "none"
    };
    const response = NextResponse.json(
      {
        error: "connection_offline",
        message: JSON.stringify(errData)
      },
      { status: 502 },
    );
    response.headers.set("x-request-id", requestId);
    return response;
  }
}
