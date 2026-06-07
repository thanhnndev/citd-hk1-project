"use client";

import {
  CircleHelp,
  Compass,
  Hotel,
  Map,
  MessageSquarePlus,
  Settings,
  Tag,
  Ticket,
  X,
} from "lucide-react";

import type { ChatConversationSummary } from "@/lib/chat-storage";

interface ChatSidebarProps {
  locale: string;
  newQuestion: string;
  recentQuestions: string[];
  conversationSummaries: ChatConversationSummary[];
  activeConversationId: string | null;
  onNewQuestion: () => void;
  onSelectConversation: (conversationId: string) => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export function ChatSidebar({
  locale,
  newQuestion,
  recentQuestions,
  conversationSummaries,
  activeConversationId,
  onNewQuestion,
  onSelectConversation,
  mobileOpen,
  onMobileClose,
}: ChatSidebarProps) {
  const isVi = locale !== "en";
  const categories = isVi
    ? [
        [Compass, "Tours & Lịch trình"],
        [Tag, "Giá & Ưu đãi"],
        [Hotel, "Khách sạn & Resort"],
        [Ticket, "Vé & Đặt chỗ"],
      ]
    : [
        [Compass, "Tours & itineraries"],
        [Tag, "Prices & offers"],
        [Hotel, "Hotels & resorts"],
        [Ticket, "Tickets & booking"],
      ];

  const formatUpdatedAt = (updatedAt: number): string => {
    const date = new Date(updatedAt);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleDateString(isVi ? "vi-VN" : "en-US", {
      month: "short",
      day: "numeric",
    });
  };

  const content = (
    <div className="flex h-full min-h-0 flex-col">
      <div className="p-5">
        <div className="mb-7 flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-lg bg-[#2383e2] text-white">
            <Map aria-hidden="true" className="size-4" />
          </span>
          <span className="truncate text-sm font-semibold text-[#37352f]">
            Hàm Ninh AI
          </span>
          <button
            type="button"
            className="ml-auto rounded-md p-1 text-[#787774] hover:bg-black/5 lg:hidden"
            onClick={onMobileClose}
            aria-label={isVi ? "Đóng menu" : "Close menu"}
          >
            <X className="size-4" />
          </button>
        </div>

        <nav className="space-y-1" aria-label={isVi ? "Điều hướng chat" : "Chat navigation"}>
          <button
            type="button"
            onClick={() => {
              onNewQuestion();
              onMobileClose();
            }}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm font-medium text-[#37352f] hover:bg-black/[0.06]"
          >
            <MessageSquarePlus className="size-4 text-[#787774]" />
            {newQuestion}
          </button>
          {categories.map(([Icon, label], index) => (
            <div
              key={label as string}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm ${
                index === 3
                  ? "bg-black/[0.06] font-medium text-[#37352f]"
                  : "text-[#787774]"
              }`}
            >
              <Icon className="size-4" />
              <span>{label as string}</span>
            </div>
          ))}
        </nav>

        <div className="mt-8">
          <p className="px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#91918e]">
            {isVi ? "Lịch sử tài khoản" : "Account history"}
          </p>
          <div className="mt-2 space-y-1">
            {conversationSummaries.length > 0 ? (
              conversationSummaries.map((conversation) => (
                <button
                  key={conversation.id}
                  type="button"
                  onClick={() => {
                    onSelectConversation(conversation.id);
                    onMobileClose();
                  }}
                  className={`w-full rounded-lg px-3 py-2.5 text-left transition-colors ${
                    conversation.id === activeConversationId
                      ? "bg-[#e7f2fb] text-[#005d90]"
                      : "text-[#787774] hover:bg-black/[0.05]"
                  }`}
                  title={conversation.title}
                >
                  <span className="block truncate text-xs font-semibold">
                    {conversation.title}
                  </span>
                  <span className="mt-1 flex items-center justify-between gap-2 text-[10px] text-[#91918e]">
                    <span>
                      {conversation.messageCount} {isVi ? "tin nhắn" : "messages"}
                    </span>
                    <span>{formatUpdatedAt(conversation.updatedAt)}</span>
                  </span>
                </button>
              ))
            ) : recentQuestions.length > 0 ? (
              recentQuestions.map((question, index) => (
                <p
                  key={`${index}-${question}`}
                  className="truncate rounded-md px-3 py-2 text-xs text-[#787774]"
                  title={question}
                >
                  {question}
                </p>
              ))
            ) : (
              <p className="px-3 py-2 text-xs text-[#91918e]">
                {isVi ? "Chưa có câu hỏi" : "No questions yet"}
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="mt-auto flex items-center justify-between border-t border-[#e9e9e7] p-4 text-[#787774]">
        <button type="button" className="rounded p-1.5 hover:bg-black/5" aria-label={isVi ? "Cài đặt" : "Settings"}>
          <Settings className="size-4" />
        </button>
        <button type="button" className="rounded p-1.5 hover:bg-black/5" aria-label={isVi ? "Trợ giúp" : "Help"}>
          <CircleHelp className="size-4" />
        </button>
      </div>
    </div>
  );

  return (
    <>
      <aside className="hidden h-full min-h-0 w-60 shrink-0 border-r border-[#e9e9e7] bg-[#f7f7f5] lg:block">
        {content}
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Chat navigation">
          <button
            type="button"
            className="absolute inset-0 bg-black/25"
            onClick={onMobileClose}
            aria-label={isVi ? "Đóng menu" : "Close menu"}
          />
          <aside className="relative h-full w-72 max-w-[85vw] border-r border-[#e9e9e7] bg-[#f7f7f5] shadow-xl">
            {content}
          </aside>
        </div>
      )}
    </>
  );
}
