import {
  Activity,
  KeyRound,
  Monitor,
  Moon,
  ShieldCheck,
  Sparkles,
  Sun,
} from "lucide-react";

import { useTheme, type ThemePreference } from "../../hooks/useTheme";
import { ChatPanel } from "../chat/ChatPanel";

const statusCards = [
  {
    title: "Gemini credentials",
    value: "Server only",
    detail: "GEMINI_API_KEY не компилируется во frontend.",
    icon: KeyRound,
  },
  {
    title: "Chat transport",
    value: "Same-origin API",
    detail: "Cookie session, timeout, abort и no-store requests.",
    icon: ShieldCheck,
  },
  {
    title: "Execution authority",
    value: "Read-only AI",
    detail: "Чат не может отправлять raw orders или менять Mainnet lock.",
    icon: Activity,
  },
] as const;

const themeOptions: Array<{
  value: ThemePreference;
  label: string;
  icon: typeof Moon;
}> = [
  { value: "dark", label: "Тёмная", icon: Moon },
  { value: "light", label: "Светлая", icon: Sun },
  { value: "system", label: "Системная", icon: Monitor },
];

export function Dashboard() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="min-h-screen">
      <a className="skip-link" href="#main-content">
        Перейти к содержимому
      </a>

      <header className="border-b border-white/10 bg-slate-950/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="flex items-center gap-3">
            <div className="grid size-11 place-items-center rounded-2xl bg-gradient-to-br from-cyan-300 to-blue-500 text-slate-950 shadow-lg shadow-cyan-500/20">
              <Sparkles className="size-5" aria-hidden="true" />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
                SharipovAI OS
              </p>
              <h1 className="text-xl font-semibold text-white">Secure AI Operations</h1>
            </div>
          </div>

          <label className="flex items-center gap-3 text-sm text-slate-300">
            <span>Тема</span>
            <select
              className="min-h-11 rounded-xl border border-white/10 bg-slate-900 px-3 text-white outline-none focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/20"
              value={theme}
              onChange={(event) => setTheme(event.target.value as ThemePreference)}
            >
              {themeOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      <main id="main-content" className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <section aria-labelledby="security-status-title">
          <div className="mb-5 flex items-end justify-between gap-4">
            <div>
              <p className="eyebrow">Production architecture</p>
              <h2 id="security-status-title" className="mt-2 text-2xl font-semibold text-white">
                Безопасность чата
              </h2>
            </div>
            <span className="status-pill">
              <span className="size-2 rounded-full bg-emerald-300" aria-hidden="true" />
              Fail-closed
            </span>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {statusCards.map(({ title, value, detail, icon: Icon }) => (
              <article key={title} className="surface-card">
                <div className="grid size-10 place-items-center rounded-xl bg-cyan-400/10 text-cyan-300">
                  <Icon className="size-5" aria-hidden="true" />
                </div>
                <p className="mt-5 text-sm text-slate-400">{title}</p>
                <p className="mt-1 text-lg font-semibold text-white">{value}</p>
                <p className="mt-2 text-sm leading-6 text-slate-500">{detail}</p>
              </article>
            ))}
          </div>
        </section>

        <div className="mt-8">
          <ChatPanel />
        </div>
      </main>
    </div>
  );
}
