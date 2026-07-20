export const MAX_MESSAGE_LENGTH = 4_000;
export const MAX_HISTORY_MESSAGES = 20;

export type ChatRole = "user" | "assistant";
export type MessageDelivery = "sent" | "pending" | "failed";
export type ChatStatus = "idle" | "sending" | "error";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  delivery: MessageDelivery;
}

export interface ChatRequestMessage {
  role: ChatRole;
  content: string;
}

export interface ChatRequest {
  message: string;
  history: ChatRequestMessage[];
}

export interface ChatResponse {
  text: string;
  model: string;
  requestId: string;
}

export interface ChatState {
  messages: ChatMessage[];
  status: ChatStatus;
  error: string | null;
  lastUserMessage: string | null;
}

export type ChatErrorCode =
  | "aborted"
  | "bad_request"
  | "forbidden"
  | "network"
  | "rate_limited"
  | "server"
  | "timeout"
  | "unauthorized"
  | "unknown";

export class ChatApiError extends Error {
  readonly code: ChatErrorCode;
  readonly status: number | null;
  readonly retryable: boolean;

  constructor(
    message: string,
    options: {
      code?: ChatErrorCode;
      status?: number | null;
      retryable?: boolean;
      cause?: unknown;
    } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = "ChatApiError";
    this.code = options.code ?? "unknown";
    this.status = options.status ?? null;
    this.retryable = options.retryable ?? false;
  }
}
