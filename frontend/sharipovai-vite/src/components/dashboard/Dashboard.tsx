import {
  Activity,
  KeyRound,
  LogOut,
  Monitor,
  Moon,
  ShieldCheck,
  Sparkles,
  Sun,
} from "lucide-react";

import { useBilling } from "../../hooks/useBilling";
import { useAuth } from "../../hooks/useAuth";
import { useTheme, type ThemePreference } from "../../hooks/useTheme";
import { AuthPanel } from "../auth/AuthPanel";
import { PricingPanel } from "../billing/PricingPanel";
import { ChatPanel } from "../chat/ChatPanel";
import { MarketOverview } from "../markets/MarketOverview";

const statusCards = [
  {
    title: "Gemini credentials",
    value: "Server only",
    detail: "GEMINI_API_KEY остаётся только в backend env.",
    icon: KeyRound,
  },
  {
    title: "Signal delivery",
    value: "Protected API",
    detail: "JWT cookie + same-origin + backend market context.",
    icon: ShieldCheck,
  },
  {
    title: "Execution authority",
    value: "Analysis only",
    detail: "SharipovAI даёт сигналы и анализ, но не торгует за пользователя.",
    icon: Activity,
  },
] as const;

const themeOptions: Array<{
  value: ThemePreference;
  label: string;
}> = [
  { value: "dark", label: "Тёмная" },
  { value: "light", label: "Светлая" },
  { value: "system", label: "Системная" },
];

export function Dashboard() {
  const { theme, setTheme } = useTheme();
  const auth = useAuth();
  const billing = useBilling(auth.status === "authenticated");
  const authenticated = auth.status === "authenticated" && Boolean(auth.user);
  const chatLockedReason = authenticated && billing.billing && !billing.billing.can_send_messages
    ? "Бесплатный лимит исчерпан. Оформите Pro plan, чтобы продолжить анализ рынка."
    : null;

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
                SharipovAI Signals
              </p>
              <h1 className="text-xl font-semibold text-white">AI Crypto Research SaaS</h1>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {authenticated && auth.user && (
              <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-300">
                {auth.user.display_name || auth.user.email}
              </div>
            )}
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
            {authenticated && (
              <button className="secondary-button" type="button" onClick={() => void auth.signOut()}>
                <LogOut className="size-4" aria-hidden="true" />
                Выйти
              </button>
            )}
          </div>
        </div>
      </header>

      <main id="main-content" className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:px-8">
        <section aria-labelledby="security-status-title">
          <div className="mb-5 flex items-end justify-between gap-4">
            <div>
              <p className="eyebrow">Production architecture</p>
              <h2 id="security-status-title" className="mt-2 text-2xl font-semibold text-white">
                Безопасный AI analysis stack
              </h2>
            </div>
            <span className="status-pill">
              <span className="size-2 rounded-full bg-emerald-300" aria-hidden="true" />
              Same-origin
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

        <MarketOverview markets={billing.markets} />

        {!authenticated ? (
          <AuthPanel
            busy={auth.busy}
            error={auth.error}
            onLogin={auth.login}
            onRegister={auth.register}
          />
        ) : (
          <div className="grid gap-8 xl:grid-cols-[1.2fr_0.8fr]">
            <div className="space-y-4">
              {billing.billing && (
                <div className="surface-card text-sm text-slate-300">
                  <p>
                    Сообщений в периоде: <span className="font-semibold text-white">{billing.billing.messages_used_this_period}</span>
                    {billing.billing.message_limit !== null ? (
                      <>
                        {" "}/ <span className="font-semibold text-white">{billing.billing.message_limit}</span>
                      </>
                    ) : (
                      " / unlimited"
                    )}
                  </p>
                  <p className="mt-2 text-slate-400">
                    План: {billing.billing.plan_code}, статус: {billing.billing.subscription_status}
                  </p>
                </div>
              )}
              <ChatPanel disabledReason={chatLockedReason} />
            </div>
            <PricingPanel
              billing={billing.billing}
              busy={billing.busy}
              error={billing.error}
              onCheckout={billing.startCheckout}
              onManage={billing.openPortal}
            />
          </div>
        )}
      </main>
    </div>
  );
}
