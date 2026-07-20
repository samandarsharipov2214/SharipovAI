import { z } from "zod";

import {
  ChatApiError,
  type ChatRequest,
  type ChatResponse,
} from "../types/chat";

const responseSchema = z.object({
  text: z.string().min(1),
  model: z.string().min(1),
  request_id: z.string().min(1),
});

const errorSchema = z
  .object({
    detail: z.union([
      z.string(),
      z.object({
        status: z.string().optional(),
        message: z.string().optional(),
      }),
    ]).optional(),
  })
  .passthrough();

const REQUEST_TIMEOUT_MS = 35_000;

function apiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL?.trim();
  if (!raw) {
    return "";
  }

  const parsed = new URL(raw);
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new ChatApiError("Некорректный адрес API.", {
      code: "bad_request",
    });
  }

  return parsed.origin;
}

function endpoint(path: string): string {
  return `${apiBaseUrl()}${path}`;
}

function errorCode(status: number): ChatApiError["code"] {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 429) return "rate_limited";
  if (status >= 400 && status < 500) return "bad_request";
  return "server";
}

function userMessage(status: number): string {
  if (status === 401) return "Сессия завершена. Войдите снова.";
  if (status === 403) return "Для чата недостаточно прав.";
  if (status === 429) return "Слишком много запросов. Подождите немного.";
  if (status >= 500) return "AI-сервис временно недоступен.";
  return "Запрос отклонён. Проверьте текст сообщения.";
}

async function safeJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return null;
  }

  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function requestChat(
  payload: ChatRequest,
  externalSignal?: AbortSignal,
): Promise<ChatResponse> {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(new DOMException("Request timed out", "TimeoutError")),
    REQUEST_TIMEOUT_MS,
  );
  const abortFromOutside = () => controller.abort(externalSignal?.reason);

  externalSignal?.addEventListener("abort", abortFromOutside, { once: true });

  try {
    const response = await fetch(endpoint("/api/ai/chat"), {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
      cache: "no-store",
      redirect: "error",
    });

    const data = await safeJson(response);
    if (!response.ok) {
      const parsedError = errorSchema.safeParse(data);
      const serverMessage = parsedError.success
        ? typeof parsedError.data.detail === "string"
          ? parsedError.data.detail
          : parsedError.data.detail?.message
        : undefined;

      throw new ChatApiError(serverMessage || userMessage(response.status), {
        code: errorCode(response.status),
        status: response.status,
        retryable: response.status === 429 || response.status >= 500,
      });
    }

    const parsed = responseSchema.safeParse(data);
    if (!parsed.success) {
      throw new ChatApiError("Сервер вернул некорректный ответ.", {
        code: "server",
        status: response.status,
        retryable: true,
      });
    }

    return {
      text: parsed.data.text,
      model: parsed.data.model,
      requestId: parsed.data.request_id,
    };
  } catch (error) {
    if (error instanceof ChatApiError) {
      throw error;
    }

    if (controller.signal.aborted) {
      if (externalSignal?.aborted) {
        throw new ChatApiError("Запрос отменён.", {
          code: "aborted",
          cause: error,
        });
      }

      throw new ChatApiError("AI не ответил вовремя.", {
        code: "timeout",
        retryable: true,
        cause: error,
      });
    }

    throw new ChatApiError("Не удалось связаться с сервером.", {
      code: "network",
      retryable: true,
      cause: error,
    });
  } finally {
    window.clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", abortFromOutside);
  }
}
