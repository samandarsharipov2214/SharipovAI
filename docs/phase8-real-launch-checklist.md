# Phase 8 Real Launch Checklist

A real bounded Testnet launch requires all items below. Missing evidence blocks the claim that the campaign ran.

- Phase 7 PR merged and deployed from reviewed commit.
- Required CI green for deployed commit.
- VPS production smoke check green.
- Isolated Bybit Testnet key present, without withdrawal/transfer permission.
- Private order and execution streams authenticated and fresh.
- Restart-safe reconciliation.
- Promoted Testnet experiment ID selected.
- No active campaign exists.
- Exact runtime and campaign confirmations entered by operator.
- Campaign evidence contains 20+ authenticated matched fills.
- Actual fees present.
- Zero orphan, duplicate, unmatched or unresolved evidence.
- Canonical final report generated.
- Phase 8 post-campaign analysis generated.
- Production kill switch restored after the window.

No automated agent may fill in missing evidence or claim completion from screenshots, Paper fills or accepted REST responses.
