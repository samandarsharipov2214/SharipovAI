import { z } from "zod";

import type { ChatMessage } from "../types/chat";

const STORAGE_KEY = "sharipovai.chat.v1";
const MAX_STORED_MESSAGES = 50;

const messageSchema = z.object({
  id: z.string().min(1).max(160),
  role: z.enum(["user", "assistant"]),
  content: z.string().min(1).max(8_000),
  createdAt: z.iso.datetime(),
  delivery: z.enum(["sent", "pending", "failed"]),
});

const storedMessagesSchema = z.array(messageSchema).max(MAX_STORED_MESSAGES);

export function loadStoredMessages(): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];

    const parsed = storedMessagesSchema.safeParse(JSON.parse(raw));
    if (!parsed.success) {
      sessionStorage.removeItem(STORAGE_KEY);
      return [];
    }

    return parsed.data.filter((message) => message.delivery === "sent");
  } catch {
    return [];
  }
}

export function saveStoredMessages(messages: ChatMessage[]): void {
  try {
    const safeMessages = messages
      .filter((message) => message.delivery === "sent")
      .slice(-MAX_STORED_MESSAGES);
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(safeMessages));
  } catch {
    // Storage can be unavailable in private mode. Chat remains functional in memory.
  }
}

export function clearStoredMessages(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // No-op when browser storage is unavailable.
  }
}
