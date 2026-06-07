"use client";

import { useState, useRef, useEffect, useCallback, type UIEvent } from "react";
import { Button } from "@/components/ui/button";
import { MessageBubble, type MessageStatus } from "./message-bubble";
import { WelcomeScreen } from "./welcome-screen";
import { ChatSidebar } from "./chat-sidebar";
import { PlaceResultsPanel } from "./place-results-panel";
import { sendChat, streamChat, type ChatResponse, type Citation, type PlaceResult, type ChatStreamStatus } from "@/lib/chat-api";
import { ArrowDown, ArrowUp, AlertCircle, Loader2, MapPinned, Menu, RotateCcw, Trash2, ArrowRight } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  places?: PlaceResult[];
  suggestions?: string[];
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
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [placesOpen, setPlacesOpen] = useState(false);
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
    if (messages.length > 0 && (isNearBottom || loading)) {
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
          suggestions: response.suggestions ?? [],
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
          onSuggestions: (suggestions) => updateLastAssistant((message) => ({ ...message, suggestions })),
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
  const latestPlaces =
    [...messages]
      .reverse()
      .find((message) => message.role === "assistant" && message.places?.length)
      ?.places ?? [];
  const recentQuestions = messages
    .filter((message) => message.role === "user")
    .map((message) => message.content)
    .slice(-2)
    .reverse();
  const placeTranslations = {
    placeResultsHeading: translations.placeResultsHeading ?? "Recommended Places",
    viewOnMap: translations.viewOnMap ?? "View on Map",
    scoreLabel: translations.scoreLabel ?? "Score",
    noRating: translations.noRating ?? "No rating",
    scoreBreakdown: translations.scoreBreakdown ?? "Score Breakdown",
    explanation: translations.explanation ?? "Why this place?",
    providerSource: translations.providerSource ?? "Source",
    providerStatus: translations.providerStatus ?? "Status",
    scoreDataLimited:
      translations.scoreDataLimited ?? "Limited scoring data available",
    accessibilityNote:
      translations.accessibilityNote ?? "Accessibility info",
  };
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

    // Prefer LLM-generated dynamic suggestions if present
    if (lastAssistant.suggestions && lastAssistant.suggestions.length > 0) {
      return lastAssistant.suggestions;
    }

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
    <div className="h-[calc(100dvh-4rem)] min-h-[36rem] overflow-hidden bg-white text-[#37352f]">
      <div
        className={`grid h-full min-h-0 ${
          latestPlaces.length > 0
            ? "lg:grid-cols-[240px_minmax(0,1fr)_360px]"
            : "lg:grid-cols-[240px_minmax(0,1fr)]"
        }`}
      >
        <ChatSidebar
          locale={locale}
          newQuestion={translations.newQuestion}
          recentQuestions={recentQuestions}
          onNewQuestion={handleClearConversation}
          mobileOpen={sidebarOpen}
          onMobileClose={() => setSidebarOpen(false)}
        />

        <main className="relative flex min-h-0 min-w-0 flex-col bg-white">

      {/* Full-height scroll region — mobile-first with safe-area bottom padding for the composer */}
      <div
        ref={scrollRef}
        className="relative z-10 flex-1 overflow-y-auto px-3 py-5 sm:px-6"
        role="log"
        aria-live="polite"
        aria-label={translations.title}
        onScroll={handleScroll}
      >
        <div className="mx-auto flex min-h-full max-w-4xl flex-col gap-6">
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
                quickPromptLabel: language === "vi" ? "Chọn điểm bắt đầu" : "Choose a starting point",
                welcomeIntents: language === "vi"
                  ? [
                    {
                      title: "Khám phá văn hóa",
                      description: "Hiểu ẩm thực, làng chài, lịch sử và đời sống địa phương với nguồn khi cần.",
                      badge: "Có nguồn",
                      prompts: ["Kể về ẩm thực địa phương", "Hải sản Hàm Ninh có gì nổi bật?"],
                    },
                    {
                      title: "Tìm địa điểm",
                      description: "Gợi ý quán hải sản, cà phê, homestay hoặc điểm ghé quanh Hàm Ninh.",
                      badge: "Địa điểm",
                      prompts: ["Tìm quán hải sản gần đây", "Có homestay gần biển không?"],
                    },
                    {
                      title: "Hỏi đường",
                      description: "Nói điểm đến hoặc điểm xuất phát; nếu thiếu, trợ lý sẽ hỏi lại.",
                      badge: "Đường đi",
                      prompts: ["Chỉ đường đến chợ Hàm Ninh", "Từ Dương Đông đi Hàm Ninh thế nào?"],
                    },
                    {
                      title: "Lên lịch trình",
                      description: "Biến thời gian, nhóm đi và sở thích thành một kế hoạch tham quan ngắn.",
                      badge: "Kế hoạch",
                      prompts: ["Gợi ý lịch trình 3 giờ", "Đi với trẻ em nên ghé đâu?"],
                    },
                  ]
                  : [
                    {
                      title: "Explore culture",
                      description: "Understand food, fishing life, history, and local context with sources when needed.",
                      badge: "Sources",
                      prompts: ["Tell me about local food", "What seafood is Ham Ninh known for?"],
                    },
                    {
                      title: "Find places",
                      description: "Get seafood, cafe, homestay, or stopover ideas around Ham Ninh.",
                      badge: "Places",
                      prompts: ["Find nearby seafood restaurants", "Any homestays near the coast?"],
                    },
                    {
                      title: "Ask directions",
                      description: "Share a destination or starting point; the assistant clarifies missing details.",
                      badge: "Routes",
                      prompts: ["Get directions to Ham Ninh market", "How do I get there from Duong Dong?"],
                    },
                    {
                      title: "Plan a stop",
                      description: "Turn time, group context, and interests into a compact itinerary.",
                      badge: "Plan",
                      prompts: ["Plan a 3-hour visit", "Where should I go with kids?"],
                    },
                  ],
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
              placeTranslations={placeTranslations}
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
        <div className="relative z-10 border-t border-[#e9e9e7] bg-white px-4 py-2.5">
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
                  className="inline-flex items-center gap-1.5 rounded-md border border-[#e9e9e7] bg-white px-3 py-1.5 text-xs font-medium text-[#37352f] transition-colors hover:bg-[#f7f7f5] disabled:cursor-not-allowed disabled:opacity-50"
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
      <footer className="relative z-10 shrink-0 border-t border-[#e9e9e7] bg-white px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-3 sm:px-8">
        <div className="mx-auto max-w-4xl">
          <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2 px-1 text-[0.7rem] text-[#5d7373]">
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                className="mr-1 rounded-md p-1 text-[#787774] hover:bg-[#f7f7f5] lg:hidden"
                onClick={() => setSidebarOpen(true)}
                aria-label={language === "vi" ? "Mở menu" : "Open menu"}
              >
                <Menu className="size-4" />
              </button>
              {latestPlaces.length > 0 && (
                <button
                  type="button"
                  className="mr-1 rounded-md p-1 text-[#2383e2] hover:bg-[#f7f7f5] lg:hidden"
                  onClick={() => setPlacesOpen(true)}
                  aria-label={placeTranslations.placeResultsHeading}
                >
                  <MapPinned className="size-4" />
                </button>
              )}
              {activeStatus && loading && <Loader2 className="size-3 animate-spin" />}
              {activeStatus && <span>{activeStatus}</span>}
            </div>
            <span className="hidden sm:inline">{labels.inputHint}</span>
          </div>
          <div className="flex items-end gap-1.5 rounded-2xl border border-[#e9e9e7] bg-white p-1.5 shadow-sm focus-within:border-[#2383e2] focus-within:ring-2 focus-within:ring-[#2383e2]/10 sm:gap-2 sm:p-2">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={translations.placeholder}
              disabled={loading}
              rows={1}
              className="max-h-36 min-h-10 flex-1 resize-none rounded-xl border-0 bg-transparent px-3 py-2 text-sm leading-6 text-[#37352f] placeholder:text-[#91918e] focus-visible:outline-none focus-visible:ring-0 disabled:opacity-50 sm:min-h-11 sm:px-3 sm:py-2.5"
              aria-label={translations.placeholder}
            />
            {messages.length > 0 && (
              <Button
                variant="ghost"
                size="icon"
                className="h-10 w-10 shrink-0 rounded-xl text-[#787774] hover:bg-destructive/10 hover:text-destructive sm:h-11 sm:w-11"
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
              className="h-10 w-10 shrink-0 rounded-xl bg-[#2383e2] shadow-sm hover:bg-[#1d6dc3] sm:h-11 sm:w-11"
              aria-label={translations.send}
              title={translations.send}
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </footer>
        </main>

        {latestPlaces.length > 0 && (
          <PlaceResultsPanel
            places={latestPlaces}
            translations={placeTranslations}
            mobileOpen={placesOpen}
            onMobileClose={() => setPlacesOpen(false)}
          />
        )}
      </div>
    </div>
  );
}
