import { useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { PlaceCard } from "./place-card";
import { MessageActions } from "./message-actions";
import { ReasoningLog } from "@/components/reasoning/reasoning-log";
import {
  Bot,
  CheckCircle2,
  Clock3,
  Loader2,
  UserRound,
  FileText,
  MapPinned,
  ThumbsUp,
  ThumbsDown,
} from "lucide-react";
import type { ChatStreamStatus, Citation, PlaceResult } from "@/lib/chat-api";
import { submitFeedback } from "@/lib/chat-api";

const markdownComponents: Components = {
  p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
  strong: ({ children }) => (
    <strong className="font-semibold text-current">{children}</strong>
  ),
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => (
    <ul className="my-3 space-y-2 pl-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="my-3 space-y-2 pl-0">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="list-none rounded-xl border border-[#e9e9e7] bg-[#fbfaf7] px-3 py-2 shadow-sm">
      {children}
    </li>
  ),
  h1: ({ children }) => (
    <h3 className="mb-2 mt-4 text-lg font-semibold">{children}</h3>
  ),
  h2: ({ children }) => (
    <h3 className="mb-2 mt-4 text-base font-semibold">{children}</h3>
  ),
  h3: ({ children }) => (
    <h4 className="mb-2 mt-3 font-semibold">{children}</h4>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-[#2383e2] pl-3 text-[#5f5e5b]">
      {children}
    </blockquote>
  ),
  code: ({ className, children }) =>
    className ? (
      <code className="block overflow-x-auto rounded-lg bg-[#f7f7f5] p-3 font-mono text-xs">
        {children}
      </code>
    ) : (
      <code className="rounded bg-[#f7f7f5] px-1.5 py-0.5 font-mono text-[0.9em]">
        {children}
      </code>
    ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="font-medium text-[#2383e2] underline underline-offset-2"
    >
      {children}
    </a>
  ),
};

export type MessageStatus = "submitted" | "streaming" | "complete";

function normalizeStreamStatus(status: ChatStreamStatus): string {
  if (status.startsWith("gathering:")) return status;
  return status.split(":")[0];
}

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
  onOpenPlacesPanel?: () => void;
  onOpenSourcesPanel?: () => void;
  /** Unique message identifier for feedback tracking. */
  messageId?: string;
  /** Session ID for feedback context. */
  sessionId?: string;
  /** Turn index in conversation. */
  turnIndex?: number;
  reasoningLog?: string | null;
  locale?: string;
  streamStatus?: ChatStreamStatus | null;
  responseTimeMs?: number;
  responseTimeLabel?: string;
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
  guardrailStatus: _guardrailStatus,
  fallback: _fallback,
  langfuseTraceId: _langfuseTraceId,
  cacheHit: _cacheHit,
  statusHistory,
  streamStatusLabels,
  placeTranslations,
  actionTranslations,
  onRetry,
  onOpenPlacesPanel,
  onOpenSourcesPanel,
  messageId,
  sessionId,
  turnIndex,
  reasoningLog,
  locale,
  streamStatus,
  responseTimeMs,
  responseTimeLabel = "Response time",
}: MessageBubbleProps) {
  const isUser = role === "user";
  const isPending = !content;
  const hasSources = Boolean(citations?.length);
  const showComplete = !isUser && status === "complete" && content;
  const isStreaming = status === "streaming" || status === "submitted";
  const formattedResponseTime =
    typeof responseTimeMs === "number" && Number.isFinite(responseTimeMs) && responseTimeMs >= 0
      ? responseTimeMs < 1000
        ? `${Math.round(responseTimeMs)} ms`
        : `${(responseTimeMs / 1000).toFixed(2)} s`
      : null;
  const [showAllPlaces, setShowAllPlaces] = useState(false);
  const [feedbackState, setFeedbackState] = useState<"like" | "dislike" | null>(null);
  const [showReasonInput, setShowReasonInput] = useState(false);
  const [reason, setReason] = useState("");

  const handleFeedback = async (type: "like" | "dislike") => {
    if (!messageId) return;
    
    // Toggle off if clicking same button
    if (feedbackState === type) {
      setFeedbackState(null);
      setShowReasonInput(false);
      return;
    }
    
    // If switching to dislike, show reason input
    if (type === "dislike") {
      setFeedbackState("dislike");
      setShowReasonInput(true);
      return;
    }
    
    // Submit like immediately
    setFeedbackState("like");
    setShowReasonInput(false);
    
    try {
      await submitFeedback({
        message_id: messageId,
        feedback_type: "like",
        session_id: sessionId ?? null,
        turn_index: turnIndex ?? null,
        message_content: content.slice(0, 200),
      });
    } catch (err) {
      console.error("Failed to submit feedback:", err);
    }
  };

  const submitReasonFeedback = async () => {
    if (!messageId) return;
    
    try {
      await submitFeedback({
        message_id: messageId,
        feedback_type: "dislike",
        reason: reason || null,
        session_id: sessionId ?? null,
        turn_index: turnIndex ?? null,
        message_content: content.slice(0, 200),
      });
    } catch (err) {
      console.error("Failed to submit feedback:", err);
    }
    
    setShowReasonInput(false);
    setReason("");
  };

  return (
    <article
      className={`flex gap-3 animate-slideUp transition-all duration-200 ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      {/* Compact avatar — distinct per role */}
      <div
        className={`mt-1 grid size-7 shrink-0 place-items-center rounded-full shadow-sm ring-1 transition-colors sm:size-8 ${
          isUser
            ? "bg-[#2b7a78] text-white ring-[#2b7a78]/20"
            : "rounded-lg bg-[#2383e2] text-white ring-[#2383e2]/20"
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
        className={`flex min-w-0 max-w-[88%] flex-col md:max-w-[82%] ${isUser ? "items-end" : "items-start"}`}
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
          className={`group relative px-4 py-3 shadow-sm transition-shadow duration-200 hover:shadow-md sm:px-5 sm:py-4 ${
            isUser
              ? "rounded-2xl rounded-tr-sm bg-[#f0f0f0] text-[#37352f]"
              : "rounded-xl border border-[#e9e9e7] bg-white text-[#37352f]"
          }`}
        >
          <div
            className={`text-[0.9rem] leading-6 sm:text-[0.95rem] sm:leading-7 ${isUser ? "whitespace-pre-wrap" : ""}`}
          >
            {content ? (
              isUser ? (
                content
              ) : (
                <RichMessageContent content={content} citations={citations} />
              )
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

          {!isUser && status === "complete" && formattedResponseTime && (
            <div className="mt-3 flex items-center gap-1.5 border-t border-[#e9e9e7] pt-2 text-[0.7rem] font-medium text-[#6b7f7e]">
              <Clock3 className="size-3" aria-hidden="true" />
              <span>{responseTimeLabel}: {formattedResponseTime}</span>
            </div>
          )}

          {/* Hover actions — copy, retry, feedback */}
          {!isUser && !isPending && content && (
            <div className="absolute -bottom-9 right-3 flex items-center gap-2 rounded-md border border-[#e9e9e7] bg-white px-2 py-1 shadow-sm">
              <MessageActions
                content={content}
                onRetry={onRetry}
                translations={actionTranslations}
              />
              {messageId && status === "complete" && (
                <div className="flex items-center gap-1 border-l border-[#e9e9e7] pl-2">
                  <button
                    type="button"
                    onClick={() => handleFeedback("like")}
                    className={`rounded p-1 transition-colors ${
                      feedbackState === "like"
                        ? "text-[#0b5f63] bg-[#0b5f63]/10"
                        : "text-[#6b7f7e] hover:text-[#0b5f63] hover:bg-[#0b5f63]/5"
                    }`}
                    aria-label="Like this response"
                    title="Phản hồi hữu ích"
                  >
                    <ThumbsUp className="size-3.5" fill={feedbackState === "like" ? "currentColor" : "none"} />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleFeedback("dislike")}
                    className={`rounded p-1 transition-colors ${
                      feedbackState === "dislike"
                        ? "text-[#b45a5a] bg-[#b45a5a]/10"
                        : "text-[#6b7f7e] hover:text-[#b45a5a] hover:bg-[#b45a5a]/5"
                    }`}
                    aria-label="Dislike this response"
                    title="Phản hồi chưa tốt"
                  >
                    <ThumbsDown className="size-3.5" fill={feedbackState === "dislike" ? "currentColor" : "none"} />
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Optional reason input for dislike */}
          {showReasonInput && (
            <div className="absolute -bottom-20 right-3 z-10 flex items-center gap-2 rounded-md border border-[#e9e9e7] bg-white px-3 py-2 shadow-md">
              <input
                type="text"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Lý do (không bắt buộc)..."
                className="w-48 rounded border border-[#e9e9e7] px-2 py-1 text-xs focus:border-[#0b5f63] focus:outline-none"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    submitReasonFeedback();
                  } else if (e.key === "Escape") {
                    setShowReasonInput(false);
                    setReason("");
                  }
                }}
                autoFocus
              />
              <button
                type="button"
                onClick={submitReasonFeedback}
                className="rounded bg-[#0b5f63] px-2 py-1 text-xs text-white hover:bg-[#0b5f63]/90"
              >
                Gửi
              </button>
            </div>
          )}

          {/* Technical badges removed for end-user view */}
        </div>

        {!isUser && status === "complete" && (hasSources || (places && places.length > 0)) && (
          <div className="mt-2 flex flex-wrap gap-2">
            {places && places.length > 0 && (
              <button
                type="button"
                onClick={onOpenPlacesPanel}
                className="inline-flex items-center gap-1.5 rounded-full border border-[#2383e2]/20 bg-[#2383e2]/8 px-3 py-1.5 text-xs font-semibold text-[#0b5f63] hover:bg-[#2383e2]/12"
              >
                <MapPinned className="size-3.5" />
                {placeTranslations?.placeResultsHeading ?? "Map"} ({places.length})
              </button>
            )}
            {hasSources && (
              <button
                type="button"
                onClick={onOpenSourcesPanel}
                className="inline-flex items-center gap-1.5 rounded-full border border-[#2383e2]/20 bg-[#f7f7f5] px-3 py-1.5 text-xs font-semibold text-[#37352f] hover:bg-[#efefed]"
              >
                <FileText className="size-3.5" />
                {sourcesLabel} ({citations!.length})
              </button>
            )}
          </div>
        )}

        {/* Semantic run progress. Responsible-AI controls remain implementation policy, not UI steps. */}
        {!isUser && isStreaming && (
          <div
            className="mt-3 w-full rounded-xl border border-[#e9e9e7] bg-[#fbfaf7] px-4 py-3"
            role="status"
            aria-live="polite"
          >
            <div className="flex items-center gap-2 text-sm font-medium text-[#123436]">
              <Loader2 className="size-4 animate-spin text-[#0b5f63]" aria-hidden="true" />
              <span>{streamStatusLabel ?? typingLabel}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {(statusHistory ?? [])
                .filter((item, index, items) => {
                  const normalized = normalizeStreamStatus(item);
                  const current = streamStatus ? normalizeStreamStatus(streamStatus) : null;
                  return normalized !== current && items.findIndex(
                    (candidate) => normalizeStreamStatus(candidate) === normalized,
                  ) === index;
                })
                .slice(-3)
                .map((item) => (
                  <span
                    key={item}
                    className="inline-flex items-center gap-1 text-xs text-[#5d7373]"
                  >
                    <CheckCircle2 className="size-3 text-emerald-600" aria-hidden="true" />
                    {streamStatusLabels?.[item] ?? item}
                  </span>
                ))}
            </div>
          </div>
        )}

        {/* Reasoning log / Explainability for completed assistant responses */}
        {!isUser && status === "complete" && reasoningLog && (
          <div className="w-full max-w-none">
            <ReasoningLog
              reasoningLog={reasoningLog}
              locale={locale}
            />
          </div>
        )}

        {/* Place cards — curated first, with progressive disclosure for more results. */}
        {!isUser && places && places.length > 0 && placeTranslations && (
          <section
            className="mt-3 max-w-full overflow-hidden rounded-xl border border-[#e9e9e7] bg-white p-3 shadow-sm lg:hidden"
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

function RichMessageContent({
  content,
  citations,
}: {
  content: string;
  citations?: Citation[];
}) {
  return (
    <div className="max-w-none text-[#37352f] [&_p:empty]:hidden">
      <ReactMarkdown components={markdownComponents}>
        {transformCitationMarkers(normalizeAssistantMarkdown(content), citations)}
      </ReactMarkdown>
    </div>
  );
}

function normalizeAssistantMarkdown(content: string) {
  return content
    .replace(/\r\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/^\s*[-*]\s*$/gm, "")
    .trim();
}

function transformCitationMarkers(content: string, citations?: Citation[]) {
  if (!citations?.length) return content;

  return content.replace(/\[(\d+)\]/g, (marker, rawIndex: string) => {
    const index = Number(rawIndex) - 1;
    const citation = citations[index];
    if (!citation) return marker;
    return `[${rawIndex}](${citation.url || `#${citationAnchorId(index)}`})`;
  });
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
