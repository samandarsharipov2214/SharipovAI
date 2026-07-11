"""Read-only access to the owner's Bybit account.

This module never submits, amends, or cancels orders. It signs private GET
requests and normalizes wallet, position, and open-order data for SharipovAI.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    status: str
    source: str
    base_url: str
    received_at_ms: int
    total_equity: float
    total_wallet_balance: float
    total_available_balance: float
    total_perp_upl: float
    coins: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    open_orders: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BybitAccountClient:
    """Fetch a verified account snapshot without trading permissions."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.api_key = os.getenv("EXCHANGE_API_KEY", "").strip()
        self.api_secret = os.getenv("EXCHANGE_API_SECRET", "").strip()
        self.recv_window = os.getenv("BYBIT_RECV_WINDOW", "5000").strip() or "5000"
        self.timeout = max(float(os.getenv("BYBIT_ACCOUNT_TIMEOUT_SECONDS", "10")), 1.0)
        self._client = client

    def status(self) -> dict[str, Any]:
        return {
            "provider": "bybit",
            "mode": "live_read_only",
            "credentials_configured": bool(self.api_key and self.api_secret),
            "sync_enabled": _truthy("BYBIT_ACCOUNT_SYNC_ENABLED", default=True),
            "trading_enabled": _truthy("EXCHANGE_LIVE_TRADING_ENABLED"),
            "kill_switch": _truthy("EXECUTION_KILL_SWITCH", default=True),
            "candidate_hosts": self._candidate_base_urls(),
        }

    def fetch_snapshot(self) -> AccountSnapshot:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Bybit account credentials are not configured")
        if not _truthy("BYBIT_ACCOUNT_SYNC_ENABLED", default=True):
            raise RuntimeError("Bybit account synchronization is disabled")

        errors: list[str] = []
        for base_url in self._candidate_base_urls():
            try:
                wallet = self._private_get(base_url, "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
                positions = self._private_get(base_url, "/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
                spot_orders = self._private_get(base_url, "/v5/order/realtime", {"category": "spot", "openOnly": 0})
                linear_orders = self._private_get(base_url, "/v5/order/realtime", {"category": "linear", "openOnly": 0, "settleCoin": "USDT"})
                return self._normalize(base_url, wallet, positions, spot_orders, linear_orders)
            except Exception as exc:
                errors.append(f"{base_url}: {type(exc).__name__}: {exc}")
        raise RuntimeError("Unable to authenticate with Bybit personal account; " + " | ".join(errors))

    def save_snapshot(self, snapshot: AccountSnapshot) -> Path:
        path = Path(os.getenv("BYBIT_ACCOUNT_STATE_FILE", "/var/data/bybit_account.json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        return path

    def _private_get(self, base_url: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode(sorted((key, value) for key, value in params.items() if value is not None))
        timestamp = str(int(time.time() * 1000))
        signature_payload = f"{timestamp}{self.api_key}{self.recv_window}{query}"
        signature = hmac.new(self.api_secret.encode(), signature_payload.encode(), hashlib.sha256).hexdigest()
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": self.recv_window,
            "X-BAPI-SIGN": signature,
        }
        client = self._client or httpx.Client(timeout=self.timeout)
        close_client = self._client is None
        try:
            response = client.get(f"{base_url}{path}?{query}", headers=headers)
            response.raise_for_status()
            data = response.json()
        finally:
            if close_client:
                client.close()
        code = int(data.get("retCode", -1))
        if code != 0:
            raise RuntimeError(f"Bybit rejected request: {data.get('retMsg', 'unknown error')} ({code})")
        return data

    def _candidate_base_urls(self) -> list[str]:
        configured = os.getenv("BYBIT_ACCOUNT_BASE_URL", "").strip() or os.getenv("EXCHANGE_BASE_URL", "").strip()
        candidates = [configured, "https://api.bybit.eu", "https://api.bybit.com", "https://api.bybit.nl"]
        result: list[str] = []
        for value in candidates:
            clean = value.rstrip("/")
            if clean and "testnet" not in clean and clean not in result:
                result.append(clean)
        return result

    @staticmethod
    def _normalize(base_url: str, wallet: dict[str, Any], positions: dict[str, Any], *orders: dict[str, Any]) -> AccountSnapshot:
        accounts = wallet.get("result", {}).get("list", []) or []
        account = accounts[0] if accounts else {}
        coins: list[dict[str, Any]] = []
        for coin in account.get("coin", []) or []:
            equity = _number(coin.get("equity"))
            wallet_balance = _number(coin.get("walletBalance"))
            if equity == 0 and wallet_balance == 0:
                continue
            coins.append({
                "coin": str(coin.get("coin", "")),
                "equity": equity,
                "wallet_balance": wallet_balance,
                "available_to_withdraw": _number(coin.get("availableToWithdraw")),
                "unrealised_pnl": _number(coin.get("unrealisedPnl")),
                "usd_value": _number(coin.get("usdValue")),
            })

        normalized_positions: list[dict[str, Any]] = []
        for item in positions.get("result", {}).get("list", []) or []:
            size = _number(item.get("size"))
            if size == 0:
                continue
            normalized_positions.append({
                "symbol": str(item.get("symbol", "")),
                "side": str(item.get("side", "")),
                "size": size,
                "avg_price": _number(item.get("avgPrice")),
                "mark_price": _number(item.get("markPrice")),
                "unrealised_pnl": _number(item.get("unrealisedPnl")),
                "leverage": _number(item.get("leverage")),
                "liq_price": _number(item.get("liqPrice")),
            })

        normalized_orders: list[dict[str, Any]] = []
        for payload in orders:
            for item in payload.get("result", {}).get("list", []) or []:
                normalized_orders.append({
                    "order_id": str(item.get("orderId", "")),
                    "symbol": str(item.get("symbol", "")),
                    "side": str(item.get("side", "")),
                    "order_type": str(item.get("orderType", "")),
                    "price": _number(item.get("price")),
                    "qty": _number(item.get("qty")),
                    "cum_exec_qty": _number(item.get("cumExecQty")),
                    "status": str(item.get("orderStatus", "")),
                    "created_time": str(item.get("createdTime", "")),
                })

        return AccountSnapshot(
            status="connected",
            source="bybit_private_api_v5",
            base_url=base_url,
            received_at_ms=int(time.time() * 1000),
            total_equity=_number(account.get("totalEquity")),
            total_wallet_balance=_number(account.get("totalWalletBalance")),
            total_available_balance=_number(account.get("totalAvailableBalance")),
            total_perp_upl=_number(account.get("totalPerpUPL")),
            coins=coins,
            positions=normalized_positions,
            open_orders=normalized_orders,
        )


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _truthy(name: str, *, default: bool = False) -> bool:
    raw_default = "1" if default else "0"
    return os.getenv(name, raw_default).strip().lower() in {"1", "true", "yes", "on"}
