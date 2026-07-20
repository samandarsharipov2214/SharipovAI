import { useEffect, useRef } from "react";
import { Bot, LoaderCircle, UserRound } from "lucide-react";

import type { ChatMessage } from "../../types/chat";

interface MessageListProps {
  messages: ChatMessage[];
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : new Intl.DateTimeFormat("ru-RU", {
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
}

export function MessageList({ messages }: MessageListProps) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="grid min-h-80 place-items-center px-6 text-center">
        <div className="max-w-md">
          <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-cyan-400/10 text-cyan-300">
            <Bot className="size-7" aria-hidden="true" />
          </div>
          <h2 className="mt-5 text-lg font-semibold text-white">Безопасный AI-чат</h2>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Сообщения отправляются на ваш backend. Gemini API key не попадает в браузер,
            localStorage или frontend bundle.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="min-h-80 space-y-4 overflow-y-auto px-4 py-5 sm:px-6"
      role="log"
      aria-live="polite"
      aria-relevant="additions text"
      aria-label="История чата"
    >
      {messages.map((message) => {
        const user = message.role === "user";
        return (
          <article
            key={message.id}
            className={`flex gap-3 ${user ? "justify-end" : "justify-start"}`}
          >
            {!user && (
              <div className="mt-1 grid size-9 shrink-0 place-items-center rounded-xl bg-cyan-400/10 text-cyan-300">
                <Bot className="size-4" aria-hidden="true" />
              </div>
            )}
            <div
              className={`max-w-[88%] rounded-2xl px-4 py-3 text-sm leading-6 shadow-lg sm:max-w-[76%] ${
                user
                  ? "rounded-br-md bg-cyan-300 text-slate-950"
                  : "rounded-bl-md border border-white/10 bg-slate-900/85 text-slate-100"
              }`}
            >
              <p className="whitespace-pre-wrap break-words">{message.content}</p>
              <div
                className={`mt-2 flex items-center gap-2 text-[11px] ${
                  user ? "text-slate-700" : "text-slate-500"
                }`}
              >
                {message.delivery === "pending" && (
                  <LoaderCircle className="size-3 animate-spin" aria-hidden="true" />
                )}
                <time dateTime={message.createdAt}>{formatTime(message.createdAt)}</time>
              </div>
            </div>
            {user && (
              <div className="mt-1 grid size-9 shrink-0 place-items-center rounded-xl bg-white/10 text-slate-200">
                <UserRound className="size-4" aria-hidden="true" />
              </div>
            )}
          </article>
        );
      })}
      <div ref={endRef} aria-hidden="true" />
    </div>
  );
}
