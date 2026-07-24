import { useCallback, useEffect, useState } from "react";

import {
  createCheckoutSession,
  createPortalSession,
  fetchBillingStatus,
  fetchMarketOverview,
} from "../api/billingApi";
import { ApiClientError } from "../api/http";
import type { BillingStatus, MarketRow } from "../types/billing";

export function useBilling(enabled: boolean) {
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [markets, setMarkets] = useState<MarketRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshBilling = useCallback(async () => {
    if (!enabled) {
      setBilling(null);
      return;
    }
    try {
      setBilling(await fetchBillingStatus());
      setError(null);
    } catch (error) {
      setError(error instanceof ApiClientError ? error.message : "Не удалось загрузить подписку.");
    }
  }, [enabled]);

  const refreshMarkets = useCallback(async () => {
    try {
      const response = await fetchMarketOverview();
      setMarkets(response.markets);
    } catch {
      setMarkets([]);
    }
  }, []);

  useEffect(() => {
    void refreshMarkets();
  }, [refreshMarkets]);

  useEffect(() => {
    void refreshBilling();
  }, [refreshBilling]);

  const startCheckout = useCallback(async () => {
    setBusy(true);
    try {
      const session = await createCheckoutSession();
      if (session.checkout_url) {
        window.location.href = session.checkout_url;
      }
    } catch (error) {
      setError(error instanceof ApiClientError ? error.message : "Не удалось открыть оплату.");
    } finally {
      setBusy(false);
    }
  }, []);

  const openPortal = useCallback(async () => {
    setBusy(true);
    try {
      const session = await createPortalSession();
      if (session.portal_url) {
        window.location.href = session.portal_url;
      }
    } catch (error) {
      setError(error instanceof ApiClientError ? error.message : "Не удалось открыть billing portal.");
    } finally {
      setBusy(false);
    }
  }, []);

  return {
    billing,
    markets,
    error,
    busy,
    refreshBilling,
    startCheckout,
    openPortal,
  } as const;
}
