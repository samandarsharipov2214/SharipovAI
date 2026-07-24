export interface BillingStatus {
  status: string;
  plan_code: string;
  subscription_status: string;
  messages_used_this_period: number;
  message_limit: number | null;
  can_send_messages: boolean;
  current_period_started_at: string;
  current_period_end: string | null;
  stripe_publishable_key: string | null;
}

export interface CheckoutSessionResponse {
  status: string;
  checkout_url?: string | null;
  portal_url?: string | null;
}

export interface MarketRow {
  id: string;
  symbol: string;
  name: string;
  price: number | null;
  price_change_percentage_24h: number | null;
  market_cap: number | null;
}

export interface MarketOverviewResponse {
  status: string;
  markets: MarketRow[];
}
