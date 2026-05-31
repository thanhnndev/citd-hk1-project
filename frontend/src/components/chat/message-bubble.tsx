"use client";

import { CitationCard } from "./citation-card";
import { PlaceCard } from "./place-card";
import { MessageActions } from "./message-actions";
import { AccessibilityBadge } from "@/components/reasoning/accessibility-badge";
import { Bot, CheckCircle2, Clock3, Loader2, UserRound } from "lucide-react";
import type { Citation, PlaceResult } from "@/lib/chat-api";

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
  placeTranslations,
  actionTranslations,
  onRetry,
}: MessageBubbleProps) {
  const isUser = role === "user";
  const isPending = !content;
  const hasSources = Boolean(citations?.length);
  const showComplete = !isUser && status === "complete" && content;

  return (
    <article className={`flex gap-3 animate-slideUp ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <div
        className={`mt-1 grid size-8 shrink-0 place-items-center rounded-full shadow-sm ${
          isUser ? "bg-[#0b5f63] text-white" : "bg-[#fffaf0] text-[#0b5f63] ring-1 ring-[#0b5f63]/15"
        }`}
        aria-hidden="true"
      >
        {isUser ? <UserRound className="size-4" /> : <Bot className="size-4" />}
      </div>

      <div className={`min-w-0 max-w-[86%] md:max-w-[74%] ${isUser ? "items-end" : "items-start"}`}>
        <div className={`mb-1 flex items-center gap-2 text-[0.72rem] ${isUser ? "justify-end text-[#0b5f63]" : "text-[#4d6868]"}`}>
          <span className="font-semibold">{isUser ? userLabel : assistantLabel}</span>
          {!isUser && status !== "complete" && (
            <span className="inline-flex items-center gap-1 rounded-full bg-[#0b5f63]/8 px-2 py-0.5 text-[#0b5f63]">
              {status === "submitted" ? <Clock3 className="size-3" /> : <Loader2 className="size-3 animate-spin" />}
              {streamStatusLabel ?? typingLabel}
            </span>
          )}
          {showComplete && hasSources && (
            <span className="inline-flex items-center gap-1 text-[#6b7f7e]">
              <CheckCircle2 className="size-3" />
              {`${citations!.length} ${sourcesLabel.toLowerCase()}`}
            </span>
          )}
        </div>

        <div
          className={`group relative rounded-[1.45rem] px-4 py-3 shadow-sm ${
            isUser
              ? "rounded-tr-md bg-[#0b5f63] text-white shadow-[#0b5f63]/15"
              : "rounded-tl-md border border-white/80 bg-[#fffdf8]/92 text-[#173a3b] shadow-slate-900/8 backdrop-blur"
          }`}
        >
          <div className={`whitespace-pre-wrap text-[0.95rem] leading-7 ${isUser ? "text-white" : ""}`}>
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

          {!isUser && !isPending && content && (
            <div className="absolute -bottom-3 right-3 rounded-full border border-slate-200 bg-white opacity-0 shadow-sm transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100">
              <MessageActions content={content} onRetry={onRetry} translations={actionTranslations} />
            </div>
          )}

          {!isUser && (guardrailStatus || fallback || langfuseTraceId || cacheHit) && (
            <AccessibilityBadge
              guardrailStatus={guardrailStatus}
              fallback={fallback}
              langfuseTraceId={langfuseTraceId}
              cacheHit={cacheHit}
            />
          )}
        </div>

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
    <span className="inline-flex gap-1 items-center" aria-hidden="true">
      <span className="h-1.5 w-1.5 rounded-full bg-[#0b5f63]/70 animate-bounce" style={{ animationDelay: "0ms" }} />
      <span className="h-1.5 w-1.5 rounded-full bg-[#0b5f63]/70 animate-bounce" style={{ animationDelay: "150ms" }} />
      <span className="h-1.5 w-1.5 rounded-full bg-[#0b5f63]/70 animate-bounce" style={{ animationDelay: "300ms" }} />
    </span>
  );
}
