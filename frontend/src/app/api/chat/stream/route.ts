/**
 * Next.js route handler: GET /api/chat/stream
 *
 * Proxies the FastAPI SSE stream.
 * Yields structured, user-friendly SSE error packets instead of HTTP 502 or technical logs.
 */

import { NextRequest, NextResponse } from "next/server";
import http from "node:http";
import { Readable } from "node:stream";

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

  return new Promise<Response>((resolve) => {
    const req = http.request(
      backendUrl,
      {
        method: "GET",
        headers: {
          "Accept": "text/event-stream",
          "X-Request-ID": requestId,
          "X-API-Key": process.env.HN_API_KEY ?? "",
        },
      },
      (res) => {
        if (res.statusCode && res.statusCode >= 400) {
          const errData = {
            type: "provider_unavailable",
            retryable: true,
            message_vi: "Hệ thống gợi ý du lịch đang gặp lỗi xử lý hoặc quá tải. Không có thông tin nào của bạn bị thay đổi. Bạn vui lòng thử lại sau vài giây.",
            message_en: "The travel recommendation system is currently busy or encountered a processing issue. None of your data was changed. Please try again in a few seconds.",
            next_action: "retry"
          };
          resolve(
            new Response(`data: [ERROR] ${JSON.stringify(errData)}\n\n`, {
              status: 200,
              headers: {
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
              },
            })
          );
          return;
        }

        // Convert the Node incoming message stream to Web ReadableStream
        const webStream = Readable.toWeb(res) as unknown as ReadableStream;

        resolve(
          new Response(webStream, {
            status: 200,
            headers: {
              "Content-Type": "text/event-stream; charset=utf-8",
              "Cache-Control": "no-cache, no-transform",
              "Connection": "keep-alive",
              "X-Accel-Buffering": "no",
              "X-Request-ID": requestId,
            },
          })
        );
      }
    );

    req.on("error", (err) => {
      const errData = {
        type: "connection_offline",
        retryable: false,
        message_vi: "Hệ thống trợ lý du lịch Hàm Ninh hiện tại không thể kết nối. Yêu cầu của bạn chưa được thực hiện.",
        message_en: "The Ham Ninh travel assistant is currently unreachable. Your request was not processed.",
        next_action: "none"
      };
      resolve(
        new Response(`data: [ERROR] ${JSON.stringify(errData)}\n\n`, {
          status: 200,
          headers: {
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
          },
        })
      );
    });

    req.end();
  });
}

