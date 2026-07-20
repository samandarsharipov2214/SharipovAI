import { RotateCcw, ShieldCheck, Trash2, X } from "lucide-react";

import { useChat } from "../../hooks/useChat";
import { ChatComposer } from "./ChatComposer";
import { MessageList } from "./MessageList";

export function ChatPanel() {
  const {
    messages,
    error,
    isLoading,
    canRetry,
    sendMessage,
    retryLast,
    cancel,
    clearMessages,
    dismissError,
  } = useChat();

  const clear = () => {
    if (messages.length === 0 || window.confirm("Очистить историю чата в этой вкладке?")) {
      clearMessages();
    }
  };

  return (
    <section
      className="overflow-hidden rounded-3xl border border-white/10 bg-slate-950/65 shadow-2xl backdrop-blur-xl"
      aria-labelledby="chat-title"
    >
      <header className="flex flex-col gap-4 border-b border-white/10 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-emerald-300">
            <ShieldCheck className="size-4" aria-hidden="true" />
            Server-side Gemini proxy
          </div>
          <h2 id="chat-title" className="mt-2 text-xl font-semibold text-white">
            General Controller Chat
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            Ответы являются аналитической поддержкой, а не разрешением на сделку.
          </p>
        </div>
        <button
          className="secondary-button self-start"
          type="button"
          onClick={clear}
          disabled={messages.length === 0 || isLoading}
        >
          <Trash2 className="size-4" aria-hidden="true" />
          Очистить
        </button>
      </header>

      {error && (
        <div
          className="m-4 flex flex-col gap-3 rounded-2xl border border-rose-400/30 bg-rose-400/10 p-4 text-sm text-rose-100 sm:flex-row sm:items-center sm:justify-between"
          role="alert"
        >
          <span>{error}</span>
          <div className="flex items-center gap-2">
            {canRetry && (
              <button className="secondary-button" type="button" onClick={() => void retryLast()}>
                <RotateCcw className="size-4" aria-hidden="true" />
                Повторить
              </button>
            )}
            <button
              className="icon-button"
              type="button"
              onClick={dismissError}
              aria-label="Закрыть сообщение об ошибке"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      <MessageList messages={messages} />
      <ChatComposer isLoading={isLoading} onCancel={cancel} onSend={sendMessage} />
    </section>
  );
}
