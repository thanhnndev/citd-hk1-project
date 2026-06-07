"use client";

import { useState } from "react";
import { CitationCard } from "./citation-card";
import { PlaceCard } from "./place-card";
import { MessageActions } from "./message-actions";
import { AccessibilityBadge } from "@/components/reasoning/accessibility-badge";
import {
  Bot,
  CheckCircle2,
  Loader2,
  UserRound,
  ArrowRight,
} from "lucide-react";
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
  streamStatusLabel: _streamStatusLabel,
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
  const [showAllPlaces, setShowAllPlaces] = useState(false);

  /** Build a compact post-response summary from status history + data signals. */
  const postResponseSummary = (() => {
    if (!hasStatusHistory || status !== "complete") return null;
    const lastPhase =
      streamStatusLabels?.[statusHistory[statusHistory.length - 1]];
    const parts: string[] = [];
    if (lastPhase) parts.push(lastPhase.replace(/\.\.\.$/, ""));
    if (citations && citations.length > 0)
      parts.push(
        `${citations.length} ${sourcesLabel?.toLowerCase() ?? "sources"}`,
      );
    if (places && places.length > 0) parts.push(`${places.length} places`);
    if (fallback) parts.push("fallback");
    if (cacheHit) parts.push("cache");
    return parts.length > 0 ? parts.join(" · ") : null;
  })();

  return (
    <article
      className={`flex gap-2.5 animate-slideUp transition-all duration-200 sm:gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      {/* Compact avatar — distinct per role */}
      <div
        className={`mt-1 grid size-7 shrink-0 place-items-center rounded-full shadow-sm ring-1 transition-colors sm:size-8 ${
          isUser
            ? "bg-[#0b5f63] text-white ring-[#0b5f63]/20"
            : "bg-[#fffaf0] text-[#0b5f63] ring-[#0b5f63]/15"
        }`}
        aria-hidden="true"
      >
        {isUser ? (
          <UserRound className="size-3.5 sm:size-4" />
        ) : (
          <Bot className="size-3.5 sm:size-4" />
        )}
      </div>

      <div
        className={`flex min-w-0 max-w-[86%] flex-col md:max-w-[74%] ${isUser ? "items-end" : "items-start"}`}
      >
        {/* Sender label + status badge */}
        <div
          className={`mb-1 flex items-center gap-2 text-[0.7rem] ${isUser ? "justify-end text-[#0b5f63]" : "text-[#4d6868]"}`}
        >
          <span className="font-semibold">
            {isUser ? userLabel : assistantLabel}
          </span>
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
          <div
            className={`whitespace-pre-wrap text-[0.9rem] leading-6 sm:text-[0.95rem] sm:leading-7 ${isUser ? "text-white" : ""}`}
          >
            {content ? (
              <RichMessageContent
                content={content}
                citations={isUser ? undefined : citations}
              />
            ) : (
              <span className="inline-flex items-center gap-2 text-[#4d6868]">
                <TypingDots />
                <span className="text-sm">{typingLabel}</span>
              </span>
            )}
            {!isUser && status === "streaming" && content && (
              <span
                className="ml-1 inline-block h-4 w-0.5 translate-y-0.5 animate-blink rounded-full bg-[#0b5f63]"
                aria-hidden="true"
              />
            )}
          </div>

          {/* Hover actions — copy, retry */}
          {!isUser && !isPending && content && (
            <div className="absolute -bottom-3 right-3 rounded-full border border-slate-200 bg-white opacity-0 shadow-sm transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100">
              <MessageActions
                content={content}
                onRetry={onRetry}
                translations={actionTranslations}
              />
            </div>
          )}

          {/* Guardrail/fallback/trace badges */}
          {!isUser &&
            (guardrailStatus || fallback || langfuseTraceId || cacheHit) && (
              <AccessibilityBadge
                guardrailStatus={guardrailStatus}
                fallback={fallback}
                langfuseTraceId={langfuseTraceId}
                cacheHit={cacheHit}
              />
            )}
        </div>

        {/* Thinking timeline — useful while waiting, hidden after completion for end users. */}
        {!isUser && isStreaming && hasStatusHistory && streamStatusLabels && (
          <div
            className={`mt-2 rounded-xl border px-2.5 py-1.5 text-[0.6rem] transition-colors sm:px-3 sm:py-2 ${
              isStreaming
                ? "border-[#0b5f63]/15 bg-[#0b5f63]/5 text-[#4d6868]"
                : "border-slate-200/60 bg-white/50 text-[#6b7f7e]"
            }`}
            aria-label="Processing steps"
          >
            <div className="flex items-center gap-1.5">
              {isStreaming && (
                <Loader2 className="size-2.5 animate-spin shrink-0" />
              )}
              <span className="font-semibold uppercase tracking-wider opacity-70">
                {isStreaming ? "Processing" : "Completed via"}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-1 gap-y-0.5">
              {statusHistory.map((s, i) => (
                <span
                  key={`${s}-${i}`}
                  className="inline-flex items-center gap-1"
                >
                  {i > 0 && <ArrowRight className="size-2 opacity-40" />}
                  <span>
                    {streamStatusLabels[s]?.replace(/\.\.\.$/, "") ?? s}
                  </span>
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
          <details
            className="mt-3 max-w-full rounded-2xl border border-[#0b5f63]/10 bg-white/65 p-2 shadow-sm"
            aria-label={sourcesLabel}
          >
            <summary className="cursor-pointer list-none rounded-xl px-2 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-[#0b5f63] transition-colors hover:bg-white/70">
              {sourcesLabel} ({citations!.length})
            </summary>
            <div className="mt-2 grid max-w-full gap-2 overflow-hidden">
              {citations!.map((citation, i) => (
                <div key={`${citation.source}-${i}`} id={citationAnchorId(i)}>
                  <CitationCard citation={citation} index={i + 1} />
                </div>
              ))}
            </div>
          </details>
        )}

        {/* Place cards — curated first, with progressive disclosure for more results. */}
        {!isUser && places && places.length > 0 && placeTranslations && (
          <section
            className="mt-3 max-w-full overflow-hidden rounded-3xl border border-[#0b5f63]/10 bg-white/72 p-3 shadow-sm"
            role="region"
            aria-label={placeTranslations.placeResultsHeading}
          >
            <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#0b5f63]">
                  {placeTranslations.placeResultsHeading}
                </p>
                <p className="mt-1 text-xs text-[#5d7373]">
                  {places.length > 3
                    ? `Hiển thị 3 gợi ý nổi bật trước, còn ${places.length - 3} địa điểm trong danh sách mở rộng.`
                    : "Các gợi ý đã được rút gọn để bạn dễ chọn."}
                </p>
              </div>
              {places.length > 3 && (
                <button
                  type="button"
                  onClick={() => setShowAllPlaces((value) => !value)}
                  className="rounded-full border border-[#0b5f63]/20 bg-white px-3 py-1.5 text-xs font-semibold text-[#0b5f63] shadow-sm hover:bg-[#0b5f63]/8"
                >
                  {showAllPlaces ? "Thu gọn" : `Xem thêm ${places.length - 3}`}
                </button>
              )}
            </div>
            <div className="grid max-w-full gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label={placeTranslations.placeResultsHeading}>
              {places.slice(0, showAllPlaces ? places.length : 3).map((place, index) => (
                <PlaceCard
                  key={place.place_id}
                  place={place}
                  rank={index + 1}
                  translations={placeTranslations}
                />
              ))}
            </div>
          </section>
        )}
      </div>
    </article>
  );
}

function citationAnchorId(index: number) {
  return `source-${index + 1}`;
}

import ReactMarkdown from "react-markdown";

function RichMessageContent({
  content,
  citations,
}: {
  content: string;
  citations?: Citation[];
}) {
  let processedContent = content;
  if (citations?.length) {
    processedContent = content.replace(/\[(\d+)\]/g, (match, d) => {
      const citationIndex = Number(d) - 1;
      const citation = citations[citationIndex];
      if (!citation) return match;
      if (citation.url) {
        return `[${match}](${citation.url})`;
      }
      return `[${match}](#${citationAnchorId(citationIndex)})`;
    });
  }

  return (
    <div className="[&_p]:mb-2 [&_p:last-child]:mb-0 [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_strong]:font-bold">
      <ReactMarkdown
        components={{
          a: ({ node: _node, ...props }) => {
            const text = String(props.children);
            const isCitation = /^\[\d+\]$/.test(text);
            if (isCitation) {
              return (
                <a
                  {...props}
                  className="mx-0.5 inline-flex translate-y-[-0.08em] items-center rounded-full border border-[#0b5f63]/20 bg-[#0b5f63]/8 px-1.5 py-0.5 text-[0.68em] font-bold leading-none text-[#0b5f63] underline-offset-2 transition-colors hover:border-[#0b5f63]/40 hover:bg-[#0b5f63]/14 focus:outline-none focus:ring-2 focus:ring-[#0b5f63]/25"
                  target={props.href?.startsWith("#") ? undefined : "_blank"}
                  rel={props.href?.startsWith("#") ? undefined : "noopener noreferrer"}
                />
              );
            }
            return (
              <a
                {...props}
                className="text-[#0b5f63] underline underline-offset-2"
                target="_blank"
                rel="noopener noreferrer"
              />
            );
          },
        }}
      >
        {processedContent}
      </ReactMarkdown>
    </div>
  );
}

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1" aria-hidden="true">
      <span
        className="h-1.5 w-1.5 rounded-full bg-[#0b5f63]/70 animate-bounce"
        style={{ animationDelay: "0ms" }}
      />
      <span
        className="h-1.5 w-1.5 rounded-full bg-[#0b5f63]/70 animate-bounce"
        style={{ animationDelay: "150ms" }}
      />
      <span
        className="h-1.5 w-1.5 rounded-full bg-[#0b5f63]/70 animate-bounce"
        style={{ animationDelay: "300ms" }}
      />
    </span>
  );
}
