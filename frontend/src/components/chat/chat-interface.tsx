"use client";

import { useState, useRef, useEffect, useCallback, type UIEvent } from "react";
import { Button } from "@/components/ui/button";
import { MessageBubble, type MessageStatus } from "./message-bubble";
import { WelcomeScreen } from "./welcome-screen";
import { ChatSidebar } from "./chat-sidebar";
import { PlaceResultsPanel } from "./place-results-panel";
import { sendChat, streamChat, type ChatHistoryTurn, type ChatResponse, type Citation, type PlaceResult, type ChatStreamStatus } from "@/lib/chat-api";
import { AUTH_CHANGED_EVENT, getUser } from "@/lib/auth-store";
import {
  createEmptyConversation,
  getChatStorageOwner,
  loadChatConversations,
  saveChatConversation,
  toConversationSummaries,
  type ChatConversationSummary,
  type StoredChatConversation,
} from "@/lib/chat-storage";
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
  reasoningLog?: string | null;
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

const STATUS_LABELS: Record<"vi" | "en", Record<string, string>> = {
  vi: {
    validating: "Bảo mật & An toàn",
    routing: "Phân tích yêu cầu",
    dispatching: "Tối ưu hóa công bằng",
    "processing:rag": "Truy xuất kiến thức",
    "processing:maps": "Tra cứu bản đồ địa điểm",
    verifying: "Xác thực phản hồi",
    understanding: "Đang hiểu câu hỏi...",
    using_history: "Đang dùng ngữ cảnh cuộc trò chuyện...",
    input_flagged: "Câu hỏi hơi mơ hồ, mình sẽ xử lý thận trọng...",
    searching_knowledge: "Đang tìm nguồn phù hợp...",
    checking_places: "Đang kiểm tra địa điểm/đường đi...",
    composing: "Đang tổng hợp câu trả lời...",
  },
  en: {
    validating: "Safety & Security",
    routing: "Request Analysis",
    dispatching: "Fairness Optimization",
    "processing:rag": "Knowledge Retrieval",
    "processing:maps": "Map & Place Lookup",
    verifying: "Response Verification",
    understanding: "Understanding your question...",
    using_history: "Using conversation context...",
    input_flagged: "The question is ambiguous, handling carefully...",
    searching_knowledge: "Searching relevant sources...",
    checking_places: "Checking places/routes...",
    composing: "Composing the answer...",
  },
};

