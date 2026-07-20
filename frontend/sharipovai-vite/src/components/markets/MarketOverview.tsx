import { TrendingDown, TrendingUp } from "lucide-react";

import type { MarketRow } from "../../types/billing";

interface MarketOverviewProps {
  markets: MarketRow[];
}

function formatCurrency(value: number | null): string {
  return typeof value === "number" ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value) : "—";
}

export function MarketOverview({ markets }: MarketOverviewProps) {
  return (
    <section aria-labelledby="market-overview-title">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Backend market context</p>
          <h2 id="market-overview-title" className="mt-2 text-2xl font-semibold text-white">
            Crypto market snapshot
          </h2>
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
        {markets.map((market) => {
          const positive = (market.price_change_percentage_24h ?? 0) >= 0;
          const Icon = positive ? TrendingUp : TrendingDown;
          return (
            <article key={market.id} className="surface-card">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">{market.symbol}</p>
                  <p className="mt-1 text-sm text-slate-400">{market.name}</p>
                </div>
                <Icon className={`size-4 ${positive ? "text-emerald-300" : "text-rose-300"}`} aria-hidden="true" />
              </div>
              <p className="mt-4 text-lg font-semibold text-white">{formatCurrency(market.price)}</p>
              <p className={`mt-2 text-sm ${positive ? "text-emerald-300" : "text-rose-300"}`}>
                {market.price_change_percentage_24h?.toFixed(2) ?? "—"}% / 24h
              </p>
            </article>
          );
        })}
      </div>
    </section>
  );
}
