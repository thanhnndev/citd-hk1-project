/**
 * Resume endpoint - sends user input back to a paused LangGraph.
 * 
 * When the backend calls interrupt(), the graph pauses and waits for user input.
 * This endpoint accepts the user's response (e.g., geolocation) and resumes
 * the graph execution via Command(resume=...).
 * 
 * Emits friendly error structures on connection failure/non-ok backend status.
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
      const errData = {
        type: "provider_unavailable",
        retryable: true,
        message_vi: "Hệ thống gợi ý du lịch đang gặp lỗi xử lý hoặc quá tải. Không có thông tin nào của bạn bị thay đổi. Bạn vui lòng thử lại sau vài giây.",
        message_en: "The travel recommendation system is currently busy or encountered a processing issue. None of your data was changed. Please try again in a few seconds.",
        next_action: "retry"
      };
      return NextResponse.json(
        { error: "provider_unavailable", message: JSON.stringify(errData) },
        { status: response.status }
      );
    }

    const result = await response.json();
    return NextResponse.json(result);
  } catch (error) {
    console.error("Resume request failed:", error);
    const errData = {
      type: "connection_offline",
      retryable: false,
      message_vi: "Hệ thống trợ lý du lịch Hàm Ninh hiện tại không thể kết nối. Yêu cầu của bạn chưa được thực hiện.",
      message_en: "The Ham Ninh travel assistant is currently unreachable. Your request was not processed.",
      next_action: "none"
    };
    return NextResponse.json(
      { error: "connection_offline", message: JSON.stringify(errData) },
      { status: 502 }
    );
  }
}
