"use client";

import { CitationCard } from "./citation-card";
import { PlaceCard } from "./place-card";
import { MessageActions } from "./message-actions";
import { AccessibilityBadge } from "@/components/reasoning/accessibility-badge";
import { Bot, CheckCircle2, Clock3, Loader2, UserRound, ArrowRight } from "lucide-react";
import type { ChatStreamStatus, Citation, PlaceResult } from "@/lib/chat-api";

export type MessageStatus = "submitted" | "streaming" | "complete";

interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  places?: PlaceResult[];
  typingLabel?: string;
  assistantLabel?: string;
  userLabel?: string;
  sourcesLabel?: string;
  streamStatusLabel?: string;
  status?: MessageStatus;
  guardrailStatus?: string;
  fallback?: boolean;
  langfuseTraceId?: string | null;
  cacheHit?: boolean;
  /** Bounded history of operational phases seen during streaming. */
  statusHistory?: ChatStreamStatus[];
  /** Map from status key to display label (for rendering timeline). */
  streamStatusLabels?: Record<string, string>;
  placeTranslations?: {
    placeResultsHeading: string;
    viewOnMap: string;
    scoreLabel: string;
    noRating: string;
    scoreBreakdown?: string;
    explanation?: string;
    providerSource?: string;
    providerStatus?: string;
    scoreDataLimited?: string;
    accessibilityNote?: string;
  };
  actionTranslations?: {
    copy?: string;
    copied?: string;
    retry?: string;
  };
  onRetry?: () => void;
}

