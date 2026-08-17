"""Temporary read-only VPS diagnostic. DO NOT MERGE.

Runs only on the self-hosted CI runner. It performs GET requests and read-only
filesystem inspection; it never writes production state or calls mutation APIs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _get_json(path: str) -> dict[str, Any]:
    url = f"http://127.0.0.1:8000{path}"
    try:
        request = Request(url, method="GET", headers={"Accept": "application/json"})
        with urlopen(request, timeout=8) as response:  # noqa: S310 - fixed localhost URL
            raw = response.read(2_000_000).decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw[:4000]}
            return {"http_status": int(response.status), "payload": payload}
    except HTTPError as exc:
        raw = exc.read(100_000).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:4000]}
        return {"http_status": int(exc.code), "payload": payload}
    except (URLError, TimeoutError, OSError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _summarize_paper_state(state: dict[str, Any]) -> dict[str, Any]:
    trades = state.get("trades") if isinstance(state.get("trades"), list) else []
    positions = state.get("positions")
    if isinstance(positions, dict):
        open_positions = len(positions)
    elif isinstance(positions, list):
        open_positions = len(positions)
    else:
        open_positions = int(state.get("open_positions", 0) or 0)

    buys = [row for row in trades if isinstance(row, dict) and str(row.get("side", "")).upper() == "BUY"]
    sells = [row for row in trades if isinstance(row, dict) and str(row.get("side", "")).upper() == "SELL"]
    sell_pnls: list[float] = []
    for row in sells:
        value = row.get("net_pnl")
        if value is None:
            continue
        try:
            sell_pnls.append(float(value))
        except (TypeError, ValueError):
            continue

    wins = sum(1 for value in sell_pnls if value > 0)
    losses = sum(1 for value in sell_pnls if value < 0)
    breakeven = sum(1 for value in sell_pnls if value == 0)
    gross_wins = sum(value for value in sell_pnls if value > 0)
    gross_losses = -sum(value for value in sell_pnls if value < 0)
    profit_factor = None if gross_losses <= 0 else gross_wins / gross_losses

    shadow_records = state.get("v2_shadow_records")
    if isinstance(shadow_records, dict):
        shadow_rows = [row for row in shadow_records.values() if isinstance(row, dict)]
    elif isinstance(shadow_records, list):
        shadow_rows = [row for row in shadow_records if isinstance(row, dict)]
    else:
        shadow_rows = []
    challenger_actions: dict[str, int] = {}
    champion_actions: dict[str, int] = {}
    disagreements = 0
    settled_shadow = 0
    for row in shadow_rows:
        challenger = str(row.get("challenger_action") or row.get("challenger_decision") or "UNKNOWN").upper()
        champion = str(row.get("champion_action") or row.get("champion_decision") or "UNKNOWN").upper()
        challenger_actions[challenger] = challenger_actions.get(challenger, 0) + 1
        champion_actions[champion] = champion_actions.get(champion, 0) + 1
        if challenger != "UNKNOWN" and champion != "UNKNOWN" and challenger != champion:
            disagreements += 1
        if row.get("settlement") or row.get("paper_settlement") or row.get("settled_at_ms"):
            settled_shadow += 1

    peak = state.get("peak_equity")
    equity = state.get("equity")
    current_drawdown_percent = None
    try:
        peak_f = float(peak)
        equity_f = float(equity)
        if peak_f > 0:
            current_drawdown_percent = max(0.0, (peak_f - equity_f) / peak_f * 100.0)
    except (TypeError, ValueError):
        pass

    return {
        "mode": state.get("mode"),
        "cash": state.get("cash"),
        "equity": state.get("equity"),
        "peak_equity": state.get("peak_equity"),
        "current_drawdown_percent": current_drawdown_percent,
        "realized_pnl": state.get("realized_pnl", state.get("net_pnl")),
        "unrealized_pnl": state.get("unrealized_pnl"),
        "total_fees": state.get("total_fees"),
        "trade_history_count": state.get("trade_history_count", len(trades)),
        "cached_trade_count": len(trades),
        "buy_count_cached": len(buys),
        "sell_count_cached": len(sells),
        "closed_trade_count_cached": len(sells),
        "open_positions": open_positions,
        "wins_cached": wins,
        "losses_cached": losses,
        "breakeven_cached": breakeven,
        "win_rate_percent_cached": (wins / len(sell_pnls) * 100.0) if sell_pnls else None,
        "closed_net_pnl_sum_cached": sum(sell_pnls),
        "profit_factor_cached": profit_factor,
        "last_action": state.get("last_action"),
        "last_reason": state.get("last_reason"),
        "worker_running": state.get("worker_running"),
        "market_stream": state.get("market_stream"),
        "v2_shadow_record_count": len(shadow_rows),
        "v2_shadow_error_count": len(state.get("v2_shadow_errors") or []) if isinstance(state.get("v2_shadow_errors"), list) else None,
        "v2_challenger_actions": challenger_actions,
        "v2_champion_actions": champion_actions,
        "v2_champion_challenger_disagreements": disagreements,
        "v2_settled_shadow_records": settled_shadow,
    }


def _read_candidate_state_files() -> list[dict[str, Any]]:
    root = Path("/var/lib/sharipovai")
    result: list[dict[str, Any]] = []
    if not root.exists():
        return [{"path": str(root), "error": "missing"}]
    try:
        candidates = [
            path
            for path in root.rglob("*.json")
            if any(token in path.name.lower() for token in ("paper", "virtual", "trade", "shadow", "decision"))
        ][:40]
    except OSError as exc:
        return [{"path": str(root), "error": f"{type(exc).__name__}: {exc}"}]

    for path in candidates:
        row: dict[str, Any] = {"path": str(path)}
        try:
            row["size"] = path.stat().st_size
            if path.stat().st_size <= 2_000_000:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    row["summary"] = _summarize_paper_state(payload)
                    row["top_level_keys"] = sorted(str(key) for key in payload.keys())[:100]
                else:
                    row["json_type"] = type(payload).__name__
        except Exception as exc:  # diagnostic must report permissions/corruption without failing CI
            row["error"] = f"{type(exc).__name__}: {exc}"
        result.append(row)
    return result


def test_vps_readonly_paper_diagnostic(record_property) -> None:
    endpoints = {
        path: _get_json(path)
        for path in (
            "/health",
            "/api/release/status",
            "/api/security/status",
            "/api/market/stream/status",
            "/api/autonomous-paper/status",
            "/api/autonomous-paper/decision-runtime",
            "/api/virtual-account/state",
        )
    }
    paper_response = endpoints.get("/api/autonomous-paper/status", {})
    paper_payload = paper_response.get("payload") if isinstance(paper_response, dict) else None
    report = {
        "diagnostic": "read_only_vps_paper_metrics",
        "localhost_endpoints": endpoints,
        "autonomous_paper_summary": _summarize_paper_state(paper_payload) if isinstance(paper_payload, dict) else None,
        "candidate_state_files": _read_candidate_state_files(),
    }
    record_property("vps_readonly_paper_diagnostic", json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
    assert True