export function ChatInterface({ locale, translations }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [chatOwner, setChatOwner] = useState("guest");
  const [conversations, setConversations] = useState<StoredChatConversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [placesOpen, setPlacesOpen] = useState(false);
  const [placesPanelOpen, setPlacesPanelOpen] = useState(true);
  const [sourcesPanelOpen, setSourcesPanelOpen] = useState(true);
  const [budgetFilter, setBudgetFilter] = useState<string | null>(null);
  const [accessibilityRequired, setAccessibilityRequired] = useState<boolean>(true);
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null);
  const [pendingLocationResolve, setPendingLocationResolve] = useState<((loc: any) => void) | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const storageHydratedRef = useRef(false);

  const language = (locale === "en" ? "en" : "vi") as "vi" | "en";
  const labels = SOURCE_LABELS[language];

  useEffect(() => {
    const loadOwnerConversations = () => {
    const owner = getChatStorageOwner(getUser());
    const stored = loadChatConversations(owner);
    const initial = stored[0] ?? createEmptyConversation();

    storageHydratedRef.current = false;
    setChatOwner(owner);
    setConversations(stored);
    setActiveConversationId(initial.id);
    setSessionId(initial.sessionId);
    setMessages(initial.messages as Message[]);
    setError(null);
    setLoading(false);
    window.setTimeout(() => {
      storageHydratedRef.current = true;
    }, 0);
    };

    loadOwnerConversations();
    window.addEventListener(AUTH_CHANGED_EVENT, loadOwnerConversations);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, loadOwnerConversations);
  }, []);

  useEffect(() => {
    if (!storageHydratedRef.current || !activeConversationId) return;
    if (messages.length === 0) return;

    const conversation: StoredChatConversation = {
      id: activeConversationId,
      sessionId,
      title: "",
      updatedAt: Date.now(),
      messages,
    };
    setConversations(saveChatConversation(chatOwner, conversation));
  }, [activeConversationId, chatOwner, messages, sessionId]);

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

  const getBrowserLocation = useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      throw new Error(language === "vi" ? "Trình duyệt không hỗ trợ chia sẻ vị trí." : "Browser location is unavailable.");
    }
    return new Promise<{ lat: number; lng: number }>((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(
        (position) => resolve({ lat: position.coords.latitude, lng: position.coords.longitude }),
        () => reject(new Error(language === "vi" ? "Không lấy được vị trí. Hãy bật quyền vị trí rồi thử lại." : "Could not access location. Enable location permission and try again.")),
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 120000 },
      );
    });
  }, [language]);

  const handleSubmit = useCallback(
    async (overrideMessage?: string) => {
      const messageText = overrideMessage ?? input.trim();
      if (!messageText || loading) return;

      setError(null);
      setLoading(true);
      setIsNearBottom(true);

      const lastAssistantBeforeSubmit = [...messages].reverse().find((message) => message.role === "assistant");
      const normalized = messageText.trim().toLowerCase();
      const confirmsLocation = /^(có|co|ok|okay|được|duoc|yes|yep|sure)$/i.test(normalized);
      const pendingLocation = Boolean(
        lastAssistantBeforeSubmit?.content &&
        /chia sẻ vị trí|biết vị trí|current location|share your location/i.test(lastAssistantBeforeSubmit.content),
      );
      let requestLocation = userLocation;
      if (pendingLocation && confirmsLocation && !requestLocation) {
        try {
          requestLocation = await getBrowserLocation();
          setUserLocation(requestLocation);
        } catch (err) {
          setLoading(false);
          setError(err instanceof Error ? err.message : translations.error);
          return;
        }
      }

      const requestHistory: ChatHistoryTurn[] = messages
        .filter((message): message is Message & { content: string } => Boolean(message.content) && (message.role === "user" || message.role === "assistant"))
        .slice(-8)
        .map((message) => ({ role: message.role, content: message.content }));

      const userMsg: Message = { role: "user", content: messageText, status: "complete" };
      const assistantPlaceholder: Message = {
        role: "assistant",
        content: "",
        citations: [],
        status: "submitted",
        streamStatus: "validating",
        statusHistory: ["validating"],
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
        const response: ChatResponse = await sendChat(messageText, sessionId, language, budgetFilter, accessibilityRequired, requestLocation);
        const displayText = response.message?.trim() ? response.message : translations.noEvidence;

        updateLastAssistant((message) => ({
          ...message,
          content: displayText,
          citations: response.citations ?? [],
          places: response.places ?? [],
          suggestions: response.suggestions ?? [],
          reasoningLog: response.reasoning_log,
          guardrailStatus: response.guardrail_status,
          fallback: response.fallback,
          langfuseTraceId: response.langfuse_trace_id,
          cacheHit: response.cache_hit,
          status: "complete",
          streamStatus: null,
          statusHistory: message.statusHistory && message.statusHistory.length > 0
            ? message.statusHistory
            : ["verifying"],
        }));
      };

      const renderGuardrailResponse = (reason: string) => {
        const friendly = language === "vi"
          ? "Mình chỉ hỗ trợ thông tin về Hàm Ninh / Phú Quốc. Bạn có thể hỏi về địa điểm, ăn uống, đường đi, văn hóa hoặc lịch trình ở Hàm Ninh nhé."
          : "I only help with Ham Ninh / Phu Quoc tourism. You can ask about places, food, directions, culture, or itineraries in Ham Ninh.";

        updateLastAssistant((message) => ({
          ...message,
          content: friendly,
          citations: [],
          places: [],
          suggestions: getQuickReplyLabels("generic"),
          guardrailStatus: reason,
          fallback: true,
          status: "complete",
          streamStatus: null,
          statusHistory: ["understanding", "composing"],
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
          onReasoning: (reasoningLog) => updateLastAssistant((message) => ({ ...message, reasoningLog })),
          onInterrupt: async (interruptData) => {
            // LangGraph interrupt detected - backend needs user input
            console.log('Interrupt received:', interruptData);
            
            if (interruptData.requires_geolocation) {
              // Automatically request geolocation from browser
              try {
                const position = await new Promise<GeolocationPosition>((resolve, reject) => {
                  navigator.geolocation.getCurrentPosition(resolve, reject, {
                    enableHighAccuracy: true,
                    timeout: 5000,
                    maximumAge: 0
                  });
                });
                
                const location = {
                  lat: position.coords.latitude,
                  lng: position.coords.longitude
                };
                
                console.log('Geolocation obtained:', location);
                return location;
              } catch (error) {
                console.warn('Geolocation request failed, falling back to manual selection:', error);
                return new Promise((resolve) => {
                  setPendingLocationResolve(() => resolve);
                });
              }
            }
            
            return null;
          },
          onDone: () => {
            updateLastAssistant((message) => ({ ...message, status: "complete", streamStatus: null }));
            setLoading(false);
          },
          onError: (err) => {
            streamFailed = true;
            streamErrorMessage = err;
          },
        }, budgetFilter, accessibilityRequired, requestLocation, requestHistory);

        if (streamFailed) {
          try {
            if (/\boff_topic\b|\binput_blocked\b/i.test(streamErrorMessage)) {
              renderGuardrailResponse(streamErrorMessage);
            } else {
              await renderPostFallback();
            }
          } catch (err) {
            removeEmptyAssistantPlaceholder();
            setError(err instanceof Error ? err.message : streamErrorMessage);
          } finally {
            setLoading(false);
          }
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : translations.error;
        if (/\boff_topic\b|\binput_blocked\b/i.test(message)) {
          renderGuardrailResponse(message);
          setLoading(false);
          return;
        }
        removeEmptyAssistantPlaceholder();
        setError(message);
        setLoading(false);
      }
    },
    [input, loading, sessionId, language, translations, updateLastAssistant, budgetFilter, accessibilityRequired, userLocation, messages, getBrowserLocation],
  );

  const handleRetry = useCallback(() => {
    const lastUserMessage = [...messages].reverse().find((m) => m.role === "user");
    if (lastUserMessage) {
      handleSubmit(lastUserMessage.content);
    }
  }, [messages, handleSubmit]);

  const handleClearConversation = useCallback(() => {
    const next = createEmptyConversation();
    setActiveConversationId(next.id);
    setSessionId(next.sessionId);
    setMessages([]);
    setError(null);
    setLoading(false);
    setInput("");
    setIsNearBottom(true);
    textareaRef.current?.focus();
  }, []);

  const handleSelectConversation = useCallback(
    (conversationId: string) => {
      const conversation = conversations.find((item) => item.id === conversationId);
      if (!conversation || loading) return;

      setActiveConversationId(conversation.id);
      setSessionId(conversation.sessionId);
      setMessages(conversation.messages as Message[]);
      setError(null);
      setInput("");
      setSidebarOpen(false);
      setIsNearBottom(true);
    },
    [conversations, loading],
  );

  // Derived from messages — needed by quick reply derivation and status bar
  const lastAssistant = [...messages].reverse().find((message) => message.role === "assistant");
  const latestPlaces =
    [...messages]
      .reverse()
      .find((message) => message.role === "assistant" && message.places?.length)
      ?.places ?? [];
  const latestCitations =
    [...messages]
      .reverse()
      .find((message) => message.role === "assistant" && message.citations?.length)
      ?.citations ?? [];
  const hasEvidencePanel = latestPlaces.length > 0 || latestCitations.length > 0;
  const recentQuestions = messages
    .filter((message) => message.role === "user")
    .map((message) => message.content)
    .slice(-2)
    .reverse();
  const conversationSummaries: ChatConversationSummary[] = toConversationSummaries(conversations);
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
    sourcesHeading: translations.citations ?? "Sources",
  };
  const sourceCount = lastAssistant?.citations?.length ?? 0;
  
  // Normalize dynamic streamStatus keys (e.g., routing:conversational -> routing)
  const rawStatus = lastAssistant?.streamStatus;
  const statusKey = rawStatus
    ? rawStatus.startsWith("processing:")
      ? rawStatus
      : rawStatus.startsWith("routing:")
        ? "routing"
        : rawStatus.startsWith("dispatching:")
          ? "dispatching"
          : rawStatus
    : null;

  const activeStatus = statusKey
    ? STATUS_LABELS[language][statusKey] ?? statusKey
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
          hasEvidencePanel
            ? "lg:grid-cols-[240px_minmax(0,1fr)_360px]"
            : "lg:grid-cols-[240px_minmax(0,1fr)]"
        }`}
      >
        <ChatSidebar
          locale={locale}
          newQuestion={translations.newQuestion}
          recentQuestions={recentQuestions}
          conversationSummaries={conversationSummaries}
          activeConversationId={activeConversationId}
          onNewQuestion={handleClearConversation}
          onSelectConversation={handleSelectConversation}
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
              onOpenPlacesPanel={() => {
                setPlacesPanelOpen(true);
                setPlacesOpen(true);
              }}
              onOpenSourcesPanel={() => {
                setSourcesPanelOpen(true);
                setPlacesOpen(true);
              }}
              messageId={msg.role === "assistant" ? `msg-${sessionId}-${i}` : undefined}
              sessionId={msg.role === "assistant" ? sessionId : undefined}
              turnIndex={msg.role === "assistant" ? i : undefined}
              reasoningLog={msg.reasoningLog}
              locale={locale}
              streamStatus={msg.streamStatus}
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

          {pendingLocationResolve && (
            <div className="my-4 rounded-xl border border-amber-200/50 bg-amber-50/50 p-4 backdrop-blur-md dark:border-amber-900/30 dark:bg-amber-950/20">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 rounded-full bg-amber-100 p-1.5 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300">
                  <MapPinned className="size-4" />
                </div>
                <div className="flex-1">
                  <h4 className="text-sm font-semibold text-amber-900 dark:text-amber-200">
                    {language === "vi" ? "Không thể truy cập vị trí" : "Location Access Failed"}
                  </h4>
                  <p className="mt-1 text-xs text-amber-700/80 dark:text-amber-300/80">
                    {language === "vi"
                      ? "Chúng tôi không thể lấy vị trí hiện tại của bạn. Bạn muốn xem gợi ý theo khu vực nào ở Phú Quốc?"
                      : "We could not access your current location. Which area would you like to explore?"}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        pendingLocationResolve({ lat: 10.1812, lng: 104.0492 });
                        setPendingLocationResolve(null);
                      }}
                      className="rounded-full bg-white dark:bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-[#0b5f63] shadow-sm hover:bg-slate-50 transition-colors border border-slate-200"
                    >
                      {language === "vi" ? "Làng chài Hàm Ninh" : "Ham Ninh Village"}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        pendingLocationResolve({ lat: 10.2155, lng: 103.9607 });
                        setPendingLocationResolve(null);
                      }}
                      className="rounded-full bg-white dark:bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-[#0b5f63] shadow-sm hover:bg-slate-50 transition-colors border border-slate-200"
                    >
                      {language === "vi" ? "Thị trấn Dương Đông" : "Duong Dong Town"}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        pendingLocationResolve({ lat: 10.0094, lng: 104.0119 });
                        setPendingLocationResolve(null);
                      }}
                      className="rounded-full bg-white dark:bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-[#0b5f63] shadow-sm hover:bg-slate-50 transition-colors border border-slate-200"
                    >
                      {language === "vi" ? "Phường An Thới" : "An Thoi Ward"}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        pendingLocationResolve({ denied: true });
                        setPendingLocationResolve(null);
                      }}
                      className="rounded-full bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 px-3.5 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 transition-colors"
                    >
                      {language === "vi" ? "Bỏ qua" : "Skip"}
                    </button>
                  </div>
                </div>
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
          {/* Header row for mobile controls and input hint */}
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
              {hasEvidencePanel && (
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

          {/* Premium consolidated input area */}
          <div className="flex flex-col rounded-2xl border border-[#e9e9e7] bg-white p-2.5 shadow-sm focus-within:border-[#0b5f63] focus-within:ring-2 focus-within:ring-[#0b5f63]/10">
            {/* Top row: text editor */}
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={translations.placeholder}
              disabled={loading}
              rows={1}
              className="max-h-36 min-h-10 w-full resize-none border-0 bg-transparent px-3 py-1.5 text-sm leading-6 text-[#37352f] placeholder:text-[#91918e] focus-visible:outline-none focus-visible:ring-0 disabled:opacity-50 sm:min-h-11 sm:px-3"
              aria-label={translations.placeholder}
            />

            {/* Bottom row: Filter selectors and action buttons */}
            <div className="mt-2.5 flex items-center justify-between border-t border-slate-100 pt-2 px-1">
              {/* Left: Toggles & Filters */}
              <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
                {/* Budget selection dropdown styled as a premium button */}
                <div className="relative inline-flex items-center">
                  <select
                    value={budgetFilter || ""}
                    onChange={(e) => setBudgetFilter(e.target.value || null)}
                    disabled={loading}
                    className="appearance-none rounded-full border border-slate-200/80 bg-slate-50/50 hover:bg-slate-50 py-1 pl-7 pr-4 text-xs font-semibold text-[#0b5f63] focus:outline-none focus:ring-1 focus:ring-[#0b5f63]/30 cursor-pointer transition-colors disabled:opacity-50"
                  >
                    <option value="">{language === "vi" ? "Bất kỳ ngân sách" : "Any budget"}</option>
                    <option value="free">{language === "vi" ? "Miễn phí" : "Free"}</option>
                    <option value="inexpensive">{language === "vi" ? "Giá rẻ" : "Inexpensive"}</option>
                    <option value="moderate">{language === "vi" ? "Bình dân" : "Moderate"}</option>
                    <option value="expensive">{language === "vi" ? "Sang trọng" : "Premium"}</option>
                  </select>
                  <div className="pointer-events-none absolute left-2.5 text-[#0b5f63] opacity-85">
                    <svg className="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect width="20" height="14" x="2" y="5" rx="2" />
                      <line x1="2" x2="22" y1="10" y2="10" />
                    </svg>
                  </div>
                </div>

                {/* Accessibility Toggle */}
                <button
                  type="button"
                  onClick={() => setAccessibilityRequired((prev) => !prev)}
                  disabled={loading}
                  className={`inline-flex items-center gap-1.5 rounded-full border py-1 px-3 text-xs font-semibold transition-colors disabled:opacity-50 ${
                    accessibilityRequired
                      ? "bg-[#0b5f63]/10 border-[#0b5f63]/25 text-[#0b5f63] hover:bg-[#0b5f63]/15"
                      : "bg-slate-50/50 border-slate-200/80 text-slate-500 hover:bg-slate-50"
                  }`}
                  title={language === "vi" ? "Ưu tiên lối đi xe lăn" : "Prefer wheelchair access"}
                >
                  <svg className="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="16" cy="4" r="1" />
                    <path d="m18 19 1-7-6 1" />
                    <path d="m5 8 3-3 5.5 2-2.36 4.57-3.64-1.31" />
                    <path d="M12 8v5" />
                    <path d="M9.5 13.5h2.5" />
                    <path d="M14 19a5 5 0 0 1-5-5H7a7 7 0 0 0 7 7Z" />
                  </svg>
                  <span>{language === "vi" ? "Tiếp cận xe lăn" : "Wheelchair access"}</span>
                </button>
              </div>

              {/* Right: Reset and Send */}
              <div className="flex items-center gap-1 sm:gap-1.5">
                {messages.length > 0 && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-500"
                    onClick={handleClearConversation}
                    disabled={loading}
                    aria-label={translations.newConversation ?? "New conversation"}
                    title={translations.newConversation ?? "New conversation"}
                  >
                    <Trash2 className="h-4.5 w-4.5" />
                  </Button>
                )}
                <Button
                  onClick={() => handleSubmit()}
                  disabled={loading || !input.trim()}
                  size="icon"
                  className="h-8 w-8 rounded-lg bg-[#0b5f63] text-white shadow-sm hover:bg-[#084d50] disabled:opacity-40"
                  aria-label={translations.send}
                  title={translations.send}
                >
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
                </Button>
              </div>
            </div>
          </div>
        </div>
      </footer>
        </main>

        {hasEvidencePanel && (
          <PlaceResultsPanel
            places={latestPlaces}
            citations={latestCitations}
            translations={placeTranslations}
            mobileOpen={placesOpen}
            placesOpen={placesPanelOpen}
            sourcesOpen={sourcesPanelOpen}
            onMobileClose={() => setPlacesOpen(false)}
            onTogglePlaces={() => setPlacesPanelOpen((open) => !open)}
            onToggleSources={() => setSourcesPanelOpen((open) => !open)}
          />
        )}
      </div>
    </div>
  );
}
