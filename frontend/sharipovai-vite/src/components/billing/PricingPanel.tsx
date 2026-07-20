import { BadgeDollarSign, Crown, Wallet } from "lucide-react";

import type { BillingStatus } from "../../types/billing";

interface PricingPanelProps {
  billing: BillingStatus | null;
  busy: boolean;
  error: string | null;
  onCheckout: () => Promise<void>;
  onManage: () => Promise<void>;
}

export function PricingPanel({
  billing,
  busy,
  error,
  onCheckout,
  onManage,
}: PricingPanelProps) {
  const active = billing?.subscription_status === "active" || billing?.subscription_status === "trialing";

  return (
    <section className="surface-card" aria-labelledby="pricing-title">
      <div className="flex items-center gap-3 text-amber-300">
        <Crown className="size-5" aria-hidden="true" />
        <h2 id="pricing-title" className="text-lg font-semibold text-white">
          SharipovAI Pro Signals
        </h2>
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-400">
        Бесплатный тариф даёт ограниченное число сообщений в месяц. Подписка снимает лимит и
        открывает непрерывный AI-анализ рынка.
      </p>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <article className="rounded-2xl border border-white/10 bg-slate-900/70 p-5">
          <div className="flex items-center gap-2 text-slate-200">
            <Wallet className="size-4" aria-hidden="true" />
            Free
          </div>
          <p className="mt-3 text-3xl font-semibold text-white">$0</p>
          <p className="mt-2 text-sm text-slate-400">{billing?.message_limit ?? 25} AI-запросов в месяц.</p>
        </article>
        <article className="rounded-2xl border border-cyan-300/30 bg-cyan-300/10 p-5">
          <div className="flex items-center gap-2 text-cyan-200">
            <BadgeDollarSign className="size-4" aria-hidden="true" />
            Pro Monthly
          </div>
          <p className="mt-3 text-3xl font-semibold text-white">Stripe plan</p>
          <p className="mt-2 text-sm text-slate-200">Unlimited market-analysis messages, billing portal, webhook sync.</p>
        </article>
      </div>
      {billing && (
        <p className="mt-4 text-sm text-slate-400">
          Текущий план: <span className="font-medium text-white">{billing.plan_code}</span>, статус: {billing.subscription_status}
        </p>
      )}
      {error && <p className="mt-3 text-sm text-rose-300">{error}</p>}
      <div className="mt-5 flex flex-wrap gap-3">
        <button className="primary-button" type="button" onClick={() => void onCheckout()} disabled={busy || active}>
          Оформить подписку
        </button>
        <button className="secondary-button" type="button" onClick={() => void onManage()} disabled={busy || !active}>
          Управлять биллингом
        </button>
      </div>
    </section>
  );
}
