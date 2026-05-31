"use client";

import { useState, useRef, useEffect, useCallback, type UIEvent } from "react";
import { Button } from "@/components/ui/button";
import { MessageBubble, type MessageStatus } from "./message-bubble";
import { WelcomeScreen } from "./welcome-screen";
import { sendChat, streamChat, type ChatResponse, type Citation, type PlaceResult, type ChatStreamStatus } from "@/lib/chat-api";
import { ArrowDown, ArrowUp, AlertCircle, Compass, Loader2, MessageSquare, RotateCcw, ShieldCheck, Trash2, Waves, ArrowRight } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  places?: PlaceResult[];
  guardrailStatus?: string;
  fallback?: boolean;
  langfuseTraceId?: string | null;
  cacheHit?: boolean;
  status?: MessageStatus;
  streamStatus?: ChatStreamStatus | null;
  /** Bounded history of operational phases seen during streaming. */
  statusHistory?: ChatStreamStatus[];
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
    scoreBreakdown?: string;
    explanation?: string;
    providerSource?: string;
    providerStatus?: string;
    scoreDataLimited?: string;
    accessibilityNote?: string;
    welcomeGreeting?: string;
    welcomeSubtitle?: string;
    newConversation?: string;
    copy?: string;
    copied?: string;
    retryMessage?: string;
    prompts?: string[];
    quickReplyLabels?: {
      places?: string[];
      sources?: string[];
      fallback?: string[];
      generic?: string[];
    };
  };
}

const SOURCE_LABELS = {
  vi: { one: "nguồn", many: "nguồn", searching: "đang xử lý", inputHint: "Enter để gửi • Shift+Enter xuống dòng", scroll: "Xuống cuối", retrying: "Đang thử lại..." },
  en: { one: "source", many: "sources", searching: "working", inputHint: "Enter to send • Shift+Enter for newline", scroll: "Jump to latest", retrying: "Retrying..." },
} as const;

const STATUS_LABELS: Record<"vi" | "en", Record<ChatStreamStatus, string>> = {
  vi: {
    understanding: "Đang hiểu câu hỏi...",
    using_history: "Đang dùng ngữ cảnh cuộc trò chuyện...",
    searching_knowledge: "Đang tìm nguồn phù hợp...",
    checking_places: "Đang kiểm tra địa điểm/đường đi...",
    composing: "Đang tổng hợp câu trả lời...",
  },
  en: {
    understanding: "Understanding your question...",
    using_history: "Using conversation context...",
    searching_knowledge: "Searching relevant sources...",
    checking_places: "Checking places/routes...",
    composing: "Composing the answer...",
  },
};

