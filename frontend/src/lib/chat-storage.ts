import type { StoredUser } from "@/lib/auth-store";
import type { ChatStreamStatus, Citation, PlaceResult } from "@/lib/chat-api";
import type { MessageStatus } from "@/components/chat/message-bubble";

export const HAM_NINH_CHAT_STORAGE_VERSION = 1;

const MAX_CONVERSATIONS_PER_OWNER = 12;
const STORAGE_PREFIX = `ham_ninh_chat_v${HAM_NINH_CHAT_STORAGE_VERSION}`;

export interface StoredChatMessage {
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
  statusHistory?: ChatStreamStatus[];
}

export interface StoredChatConversation {
  id: string;
  sessionId: string;
  title: string;
  updatedAt: number;
  messages: StoredChatMessage[];
}

export interface ChatConversationSummary {
  id: string;
  title: string;
  updatedAt: number;
  messageCount: number;
}

function isClient(): boolean {
  return typeof window !== "undefined";
}

function storageKey(owner: string): string {
  return `${STORAGE_PREFIX}:${owner}`;
}

function normalizeTitle(messages: StoredChatMessage[]): string {
  const firstUserMessage = messages.find((message) => message.role === "user")?.content.trim();
  if (!firstUserMessage) return "Cuộc trò chuyện mới";
  return firstUserMessage.length > 72 ? `${firstUserMessage.slice(0, 69)}...` : firstUserMessage;
}

function isConversation(value: unknown): value is StoredChatConversation {
  if (typeof value !== "object" || value === null) return false;
  const maybe = value as StoredChatConversation;
  return (
    typeof maybe.id === "string" &&
    typeof maybe.sessionId === "string" &&
    typeof maybe.title === "string" &&
    typeof maybe.updatedAt === "number" &&
    Array.isArray(maybe.messages)
  );
}

export function getChatStorageOwner(user: StoredUser | null): string {
  return user?.id ? `user.${user.id}` : "guest";
}

export function createEmptyConversation(): StoredChatConversation {
  const id = crypto.randomUUID();
  return {
    id,
    sessionId: crypto.randomUUID(),
    title: "Cuộc trò chuyện mới",
    updatedAt: Date.now(),
    messages: [],
  };
}

export function loadChatConversations(owner: string): StoredChatConversation[] {
  if (!isClient()) return [];

  try {
    const raw = localStorage.getItem(storageKey(owner));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(isConversation)
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_CONVERSATIONS_PER_OWNER);
  } catch {
    return [];
  }
}

export function saveChatConversation(owner: string, conversation: StoredChatConversation): StoredChatConversation[] {
  if (!isClient()) return [];

  const normalized: StoredChatConversation = {
    ...conversation,
    title: normalizeTitle(conversation.messages),
    updatedAt: Date.now(),
  };
  const existing = loadChatConversations(owner).filter((item) => item.id !== normalized.id);
  const next = [normalized, ...existing].slice(0, MAX_CONVERSATIONS_PER_OWNER);
  localStorage.setItem(storageKey(owner), JSON.stringify(next));
  return next;
}

export function toConversationSummaries(conversations: StoredChatConversation[]): ChatConversationSummary[] {
  return conversations.map((conversation) => ({
    id: conversation.id,
    title: conversation.title,
    updatedAt: conversation.updatedAt,
    messageCount: conversation.messages.length,
  }));
}
