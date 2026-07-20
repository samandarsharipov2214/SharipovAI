import { useCallback, useEffect, useReducer, useRef } from "react";

import { requestChat } from "../api/chatApi";
import {
  clearStoredMessages,
  loadStoredMessages,
  saveStoredMessages,
} from "../lib/chatStorage";
import { createId } from "../lib/id";
import {
  ChatApiError,
  MAX_HISTORY_MESSAGES,
  MAX_MESSAGE_LENGTH,
  type ChatMessage,
  type ChatRequestMessage,
  type ChatState,
} from "../types/chat";

const INITIAL_STATE: ChatState = {
  messages: [],
  status: "idle",
  error: null,
  lastUserMessage: null,
};

type Action =
  | { type: "hydrate"; messages: ChatMessage[] }
  | { type: "append"; messages: ChatMessage[] }
  | { type: "replace"; id: string; message: ChatMessage }
  | { type: "remove"; id: string }
  | { type: "sending"; lastUserMessage: string }
  | { type: "error"; message: string }
  | { type: "idle" }
  | { type: "dismissError" }
  | { type: "clear" };

interface SubmitOptions {
  appendUserMessage: boolean;
  enforceDuplicateGuard: boolean;
}

function reducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case "hydrate":
      return { ...state, messages: action.messages };
    case "append":
      return { ...state, messages: [...state.messages, ...action.messages] };
    case "replace":
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.id === action.id ? action.message : message,
        ),
      };
    case "remove":
      return {
        ...state,
        messages: state.messages.filter((message) => message.id !== action.id),
      };
    case "sending":
      return {
        ...state,
        status: "sending",
        error: null,
        lastUserMessage: action.lastUserMessage,
      };
    case "error":
      return { ...state, status: "error", error: action.message };
    case "idle":
      return { ...state, status: "idle" };
    case "dismissError":
      return { ...state, error: null, status: "idle" };
    case "clear":
      return { ...INITIAL_STATE };
    default:
      return state;
  }
}

function requestHistory(messages: ChatMessage[]): ChatRequestMessage[] {
  return messages
    .filter((message) => message.delivery === "sent")
    .slice(-MAX_HISTORY_MESSAGES)
    .map(({ role, content }) => ({ role, content }));
}

function historyBeforeRetriedMessage(
  messages: ChatMessage[],
  retriedText: string,
): ChatRequestMessage[] {
  const history = requestHistory(messages);
  const last = history.at(-1);
  if (last?.role === "user" && last.content === retriedText) {
    history.pop();
  }
  return history;
}

function publicError(error: unknown): string {
  if (error instanceof ChatApiError) return error.message;
  return "Неизвестная ошибка. Повторите запрос.";
}

export function useChat() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE, (initial) => ({
    ...initial,
    messages: loadStoredMessages(),
  }));
  const controllerRef = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);
  const lastSubmissionRef = useRef<{ text: string; at: number } | null>(null);

  useEffect(() => {
    saveStoredMessages(state.messages);
  }, [state.messages]);

  useEffect(
    () => () => {
      controllerRef.current?.abort();
    },
    [],
  );

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    sendingRef.current = false;
  }, []);

  const submit = useCallback(
    async (rawText: string, options: SubmitOptions): Promise<boolean> => {
      const text = rawText.trim();
      if (!text || text.length > MAX_MESSAGE_LENGTH || sendingRef.current) {
        return false;
      }

      const now = Date.now();
      const previous = lastSubmissionRef.current;
      if (
        options.enforceDuplicateGuard &&
        previous?.text === text &&
        now - previous.at < 700
      ) {
        return false;
      }
      lastSubmissionRef.current = { text, at: now };

      const createdAt = new Date().toISOString();
      const pendingId = createId("assistant");
      const pendingMessage: ChatMessage = {
        id: pendingId,
        role: "assistant",
        content: "SharipovAI анализирует запрос…",
        createdAt,
        delivery: "pending",
      };
      const messagesToAppend: ChatMessage[] = [pendingMessage];

      if (options.appendUserMessage) {
        messagesToAppend.unshift({
          id: createId("user"),
          role: "user",
          content: text,
          createdAt,
          delivery: "sent",
        });
      }

      const history = options.appendUserMessage
        ? requestHistory(state.messages)
        : historyBeforeRetriedMessage(state.messages, text);
      const controller = new AbortController();
      controllerRef.current?.abort();
      controllerRef.current = controller;
      sendingRef.current = true;
      dispatch({ type: "append", messages: messagesToAppend });
      dispatch({ type: "sending", lastUserMessage: text });

      try {
        const response = await requestChat(
          {
            message: text,
            history,
          },
          controller.signal,
        );

        dispatch({
          type: "replace",
          id: pendingId,
          message: {
            id: pendingId,
            role: "assistant",
            content: response.text,
            createdAt: new Date().toISOString(),
            delivery: "sent",
          },
        });
        dispatch({ type: "idle" });
        return true;
      } catch (error) {
        dispatch({ type: "remove", id: pendingId });
        if (error instanceof ChatApiError && error.code === "aborted") {
          dispatch({ type: "idle" });
          return false;
        }
        dispatch({ type: "error", message: publicError(error) });
        return false;
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
        }
        sendingRef.current = false;
      }
    },
    [state.messages],
  );

  const sendMessage = useCallback(
    (rawText: string) =>
      submit(rawText, {
        appendUserMessage: true,
        enforceDuplicateGuard: true,
      }),
    [submit],
  );

  const retryLast = useCallback(() => {
    if (!state.lastUserMessage) return Promise.resolve(false);
    return submit(state.lastUserMessage, {
      appendUserMessage: false,
      enforceDuplicateGuard: false,
    });
  }, [state.lastUserMessage, submit]);

  const clearMessages = useCallback(() => {
    cancel();
    clearStoredMessages();
    dispatch({ type: "clear" });
  }, [cancel]);

  const dismissError = useCallback(
    () => dispatch({ type: "dismissError" }),
    [],
  );

  return {
    messages: state.messages,
    error: state.error,
    status: state.status,
    isLoading: state.status === "sending",
    canRetry: Boolean(state.lastUserMessage) && state.status === "error",
    sendMessage,
    retryLast,
    cancel,
    clearMessages,
    dismissError,
  } as const;
}
