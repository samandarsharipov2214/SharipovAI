import {
  useEffect,
  useId,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Send, Square } from "lucide-react";

import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { MAX_MESSAGE_LENGTH } from "../../types/chat";

const DRAFT_KEY = "sharipovai.chat.draft";

interface ChatComposerProps {
  isLoading: boolean;
  disabledReason?: string | null;
  onCancel: () => void;
  onSend: (message: string) => Promise<boolean>;
}

function initialDraft(): string {
  try {
    return sessionStorage.getItem(DRAFT_KEY)?.slice(0, MAX_MESSAGE_LENGTH) ?? "";
  } catch {
    return "";
  }
}

export function ChatComposer({ isLoading, disabledReason, onCancel, onSend }: ChatComposerProps) {
  const [draft, setDraft] = useState(initialDraft);
  const debouncedDraft = useDebouncedValue(draft, 250);
  const descriptionId = useId();
  const validationId = useId();
  const trimmed = debouncedDraft.trim();
  const tooLong = debouncedDraft.length > MAX_MESSAGE_LENGTH;
  const locked = Boolean(disabledReason);
  const canSend = trimmed.length > 0 && !tooLong && !isLoading && !locked;

  useEffect(() => {
    try {
      sessionStorage.setItem(DRAFT_KEY, debouncedDraft);
    } catch {
      // Draft persistence is optional; the controlled input remains available.
    }
  }, [debouncedDraft]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSend) return;

    const sent = await onSend(draft);
    if (sent) {
      setDraft("");
      try {
        sessionStorage.removeItem(DRAFT_KEY);
      } catch {
        // Ignore unavailable browser storage.
      }
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  return (
    <form className="border-t border-white/10 p-4 sm:p-5" onSubmit={submit}>
      <label className="sr-only" htmlFor="chat-message">
        Сообщение для SharipovAI
      </label>
      <div className="rounded-2xl border border-white/10 bg-slate-950/70 p-2 shadow-inner focus-within:border-cyan-300/60 focus-within:ring-2 focus-within:ring-cyan-300/15">
        <textarea
          id="chat-message"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          maxLength={MAX_MESSAGE_LENGTH}
          disabled={isLoading || locked}
          aria-describedby={`${descriptionId} ${validationId}`}
          aria-invalid={tooLong}
          placeholder={locked ? "Чат временно заблокирован до активации плана." : "Спросите про BTC, ETH, уровни, тренд или рыночный риск…"}
          className="min-h-24 w-full resize-y bg-transparent px-3 py-2 text-sm leading-6 text-white outline-none placeholder:text-slate-600 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <div className="flex flex-col gap-3 border-t border-white/5 px-2 pt-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs text-slate-500">
            <span id={descriptionId}>{disabledReason || "Enter — отправить, Shift+Enter — новая строка."}</span>
            <span
              id={validationId}
              className={tooLong ? "ml-2 text-rose-300" : "ml-2"}
              aria-live="polite"
            >
              {debouncedDraft.length}/{MAX_MESSAGE_LENGTH}
            </span>
          </div>
          {isLoading ? (
            <button className="secondary-button" type="button" onClick={onCancel}>
              <Square className="size-4" aria-hidden="true" />
              Остановить
            </button>
          ) : (
            <button className="primary-button" type="submit" disabled={!canSend}>
              <Send className="size-4" aria-hidden="true" />
              Отправить
            </button>
          )}
        </div>
      </div>
    </form>
  );
}
