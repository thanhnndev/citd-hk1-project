"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { MessageBubble } from "./message-bubble";
import { sendChat, type ChatResponse, type Citation } from "@/lib/chat-api";
import { ArrowUp, RotateCcw, Loader2 } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}

interface ChatInterfaceProps {
  locale: string;
  translations: {
    title: string;
    placeholder: string;
    send: string;
    typing: string;
    error: string;
    retry: string;
    citations: string;
    noEvidence: string;
    newQuestion: string;
  };
}

export function ChatInterface({ locale, translations }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId] = useState(() => crypto.randomUUID());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const language = (locale === "en" ? "en" : "vi") as "vi" | "en";

  const handleSubmit = useCallback(
    async (overrideMessage?: string) => {
      const messageText = overrideMessage ?? input.trim();
      if (!messageText || loading) return;

      setError(null);
      setLoading(true);

      // Append user message immediately
      const userMsg: Message = { role: "user", content: messageText };
      setMessages((prev) => [...prev, userMsg]);
      setInput("");

      try {
        const response: ChatResponse = await sendChat(messageText, sessionId, language);

        // Determine display text — use noEvidence fallback when message is empty
        const displayText =
          response.message && response.message.trim()
            ? response.message
            : translations.noEvidence;

        const assistantMsg: Message = {
          role: "assistant",
          content: displayText,
          citations: response.citations ?? [],
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : translations.error;
        setError(errorMessage);
      } finally {
        setLoading(false);
      }
    },
    [input, loading, sessionId, language, translations],
  );

  const handleRetry = useCallback(() => {
    // Find the last user message and retry it
    const lastUserMessage = [...messages].reverse().find((m) => m.role === "user");
    if (lastUserMessage) {
      handleSubmit(lastUserMessage.content);
    }
  }, [messages, handleSubmit]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
    }
  }, [input]);

  return (
    <div className="flex flex-col h-[calc(100dvh-4rem)] md:h-[calc(100dvh-5rem)]">
      {/* Messages area */}
      <div
        className="flex-1 overflow-y-auto px-4 py-4 space-y-4"
        role="log"
        aria-live="polite"
        aria-label={translations.title}
      >
        {messages.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center h-full text-center text-muted-foreground">
            <p className="text-lg font-medium mb-1">{translations.title}</p>
            <p className="text-sm">{translations.placeholder}</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            role={msg.role}
            content={msg.content}
            citations={msg.citations}
            typingLabel={translations.typing}
          />
        ))}

        {/* Loading indicator — shown when waiting for assistant */}
        {loading && messages.length > 0 && messages[messages.length - 1].role === "user" && (
          <MessageBubble
            role="assistant"
            content=""
            typingLabel={translations.typing}
          />
        )}

        {/* Error state */}
        {error && (
          <div className="flex justify-center">
            <div className="bg-destructive/10 border border-destructive/20 rounded-xl px-4 py-3 max-w-md text-center">
              <p className="text-sm text-destructive">{error}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={handleRetry}
                disabled={loading}
              >
                <RotateCcw className="h-3.5 w-3.5 mr-1" />
                {translations.retry}
              </Button>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t bg-background px-4 py-3">
        <div className="max-w-3xl mx-auto flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={translations.placeholder}
            disabled={loading}
            rows={1}
            className="flex-1 resize-none rounded-xl border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 min-h-[40px] max-h-[120px]"
            aria-label={translations.placeholder}
          />
          <Button
            onClick={() => handleSubmit()}
            disabled={loading || !input.trim()}
            size="icon"
            className="rounded-xl shrink-0 h-10 w-10"
            aria-label={translations.send}
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowUp className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
