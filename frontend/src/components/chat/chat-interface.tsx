"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { MessageBubble } from "./message-bubble";
import { WelcomeScreen } from "./welcome-screen";
import { sendChat, streamChat, type ChatResponse, type Citation, type PlaceResult } from "@/lib/chat-api";
import { ArrowUp, RotateCcw, Loader2, Trash2, ShieldCheck, Waves } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  places?: PlaceResult[];
  guardrailStatus?: string;
  fallback?: boolean;
  langfuseTraceId?: string | null;
  cacheHit?: boolean;
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
    placeResultsHeading?: string;
    viewOnMap?: string;
    scoreLabel?: string;
    noRating?: string;
    welcomeGreeting?: string;
    welcomeSubtitle?: string;
    newConversation?: string;
    copy?: string;
    copied?: string;
    retryMessage?: string;
    prompts?: string[];
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

      // Append user message and the assistant placeholder that streaming will fill.
      const userMsg: Message = { role: "user", content: messageText };
      const assistantPlaceholder: Message = {
        role: "assistant",
        content: "",
        citations: [],
      };
      setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);
      setInput("");

      const appendToAssistant = (token: string) => {
        setMessages((prev) => {
          const next = [...prev];
          const lastIndex = next.length - 1;
          const lastMessage = next[lastIndex];

          if (!lastMessage || lastMessage.role !== "assistant") {
            return prev;
          }

          next[lastIndex] = {
            ...lastMessage,
            content: lastMessage.content + token,
          };
          return next;
        });
      };

      const updateAssistantCitations = (citations: Citation[]) => {
        setMessages((prev) => {
          const next = [...prev];
          const lastIndex = next.length - 1;
          const lastMessage = next[lastIndex];

          if (!lastMessage || lastMessage.role !== "assistant") {
            return prev;
          }

          next[lastIndex] = { ...lastMessage, citations };
          return next;
        });
      };

      const removeEmptyAssistantPlaceholder = () => {
        setMessages((prev) => {
          const lastMessage = prev[prev.length - 1];
          if (lastMessage?.role === "assistant" && !lastMessage.content) {
            return prev.slice(0, -1);
          }
          return prev;
        });
      };

      const renderPostFallback = async () => {
        const response: ChatResponse = await sendChat(messageText, sessionId, language);
        const displayText =
          response.message && response.message.trim()
            ? response.message
            : translations.noEvidence;

        setMessages((prev) => {
          const next = [...prev];
          const lastIndex = next.length - 1;
          const lastMessage = next[lastIndex];

          if (lastMessage?.role === "assistant") {
            next[lastIndex] = {
              ...lastMessage,
              content: displayText,
              citations: response.citations ?? [],
              places: response.places ?? [],
              guardrailStatus: response.guardrail_status,
              fallback: response.fallback,
              langfuseTraceId: response.langfuse_trace_id,
              cacheHit: response.cache_hit,
            };
            return next;
          }

          return [
            ...prev,
            {
              role: "assistant",
              content: displayText,
              citations: response.citations ?? [],
              places: response.places ?? [],
              guardrailStatus: response.guardrail_status,
              fallback: response.fallback,
              langfuseTraceId: response.langfuse_trace_id,
              cacheHit: response.cache_hit,
            },
          ];
        });
      };

      try {
        let streamFailed = false;
        let streamErrorMessage = translations.error;

        await streamChat(messageText, sessionId, language, {
          onToken: appendToAssistant,
          onCitations: updateAssistantCitations,
          onDone: () => setLoading(false),
          onError: (err) => {
            streamFailed = true;
            streamErrorMessage = err;
          },
        });

        if (streamFailed) {
          try {
            await renderPostFallback();
          } catch (err) {
            removeEmptyAssistantPlaceholder();
            setError(err instanceof Error ? err.message : streamErrorMessage);
          } finally {
            setLoading(false);
          }
        }
      } catch (err) {
        removeEmptyAssistantPlaceholder();
        setError(err instanceof Error ? err.message : translations.error);
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

  const handleClearConversation = useCallback(() => {
    setMessages([]);
    setError(null);
    setLoading(false);
    setInput("");
  }, []);

  const handlePromptClick = useCallback(
    (prompt: string) => {
      handleSubmit(prompt);
    },
    [handleSubmit],
  );

  const handleRetryMessage = useCallback(
    (index: number) => {
      // Find the user message before this assistant message and re-send it
      if (index > 0 && messages[index - 1]?.role === "user") {
        handleSubmit(messages[index - 1].content);
      }
    },
    [messages, handleSubmit],
  );

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
    <div className="relative flex h-[calc(100dvh-4rem)] flex-col overflow-hidden bg-[radial-gradient(circle_at_top_left,rgba(20,146,139,0.22),transparent_32%),linear-gradient(135deg,#f8f3e8_0%,#e8f4f1_48%,#fff8ed_100%)] md:h-[calc(100dvh-5rem)]">
      <div className="pointer-events-none absolute -left-20 top-20 size-56 rounded-full bg-[#f2a65a]/20 blur-3xl" />
      <div className="pointer-events-none absolute -right-24 bottom-24 size-64 rounded-full bg-[#0b8f8a]/18 blur-3xl" />

      <header className="relative z-10 border-b border-white/60 bg-white/55 px-4 py-3 backdrop-blur-xl">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-primary">
              <Waves className="size-3.5" />
              Ham Ninh Guide
            </div>
            <h1 className="mt-1 text-lg font-semibold tracking-tight text-foreground md:text-2xl">
              {translations.title}
            </h1>
          </div>
          <div className="hidden items-center gap-2 rounded-full border border-white/70 bg-white/70 px-3 py-1.5 text-xs text-muted-foreground shadow-sm md:flex">
            <ShieldCheck className="size-3.5 text-primary" />
            {language === "vi" ? "Trả lời mềm, có kiểm chứng" : "Soft, grounded answers"}
          </div>
        </div>
      </header>

      {/* Messages area */}
      <div
        className="relative z-10 flex-1 space-y-4 overflow-y-auto px-4 py-5 md:px-6"
        role="log"
        aria-live="polite"
        aria-label={translations.title}
      >
        {messages.length === 0 && !error && (
          <WelcomeScreen
            onPromptClick={handlePromptClick}
            translations={{
              greeting: translations.welcomeGreeting ?? translations.title,
              subtitle: translations.welcomeSubtitle ?? translations.placeholder,
              promptChips: translations.prompts ?? [],
              badgeLabel: language === "vi" ? "Trợ lý du lịch địa phương" : "Local AI travel guide",
            }}
          />
        )}

        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            role={msg.role}
            content={msg.content}
            citations={msg.citations}
            places={msg.places}
            guardrailStatus={msg.guardrailStatus}
            fallback={msg.fallback}
            langfuseTraceId={msg.langfuseTraceId}
            cacheHit={msg.cacheHit}
            typingLabel={translations.typing}
            onRetry={msg.role === "assistant" ? () => handleRetryMessage(i) : undefined}
            placeTranslations={{
              placeResultsHeading: translations.placeResultsHeading ?? "Recommended Places",
              viewOnMap: translations.viewOnMap ?? "View on Map",
              scoreLabel: translations.scoreLabel ?? "Score",
              noRating: translations.noRating ?? "No rating",
            }}
          />
        ))}

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
      <div className="relative z-10 border-t border-white/60 bg-white/65 px-4 py-3 backdrop-blur-xl">
        <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-[1.35rem] border border-white/80 bg-white/85 p-2 shadow-lg shadow-slate-900/8">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={translations.placeholder}
            disabled={loading}
            rows={1}
            className="max-h-[120px] min-h-[44px] flex-1 resize-none rounded-2xl border-0 bg-transparent px-3 py-2.5 text-sm leading-6 placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-0 disabled:opacity-50"
            aria-label={translations.placeholder}
          />
          {messages.length > 0 && (
            <Button
              variant="ghost"
              size="icon"
              className="h-11 w-11 shrink-0 rounded-2xl text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              onClick={handleClearConversation}
              disabled={loading}
              aria-label={translations.newConversation ?? "New conversation"}
              title={translations.newConversation ?? "New conversation"}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
          <Button
            onClick={() => handleSubmit()}
            disabled={loading || !input.trim()}
            size="icon"
            className="h-11 w-11 shrink-0 rounded-2xl bg-[#0b5f63] shadow-md shadow-[#0b5f63]/20 hover:bg-[#084d50]"
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