export function MessageBubble({
  role,
  content,
  citations,
  places,
  typingLabel = "Thinking...",
  assistantLabel = "Ham Ninh Assistant",
  userLabel = "You",
  sourcesLabel = "Sources",
  streamStatusLabel,
  status = "complete",
  guardrailStatus,
  fallback,
  langfuseTraceId,
  cacheHit,
  statusHistory,
  streamStatusLabels,
  placeTranslations,
  actionTranslations,
  onRetry,
}: MessageBubbleProps) {
  const isUser = role === "user";
  const isPending = !content;
  const hasSources = Boolean(citations?.length);
  const showComplete = !isUser && status === "complete" && content;
  const hasStatusHistory = !isUser && statusHistory && statusHistory.length > 0;
  const isStreaming = status === "streaming" || status === "submitted";

  /** Build a compact post-response summary from status history + data signals. */
  const postResponseSummary = (() => {
    if (!hasStatusHistory || status !== "complete") return null;
    const lastPhase = streamStatusLabels?.[statusHistory[statusHistory.length - 1]];
    const parts: string[] = [];
    if (lastPhase) parts.push(lastPhase.replace(/\.\.\.$/, ""));
    if (citations && citations.length > 0) parts.push(`${citations.length} ${sourcesLabel?.toLowerCase() ?? "sources"}`);
    if (places && places.length > 0) parts.push(`${places.length} places`);
    if (fallback) parts.push("fallback");
    if (cacheHit) parts.push("cache");
    return parts.length > 0 ? parts.join(" · ") : null;
  })();

  return (
    <article className={`flex gap-2.5 animate-slideUp transition-all duration-200 sm:gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Compact avatar — distinct per role */}
      <div
        className={`mt-1 grid size-7 shrink-0 place-items-center rounded-full shadow-sm ring-1 transition-colors sm:size-8 ${
          isUser
            ? "bg-[#0b5f63] text-white ring-[#0b5f63]/20"
            : "bg-[#fffaf0] text-[#0b5f63] ring-[#0b5f63]/15"
        }`}
        aria-hidden="true"
      >
        {isUser ? <UserRound className="size-3.5 sm:size-4" /> : <Bot className="size-3.5 sm:size-4" />}
      </div>

      <div className={`flex min-w-0 max-w-[86%] flex-col md:max-w-[74%] ${isUser ? "items-end" : "items-start"}`}>
        {/* Sender label + status badge */}
        <div className={`mb-1 flex items-center gap-2 text-[0.7rem] ${isUser ? "justify-end text-[#0b5f63]" : "text-[#4d6868]"}`}>
          <span className="font-semibold">{isUser ? userLabel : assistantLabel}</span>
          {showComplete && hasSources && (
            <span className="inline-flex items-center gap-1 text-[#6b7f7e]">
              <CheckCircle2 className="size-3" />
              {`${citations!.length} ${sourcesLabel.toLowerCase()}`}
            </span>
          )}
        </div>

        {/* Message bubble — visibly distinct left/right styles */}
        <div
          className={`group relative rounded-[1.35rem] px-3.5 py-2.5 shadow-sm transition-shadow duration-200 hover:shadow-md sm:rounded-[1.45rem] sm:px-4 sm:py-3 ${
            isUser
              ? "rounded-tr-md bg-gradient-to-br from-[#0b5f63] to-[#0d7a7e] text-white shadow-[#0b5f63]/20"
              : "rounded-tl-md border border-white/80 bg-[#fffdf8]/92 text-[#173a3b] shadow-slate-900/8 backdrop-blur"
          }`}
        >
          <div className={`whitespace-pre-wrap text-[0.9rem] leading-6 sm:text-[0.95rem] sm:leading-7 ${isUser ? "text-white" : ""}`}>
            {content || (
              <span className="inline-flex items-center gap-2 text-[#4d6868]">
                <TypingDots />
                <span className="text-sm">{typingLabel}</span>
              </span>
            )}
            {!isUser && status === "streaming" && content && (
              <span className="ml-1 inline-block h-4 w-0.5 translate-y-0.5 animate-blink rounded-full bg-[#0b5f63]" aria-hidden="true" />
            )}
          </div>

          {/* Hover actions — copy, retry */}
          {!isUser && !isPending && content && (
            <div className="absolute -bottom-3 right-3 rounded-full border border-slate-200 bg-white opacity-0 shadow-sm transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100">
              <MessageActions content={content} onRetry={onRetry} translations={actionTranslations} />
            </div>
          )}

          {/* Guardrail/fallback/trace badges */}
          {!isUser && (guardrailStatus || fallback || langfuseTraceId || cacheHit) && (
            <AccessibilityBadge
              guardrailStatus={guardrailStatus}
              fallback={fallback}
              langfuseTraceId={langfuseTraceId}
              cacheHit={cacheHit}
            />
          )}
        </div>

        {/* Thinking timeline — shown during streaming and retained after completion */}
        {!isUser && hasStatusHistory && streamStatusLabels && (
          <div
            className={`mt-2 rounded-xl border px-2.5 py-1.5 text-[0.6rem] transition-colors sm:px-3 sm:py-2 ${
              isStreaming
                ? "border-[#0b5f63]/15 bg-[#0b5f63]/5 text-[#4d6868]"
                : "border-slate-200/60 bg-white/50 text-[#6b7f7e]"
            }`}
            aria-label="Processing steps"
          >
            <div className="flex items-center gap-1.5">
              {isStreaming && <Loader2 className="size-2.5 animate-spin shrink-0" />}
              <span className="font-semibold uppercase tracking-wider opacity-70">
                {isStreaming ? "Processing" : "Completed via"}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-1 gap-y-0.5">
              {statusHistory.map((s, i) => (
                <span key={`${s}-${i}`} className="inline-flex items-center gap-1">
                  {i > 0 && <ArrowRight className="size-2 opacity-40" />}
                  <span>{streamStatusLabels[s]?.replace(/\.\.\.$/, "") ?? s}</span>
                </span>
              ))}
            </div>
            {postResponseSummary && (
              <div className="mt-1.5 border-t border-current/10 pt-1.5 text-[0.55rem] opacity-70">
                {postResponseSummary}
              </div>
            )}
          </div>
        )}

        {/* Citations — collapsible sources drawer */}
        {!isUser && hasSources && (
          <details className="mt-3 max-w-full rounded-2xl border border-[#0b5f63]/10 bg-white/65 p-2 shadow-sm" aria-label={sourcesLabel}>
            <summary className="cursor-pointer list-none rounded-xl px-2 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-[#0b5f63] transition-colors hover:bg-white/70">
              {sourcesLabel} ({citations!.length})
            </summary>
            <div className="mt-2 grid max-w-full gap-2 overflow-hidden">
              {citations!.map((citation, i) => (
                <CitationCard key={`${citation.source}-${i}`} citation={citation} index={i + 1} />
              ))}
            </div>
          </details>
        )}

        {/* Place cards — bounded at top 5 */}
        {!isUser && places && places.length > 0 && placeTranslations && (
          <section className="mt-3 rounded-2xl border border-[#0b5f63]/10 bg-white/65 p-3 shadow-sm" role="region" aria-label={placeTranslations.placeResultsHeading}>
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#0b5f63]">
              {placeTranslations.placeResultsHeading}
            </p>
            <div className="flex gap-2 overflow-x-auto pb-2" aria-label={placeTranslations.placeResultsHeading}>
              {places.slice(0, 5).map((place) => (
                <PlaceCard key={place.place_id} place={place} translations={placeTranslations} />
              ))}
            </div>
          </section>
        )}
      </div>
    </article>
  );
}

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1" aria-hidden="true">
      <span className="h-1.5 w-1.5 rounded-full bg-[#0b5f63]/70 animate-bounce" style={{ animationDelay: "0ms" }} />
      <span className="h-1.5 w-1.5 rounded-full bg-[#0b5f63]/70 animate-bounce" style={{ animationDelay: "150ms" }} />
      <span className="h-1.5 w-1.5 rounded-full bg-[#0b5f63]/70 animate-bounce" style={{ animationDelay: "300ms" }} />
    </span>
  );
}
