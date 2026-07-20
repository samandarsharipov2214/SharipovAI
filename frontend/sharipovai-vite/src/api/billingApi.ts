import { requestJson } from "./http";
import type {
  BillingStatus,
  CheckoutSessionResponse,
  MarketOverviewResponse,
} from "../types/billing";

export function fetchBillingStatus(): Promise<BillingStatus> {
  return requestJson<BillingStatus>("/api/billing/status");
}

export function createCheckoutSession(): Promise<CheckoutSessionResponse> {
  return requestJson<CheckoutSessionResponse>("/api/billing/checkout-session", {
    method: "POST",
  });
}

export function createPortalSession(): Promise<CheckoutSessionResponse> {
  return requestJson<CheckoutSessionResponse>("/api/billing/portal-session", {
    method: "POST",
  });
}

export function fetchMarketOverview(): Promise<MarketOverviewResponse> {
  return requestJson<MarketOverviewResponse>("/api/markets/overview");
}
