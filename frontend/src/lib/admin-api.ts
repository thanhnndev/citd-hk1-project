/**
 * Typed API client for /api/admin/* proxy routes.
 * Each call attaches the JWT token from localStorage via getToken().
 */

import { getToken } from "@/lib/auth-store";

/* ── Response shapes (mirrors backend response models) ─────── */

export interface CorpusStatsResponse {
  total_chunks: number;
  total_docs: number;
  language_distribution: Record<string, number>;
  bm25_vocab_size: number;
  hybrid_enabled: boolean;
  qdrant_collection_name: string | null;
}

export interface EvalTriggerRequest {
  dataset_path?: string;
  metrics?: string[];
}

export interface EvalResultResponse {
  verdict: string;
  metrics: Record<string, unknown>;
  timestamp: string;
  dataset_size: number;
  latency_ms: number;
  result_path: string | null;
}

export interface TracesStatusResponse {
  langfuse_enabled: boolean;
  host: string | null;
  message: string;
}

export interface FairnessSummaryResponse {
  total_audits: number;
  latest_timestamp: string | null;
  local_factor_distribution: Record<string, unknown> | null;
  message: string | null;
}

/* ── Helpers ────────────────────────────────────────────────── */

interface AdminFetchOptions extends RequestInit {
  /** Optional path appended to /api/admin (e.g. "/stats", "/eval/trigger"). */
  path?: string;
}

async function adminFetch<T>(options: AdminFetchOptions): Promise<T> {
  const token = getToken();
  if (!token) {
    throw new Error("No authentication token — call login first.");
  }

  const url = options.path
    ? `/api/admin${options.path}`
    : "/api/admin";

  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(options.headers ?? {}),
    },
  });

  const data = await res.json().catch(() => null);

  if (!res.ok) {
    const message =
      (data as { detail?: string } | null)?.detail ??
      `Admin request failed (${res.status})`;
    throw new Error(message);
  }

  return data as T;
}

/* ── Public API ─────────────────────────────────────────────── */

export async function getCorpusStats(): Promise<CorpusStatsResponse> {
  return adminFetch<CorpusStatsResponse>({ method: "GET", path: "/stats" });
}

export async function triggerEval(
  body?: EvalTriggerRequest,
): Promise<EvalResultResponse> {
  return adminFetch<EvalResultResponse>({
    method: "POST",
    path: "/eval/trigger",
    body: JSON.stringify(body ?? {}),
  });
}

export async function getEvalResults(): Promise<EvalResultResponse[]> {
  return adminFetch<EvalResultResponse[]>({
    method: "GET",
    path: "/eval/results",
  });
}

export async function getTracesStatus(): Promise<TracesStatusResponse> {
  return adminFetch<TracesStatusResponse>({
    method: "GET",
    path: "/traces",
  });
}

export async function getFairnessSummary(): Promise<FairnessSummaryResponse> {
  return adminFetch<FairnessSummaryResponse>({
    method: "GET",
    path: "/fairness",
  });
}
