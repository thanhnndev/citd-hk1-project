"use client";

import { CitationCard } from "./citation-card";
import type { Citation } from "@/lib/chat-api";

interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  typingLabel?: string;
}

export function MessageBubble({
  role,
  content,
  citations,
  typingLabel = "Thinking...",
}: MessageBubbleProps) {
  const isUser = role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] md:max-w-[75%] rounded-2xl px-4 py-3 ${
          isUser
            ? "bg-primary text-primary-foreground rounded-br-sm"
            : "bg-muted rounded-bl-sm"
        }`}
      >
        {/* Content */}
        <div className={`whitespace-pre-wrap text-sm leading-relaxed ${isUser ? "text-primary-foreground" : ""}`}>
          {content || (
            <span className="inline-flex gap-1 items-center">
              <TypingDots />
              <span className="ml-1 text-xs text-muted-foreground">{typingLabel}</span>
            </span>
          )}
        </div>

        {/* Citations — only for assistant messages */}
        {!isUser && citations && citations.length > 0 && (
          <div className="mt-3 space-y-2">
            {citations.map((citation, i) => (
              <CitationCard key={i} citation={citation} />
            ))}
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