export function ChatInterface({ locale, translations }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [sessionId] = useState(() => crypto.randomUUID());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const language = (locale === "en" ? "en" : "vi") as "vi" | "en";
  const labels = SOURCE_LABELS[language];

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    messagesEndRef.current?.scrollIntoView({ behavior, block: "end" });
  }, []);

  useEffect(() => {
    if (isNearBottom || loading) {
      scrollToBottom("smooth");
    }
  }, [messages, isNearBottom, loading, scrollToBottom]);

  const handleScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    const target = event.currentTarget;
    const distance = target.scrollHeight - target.scrollTop - target.clientHeight;
    setIsNearBottom(distance < 120);
  }, []);

  const updateLastAssistant = useCallback((updater: (message: Message) => Message) => {
    setMessages((prev) => {
      const next = [...prev];
      const lastIndex = next.length - 1;
      const lastMessage = next[lastIndex];

      if (!lastMessage || lastMessage.role !== "assistant") {
        return prev;
      }

      next[lastIndex] = updater(lastMessage);
      return next;
    });
  }, []);

  const handleSubmit = useCallback(
    async (overrideMessage?: string) => {
      const messageText = overrideMessage ?? input.trim();
      if (!messageText || loading) return;

      setError(null);
      setLoading(true);
      setIsNearBottom(true);

      const userMsg: Message = { role: "user", content: messageText, status: "complete" };
      const assistantPlaceholder: Message = {
        role: "assistant",
        content: "",
        citations: [],
        status: "submitted",
        streamStatus: "understanding",
        statusHistory: ["understanding"],
      };
      setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);
      setInput("");

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
        updateLastAssistant((message) => ({ ...message, status: "submitted" }));
        const response: ChatResponse = await sendChat(messageText, sessionId, language);
        const displayText = response.message?.trim() ? response.message : translations.noEvidence;

        updateLastAssistant((message) => ({
          ...message,
          content: displayText,
          citations: response.citations ?? [],
          places: response.places ?? [],
          guardrailStatus: response.guardrail_status,
          fallback: response.fallback,
          langfuseTraceId: response.langfuse_trace_id,
          cacheHit: response.cache_hit,
          status: "complete",
          streamStatus: null,
          statusHistory: message.statusHistory && message.statusHistory.length > 0
            ? message.statusHistory
            : ["composing"],
        }));
      };

      try {
        let streamFailed = false;
        let streamErrorMessage = translations.error;

        await streamChat(messageText, sessionId, language, {
          onOpen: () => updateLastAssistant((message) => ({ ...message, status: "streaming" })),
          onStatus: (streamStatus) => updateLastAssistant((message) => {
            const prev = message.statusHistory ?? [];
            const last = prev[prev.length - 1];
            const history = last === streamStatus ? prev : [...prev, streamStatus];
            return { ...message, streamStatus, status: "streaming", statusHistory: history };
          }),
          onToken: (token) => updateLastAssistant((message) => ({
            ...message,
            content: message.content + token,
            status: "streaming",
          })),
          onCitations: (citations) => updateLastAssistant((message) => ({ ...message, citations })),
          onPlaces: (places) => updateLastAssistant((message) => ({ ...message, places })),
          onDone: () => {
            updateLastAssistant((message) => ({ ...message, status: "complete", streamStatus: null }));
            setLoading(false);
          },
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
    [input, loading, sessionId, language, translations, updateLastAssistant],
  );

  const handleRetry = useCallback(() => {
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
    setIsNearBottom(true);
    textareaRef.current?.focus();
  }, []);

  // Derived from messages — needed by quick reply derivation and status bar
  const lastAssistant = [...messages].reverse().find((message) => message.role === "assistant");
  const sourceCount = lastAssistant?.citations?.length ?? 0;
  const activeStatus = lastAssistant?.streamStatus
    ? STATUS_LABELS[language][lastAssistant.streamStatus]
    : loading
      ? labels.searching
      : sourceCount > 0
        ? `${sourceCount} ${sourceCount === 1 ? labels.one : labels.many}`
        : "";

  // ── Deterministic Quick Reply Chips ──────────────────────────────────────
  // Derives chip labels from local UI state only — no LLM/API calls.

  const defaultQuickReplies: Record<"vi" | "en", {
    places: string[];
    sources: string[];
    fallback: string[];
    generic: string[];
  }> = {
    vi: {
      places: ["Hiển thị trên bản đồ", "Kể thêm về chỗ này", "Có tiếp cận được không?"],
      sources: ["Tóm tắt nguồn tham khảo", "Hỏi thêm về chủ đề này"],
      fallback: ["Thử hỏi theo hướng khác", "Hỏi về làng chài"],
      generic: ["Bạn còn làm được gì?", "Kể về ẩm thực địa phương"],
    },
    en: {
      places: ["Show on map", "Tell me more", "Is it accessible?"],
      sources: ["Summarize the sources", "Follow up on this"],
      fallback: ["Try a different angle", "Ask about the village"],
      generic: ["What else can you do?", "Tell me about local food"],
    },
  };

  const getQuickReplyLabels = useCallback(
    (category: "places" | "sources" | "fallback" | "generic"): string[] => {
      const fromTranslations = translations.quickReplyLabels?.[category];
      if (fromTranslations && Array.isArray(fromTranslations) && fromTranslations.length > 0) {
        return fromTranslations;
      }
      return defaultQuickReplies[language][category];
    },
    [translations.quickReplyLabels, language],
  );

  const deriveQuickReplies = useCallback((): string[] => {
    if (!lastAssistant || lastAssistant.status !== "complete") return [];

    // Place results: show map / follow-up / accessibility chips
    if (lastAssistant.places && lastAssistant.places.length > 0) {
      return getQuickReplyLabels("places");
    }

    // Source-backed answer: show summary / follow-up chips
    if (lastAssistant.citations && lastAssistant.citations.length > 0) {
      return getQuickReplyLabels("sources");
    }

    // Fallback response: show recovery chips
    if (lastAssistant.fallback) {
      return getQuickReplyLabels("fallback");
    }

    // Generic next-question chips for any other assistant response
    return getQuickReplyLabels("generic");
  }, [lastAssistant, getQuickReplyLabels]);

  const handleQuickReplyClick = useCallback(
    (label: string) => {
      if (!loading) {
        handleSubmit(label);
      }
    },
    [loading, handleSubmit],
  );

  const quickReplyChips = deriveQuickReplies();

  const handlePromptClick = useCallback(
    (prompt: string) => {
      handleSubmit(prompt);
    },
    [handleSubmit],
  );

  const handleRetryMessage = useCallback(
    (index: number) => {
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

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 144)}px`;
    }
  }, [input]);

  return (
    <div className="relative flex h-[calc(100dvh-4rem)] flex-col overflow-hidden bg-[#f4eddf] md:h-[calc(100dvh-5rem)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_12%_8%,rgba(12,95,99,0.18),transparent_34%),radial-gradient(circle_at_86%_22%,rgba(232,137,58,0.20),transparent_30%),linear-gradient(135deg,#f7f0e4_0%,#e3f2ee_54%,#fff8e9_100%)]" />
      <div className="pointer-events-none absolute left-0 top-0 h-full w-full opacity-[0.08] [background-image:linear-gradient(90deg,#0b5f63_1px,transparent_1px),linear-gradient(#0b5f63_1px,transparent_1px)] [background-size:44px_44px]" />

      <header className="relative z-10 border-b border-[#0b5f63]/10 bg-[#fffaf0]/78 px-4 py-3 backdrop-blur-xl">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-[#0b5f63] text-[#fffaf0] shadow-lg shadow-[#0b5f63]/20">
              <Compass className="size-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[0.68rem] font-semibold uppercase tracking-[0.24em] text-[#0b5f63]">
                <Waves className="size-3.5" />
                Ham Ninh Guide
              </div>
              <h1 className="mt-0.5 truncate text-lg font-semibold tracking-tight text-[#123436] md:text-2xl">
                {translations.title}
              </h1>
            </div>
          </div>
          <div className="hidden items-center gap-2 rounded-full border border-[#0b5f63]/15 bg-white/70 px-3 py-1.5 text-xs text-[#426365] shadow-sm md:flex">
            <ShieldCheck className="size-3.5 text-[#0b5f63]" />
            {language === "vi" ? "Trợ lý AI - hãy kiểm chứng thông tin quan trọng" : "AI assistant - verify important details"}
          </div>
        </div>
      </header>

      {/* Full-height scroll region — mobile-first with safe-area bottom padding for the composer */}
      <div
        ref={scrollRef}
        className="relative z-10 flex-1 overflow-y-auto px-2 pb-[env(safe-area-inset-bottom)] py-3 sm:px-3 sm:py-4 md:px-6"
        role="log"
        aria-live="polite"
        aria-label={translations.title}
        onScroll={handleScroll}
      >
        <div className="mx-auto flex min-h-full max-w-4xl flex-col gap-4 sm:gap-5">
          {messages.length === 0 && !error && (
            <WelcomeScreen
              onPromptClick={handlePromptClick}
              translations={{
                greeting: translations.welcomeGreeting ?? translations.title,
                subtitle: translations.welcomeSubtitle ?? translations.placeholder,
                promptChips: translations.prompts ?? [],
                badgeLabel: language === "vi" ? "Trợ lý du lịch địa phương" : "Local AI travel guide",
                disclosure: language === "vi"
                  ? "Đây là trợ lý AI; thông tin có thể sai. Với đường đi, giờ mở cửa hoặc an toàn, hãy kiểm tra lại trên bản đồ/nguồn chính thức."
                  : "This is an AI assistant and can be wrong. For routes, opening hours, or safety, verify with a map or official source.",
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
              status={msg.status}
              statusHistory={msg.statusHistory}
              streamStatusLabel={msg.streamStatus ? STATUS_LABELS[language][msg.streamStatus] : undefined}
              streamStatusLabels={STATUS_LABELS[language]}
              typingLabel={translations.typing}
              assistantLabel={language === "vi" ? "Trợ lý Hàm Ninh" : "Ham Ninh Assistant"}
              userLabel={language === "vi" ? "Bạn" : "You"}
              sourcesLabel={translations.citations}
              onRetry={msg.role === "assistant" ? () => handleRetryMessage(i) : undefined}
              actionTranslations={{
                copy: translations.copy,
                copied: translations.copied,
                retry: translations.retryMessage,
              }}
              placeTranslations={{
                placeResultsHeading: translations.placeResultsHeading ?? "Recommended Places",
                viewOnMap: translations.viewOnMap ?? "View on Map",
                scoreLabel: translations.scoreLabel ?? "Score",
                noRating: translations.noRating ?? "No rating",
                scoreBreakdown: translations.scoreBreakdown ?? "Score Breakdown",
                explanation: translations.explanation ?? "Why this place?",
                providerSource: translations.providerSource ?? "Source",
                providerStatus: translations.providerStatus ?? "Status",
                scoreDataLimited: translations.scoreDataLimited ?? "Limited scoring data available",
                accessibilityNote: translations.accessibilityNote ?? "Accessibility info",
              }}
            />
          ))}

          {error && (
            <div className="flex gap-3 animate-slideUp">
              <div
                className="mt-1 grid size-8 shrink-0 place-items-center rounded-full bg-[#fffaf0] text-[#0b5f63] ring-1 ring-[#0b5f63]/15 shadow-sm"
                aria-hidden="true"
              >
                <AlertCircle className="size-4" />
              </div>
              <div className="min-w-0 max-w-[86%] items-start md:max-w-[74%]">
                <div className="mb-1 flex items-center gap-2 text-[0.72rem] text-[#b45a5a]">
                  <span className="font-semibold">{language === "vi" ? "Lỗi kết nối" : "Connection error"}</span>
                </div>
                <div className="group relative rounded-[1.45rem] rounded-tl-md border border-destructive/20 bg-white/85 px-4 py-3 shadow-lg shadow-destructive/5">
                  <p className="text-sm text-destructive">{error}</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3 rounded-full border-destructive/20 text-destructive hover:bg-destructive/5"
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
      </div>

      {/* Quick reply chips — deterministic, derived from local UI state */}
      {quickReplyChips.length > 0 && !loading && (
        <div className="relative z-10 border-t border-[#0b5f63]/10 bg-[#fffaf0]/60 px-2 py-2 sm:px-3 sm:py-2.5">
          <div className="mx-auto max-w-4xl">
            <div className="flex items-center gap-2 px-1 text-[0.65rem] font-medium uppercase tracking-[0.12em] text-[#5d7373]">
              <ArrowRight className="size-3" />
              <span>{language === "vi" ? "Gợi ý tiếp theo" : "Quick replies"}</span>
            </div>
            <div className="mt-1.5 flex flex-wrap gap-1.5 sm:gap-2" role="group" aria-label={language === "vi" ? "Câu trả lời nhanh" : "Quick reply suggestions"}>
              {quickReplyChips.map((label, i) => (
                <button
                  key={`${label}-${i}`}
                  type="button"
                  onClick={() => handleQuickReplyClick(label)}
                  disabled={loading}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[#0b5f63]/20 bg-white/80 px-3 py-1.5 text-xs font-medium text-[#0b5f63] shadow-sm transition-colors hover:bg-[#0b5f63]/10 hover:border-[#0b5f63]/30 active:bg-[#0b5f63]/15 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {!isNearBottom && (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="absolute bottom-28 left-1/2 z-20 -translate-x-1/2 rounded-full border border-white/80 bg-white/90 shadow-lg"
          onClick={() => scrollToBottom("smooth")}
        >
          <ArrowDown className="size-3.5" />
          {labels.scroll}
        </Button>
      )}

      {/* Sticky bottom composer — mobile-first with safe-area padding */}
      <div className="relative z-10 border-t border-[#0b5f63]/10 bg-[#fffaf0]/82 px-2 py-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] backdrop-blur-xl sm:px-3 sm:py-3 md:px-4">
        <div className="mx-auto max-w-4xl">
          <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2 px-1 text-[0.7rem] text-[#5d7373]">
            <div className="flex flex-wrap items-center gap-1.5">
              {activeStatus && loading && <Loader2 className="size-3 animate-spin" />}
              {activeStatus && <span>{activeStatus}</span>}
            </div>
            <span className="hidden sm:inline">{labels.inputHint}</span>
          </div>
          <div className="flex items-end gap-1.5 rounded-[1.45rem] border border-white/90 bg-white/90 p-1.5 shadow-2xl shadow-[#0b5f63]/10 ring-1 ring-[#0b5f63]/8 sm:gap-2 sm:p-2">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={translations.placeholder}
              disabled={loading}
              rows={1}
              className="max-h-36 min-h-10 flex-1 resize-none rounded-2xl border-0 bg-transparent px-3 py-2 text-sm leading-6 text-[#123436] placeholder:text-[#6f8584] focus-visible:outline-none focus-visible:ring-0 disabled:opacity-50 sm:min-h-11 sm:text-sm sm:leading-6 sm:px-3 sm:py-2.5"
              aria-label={translations.placeholder}
            />
            {messages.length > 0 && (
              <Button
                variant="ghost"
                size="icon"
                className="h-10 w-10 shrink-0 rounded-2xl text-[#6f8584] hover:bg-destructive/10 hover:text-destructive sm:h-11 sm:w-11"
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
              className="h-10 w-10 shrink-0 rounded-2xl bg-[#0b5f63] shadow-md shadow-[#0b5f63]/20 hover:bg-[#084d50] sm:h-11 sm:w-11"
              aria-label={translations.send}
              title={translations.send}
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
