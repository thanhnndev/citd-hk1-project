import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const storage = await readFile(
  new URL("../src/lib/chat-storage.ts", import.meta.url),
  "utf8",
).catch(() => "");
const chatInterface = await readFile(
  new URL("../src/components/chat/chat-interface.tsx", import.meta.url),
  "utf8",
);
const sidebar = await readFile(
  new URL("../src/components/chat/chat-sidebar.tsx", import.meta.url),
  "utf8",
);

assert.match(storage, /HAM_NINH_CHAT_STORAGE_VERSION/);
assert.match(storage, /getChatStorageOwner/);
assert.match(storage, /loadChatConversations/);
assert.match(storage, /saveChatConversation/);
assert.match(storage, /createEmptyConversation/);
assert.match(storage, /user\.id/);

assert.match(chatInterface, /getUser/);
assert.match(chatInterface, /loadChatConversations/);
assert.match(chatInterface, /saveChatConversation/);
assert.match(chatInterface, /activeConversationId/);
assert.match(chatInterface, /handleSelectConversation/);
assert.match(chatInterface, /conversationSummaries/);

assert.match(sidebar, /conversationSummaries/);
assert.match(sidebar, /activeConversationId/);
assert.match(sidebar, /onSelectConversation/);
assert.match(sidebar, /button/);

console.log("S15 account chat history contract passed.");
