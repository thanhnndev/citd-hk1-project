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
  tree1_locality: number;
  tree2_proximity: number;
  tree3_quality: number;
  s_bag: number;
  delta1_fairness: number;
  delta2_access: number;
  final_score: number;
  rank: number;
}

/**
 * Safe structured explanation for why a place was recommended.
 * Mirrors backend/app/models/response.py PlaceExplanation (extra='forbid').
 * All fields are backend-owned — the frontend never fabricates reasoning.
 */
export interface PlaceExplanation {
  /** 1-based recommendation rank, or 0 when not ranked. */
  rank: number;
  /** Concise reason derived only from normalized place data. */
  primary_reason: string;
  /** Preference signals matched by the normalized candidate. */
  matched_preferences: string[];
  /** Safe locality/fairness context without exact user GPS. */
  local_context: string;
  /** Compact score fields used by the reranker or fallback scorer. */
  score_factors: Record<string, number | string | null>;
  /** Fairness/locality note derived from local_factor metadata. */
  fairness_note: string;
  /** Accessibility note derived from normalized accessibility fields. */
  accessibility_note: string;
  /** Route summary without exact origin/user GPS. */
  route_summary: string;
  /** Normalized provider/source label (google_places, goong_places, mock, cache). */
  provider_source: string | null;
  /** Normalized provider status (ok, empty, credentials_blocked, upstream_error, unavailable). */
  provider_status: string | null;
  /** Normalized candidate/result fields used to build this explanation. */
  evidence_fields_used: string[];
}

export interface PlaceResult {
  place_id: string;
  display_name: string;
  formatted_address?: string | null;
  location?: LatLng | null;
  types: string[];
  primary_type?: string | null;
  rating?: number | null;
  user_rating_count?: number | null;
  price_level?: number | null;
  open_now?: boolean | null;
  business_status?: string | null;
  local_factor: number;
  final_score: number;
  score_breakdown: ScoreBreakdown;
  accessibility_score?: number | null;
  accessibility_warning?: string | null;
  map_uri: string;
  /** Structured why-this-recommendation data from backend. Never fabricated. */
  explanation?: PlaceExplanation;
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
  suggestions?: string[];
  reasoning_log?: string | null;
  intent?: string | null;
  langfuse_trace_id?: string | null;
  fallback?: boolean;
  guardrail_status?: string;
  cache_hit?: boolean;
  latency_ms: number;
}

export type ChatStreamStatus =
  | "understanding"
  | "using_history"
  | "searching_knowledge"
  | "checking_places"
  | "composing";

/**
 * Provider source vocabulary — reflects which provider actually served results.
 * Never fabricated by the frontend.
 * @see docs/M014-S03-RECOMMENDATION-EXPLANATION-CONTRACT.md §2
 */
export type ProviderSource = "google_places" | "goong_places" | "mock" | "cache";

/**
 * Provider status vocabulary — reflects actual provider health/result state.
 * @see docs/M014-S03-RECOMMENDATION-EXPLANATION-CONTRACT.md §2
 */
export type ProviderStatus = "ok" | "empty" | "credentials_blocked" | "upstream_error" | "unavailable";

export interface StreamChatCallbacks {
  onToken: (token: string) => void;
  onCitations: (citations: Citation[]) => void;
  onPlaces?: (places: PlaceResult[]) => void;
  onStatus?: (status: ChatStreamStatus) => void;
  onSuggestions?: (suggestions: string[]) => void;
  onDone: () => void;
  onOpen?: () => void;
  onError: (error: string) => void;
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

export async function streamChat(
  message: string,
  sessionId: string,
  language: "vi" | "en",
  callbacks: StreamChatCallbacks,
): Promise<void> {
  const params = new URLSearchParams({
    message,
    session_id: sessionId,
    language,
  });

  const res = await fetch(`/api/chat/stream?${params.toString()}`, {
    headers: { Accept: "text/event-stream" },
  });

  if (!res.ok) {
    callbacks.onError(`Chat stream failed (${res.status})`);
    return;
  }

  if (!res.body) {
    callbacks.onError("No stream body");
    return;
  }

  callbacks.onOpen?.();

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const event of events) {
      const dataLines = event
        .split("\n")
        .filter((line) => line.startsWith("data: "));

      const data = dataLines.map((line) => line.slice(6)).join("\n");

      if (data === "[DONE]") {
        callbacks.onDone();
        return;
      }

      if (data.startsWith("[STATUS] ")) {
        callbacks.onStatus?.(data.slice(9) as ChatStreamStatus);
        continue;
      }

      if (data.startsWith("[CITATIONS] ")) {
        try {
          callbacks.onCitations(JSON.parse(data.slice(12)) as Citation[]);
        } catch {
          callbacks.onError("Invalid citations payload");
          return;
        }
        continue;
      }

      if (data.startsWith("[PLACES] ")) {
        try {
          callbacks.onPlaces?.(JSON.parse(data.slice(9)) as PlaceResult[]);
        } catch {
          callbacks.onError("Invalid places payload");
          return;
        }
        continue;
      }

      if (data.startsWith("[SUGGESTIONS] ")) {
        try {
          callbacks.onSuggestions?.(JSON.parse(data.slice(14)) as string[]);
        } catch {
          callbacks.onError("Invalid suggestions payload");
          return;
        }
        continue;
      }

      if (data.startsWith("[ERROR] ")) {
        callbacks.onError(data.slice(8));
        return;
      }

      callbacks.onToken(data);
    }
  }
}
