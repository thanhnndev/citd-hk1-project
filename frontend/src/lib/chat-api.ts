/**
 * Typed API client for POST /api/chat.
 *
 * Mirrors the Pydantic models from backend/app/models/request.py and
 * backend/app/models/response.py so the frontend gets compile-time safety.
 */

/* ── Request shapes (backend: ChatRequest) ─────────────────────────── */

export interface LatLng {
  lat: number;
  lng: number;
}

export interface ChatRequest {
  session_id: string;
  message: string;
  language: "vi" | "en";
  budget_filter?: string | null;
  user_location?: LatLng | null;
  accessibility_required?: boolean;
}

/* ── Response shapes (backend: ChatResponse, Citation, PlaceResult) ── */

export interface ScoreBreakdown {
  relevance: number;
  proximity: number;
  price: number;
  rating: number;
  accessibility: number;
}

export interface PlaceResult {
  place_id: string;
  display_name: string;
  formatted_address?: string | null;
  rating?: number | null;
  price_level?: number | null;
  local_factor: number;
  final_score: number;
  score_breakdown: ScoreBreakdown;
  accessibility_score?: number | null;
  accessibility_warning?: string | null;
  google_maps_uri: string;
}

export interface Citation {
  source: string;
  url?: string | null;
  snippet?: string | null;
}

export interface ChatResponse {
  session_id: string;
  message: string;
  citations: Citation[];
  places: PlaceResult[];
  reasoning_log?: string | null;
  intent?: string | null;
  langfuse_trace_id?: string | null;
  latency_ms: number;
}

/* ── Error shape returned by the route handler on 502 ──────────────── */

export interface ChatError {
  error: string;
}

/* ── Public API ────────────────────────────────────────────────────── */

/**
 * Send a chat message to the backend via the Next.js proxy route.
 *
 * @param message  – the user's natural-language query
 * @param sessionId – optional session ID for conversation continuity;
 *                    a UUID v4 is generated when omitted
 * @param language  – "vi" or "en"; defaults to "vi"
 * @returns parsed ChatResponse from the backend
 * @throws Error when the HTTP response is not OK or the body is invalid
 */
export async function sendChat(
  message: string,
  sessionId?: string,
  language: "vi" | "en" = "vi",
): Promise<ChatResponse> {
  const body: ChatRequest = {
    session_id: sessionId ?? crypto.randomUUID(),
    message,
    language,
    accessibility_required: true,
  };

  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const data = (await res.json().catch(() => null)) as ChatError | null;
    throw new Error(data?.error ?? `Chat request failed (${res.status})`);
  }

  return (await res.json()) as ChatResponse;
}
