"use client";

import { CitationCard } from "./citation-card";
import { PlaceCard } from "./place-card";
import { MessageActions } from "./message-actions";
import { AccessibilityBadge } from "@/components/reasoning/accessibility-badge";
import type { Citation, PlaceResult } from "@/lib/chat-api";

interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  places?: PlaceResult[];
  typingLabel?: string;
  guardrailStatus?: string;
  fallback?: boolean;
  langfuseTraceId?: string | null;
  cacheHit?: boolean;
  placeTranslations?: {
    placeResultsHeading: string;
    viewOnMap: string;
    scoreLabel: string;
    noRating: string;
  };
  onRetry?: () => void;
}

export function MessageBubble({
  role,
  content,
  citations,
  places,
  typingLabel = "Thinking...",
  guardrailStatus,
  fallback,
  langfuseTraceId,
  cacheHit,
  placeTranslations,
  onRetry,
}: MessageBubbleProps) {
  const isUser = role === "user";
  const isStreaming = !content;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} animate-slideUp`}>
      <div
        className={`group relative max-w-[92%] rounded-[1.5rem] px-4 py-3 shadow-sm md:max-w-[74%] ${
          isUser
            ? "rounded-br-md bg-[#0b5f63] text-white shadow-[#0b5f63]/15"
            : "rounded-bl-md border border-white/70 bg-white/88 text-foreground shadow-slate-900/8 backdrop-blur"
        }`}
      >
        {/* Content */}
        <div className={`whitespace-pre-wrap text-[0.95rem] leading-7 ${isUser ? "text-white" : ""}`}>
          {content || (
            <span className="inline-flex gap-1 items-center">
              <TypingDots />
              <span className="ml-1 text-xs text-muted-foreground">{typingLabel}</span>
              {/* Streaming cursor */}
              <span className="inline-block w-0.5 h-4 bg-primary animate-blink ml-0.5" aria-hidden="true" />
            </span>
          )}
        </div>

        {/* Message actions — hover-revealed for assistant messages with content */}
        {!isUser && !isStreaming && content && (
          <div className="absolute -right-1 -bottom-1 translate-x-full translate-y-1/2">
            <MessageActions content={content} onRetry={onRetry} />
          </div>
        )}

        {/* Accessibility badges — only for assistant messages with status info */}
        {!isUser && (guardrailStatus || fallback || langfuseTraceId || cacheHit) && (
          <AccessibilityBadge
            guardrailStatus={guardrailStatus}
            fallback={fallback}
            langfuseTraceId={langfuseTraceId}
            cacheHit={cacheHit}
          />
        )}

        {/* Citations — only for assistant messages */}
        {!isUser && citations && citations.length > 0 && (
          <div className="mt-4 space-y-2 border-t border-slate-200/70 pt-3">
            {citations.map((citation, i) => (
              <CitationCard key={i} citation={citation} />
            ))}
          </div>
        )}

        {/* Place cards — only for assistant messages with places */}
        {!isUser && places && places.length > 0 && placeTranslations && (
          <div className="mt-4 border-t border-slate-200/70 pt-3" role="region" aria-label={placeTranslations.placeResultsHeading}>
            <p className="text-xs font-medium text-muted-foreground mb-2">
              {placeTranslations.placeResultsHeading}
            </p>
            <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-thin" aria-label={placeTranslations.placeResultsHeading}>
              {places.slice(0, 5).map((place) => (
                <PlaceCard key={place.place_id} place={place} translations={placeTranslations} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Simple three-dot typing animation */
function TypingDots() {
  return (
    <span className="inline-flex gap-1 items-center" aria-hidden="true">
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60 animate-bounce" style={{ animationDelay: "0ms" }} />
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60 animate-bounce" style={{ animationDelay: "150ms" }} />
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60 animate-bounce" style={{ animationDelay: "300ms" }} />
    </span>
  );
}
