"""Controls progression from paper to testnet, limited live, and scaling."""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .evidence_integrity import eligible_closed_trades
from .execution_journal import ExecutionJournal


@dataclass(frozen=True, slots=True)
class StageAssessment:
    current_stage: int
    eligible_stage: int
    decision: str
    blockers: tuple[str, ...]
    metrics: dict[str, float]
    recommended_max_notional_usdt: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StageController:
    """Evaluate persisted evidence before allowing a higher execution stage.

    Only verified market-backed closed trades are accepted as promotion evidence.
    Synthetic, demo, fixture and timer-derived activity is excluded fail-closed.
    """

    def __init__(self, state_file: str | None = None, journal: ExecutionJournal | None = None) -> None:
        self.state_file = Path(state_file or os.getenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json"))
        self.journal = journal or ExecutionJournal()

    def assess(self) -> StageAssessment:
        state = self._load()
        raw_trades = state.get("trades", [])
        if not isinstance(raw_trades, list):
            raw_trades = []
        raw_closed = [
            item
            for item in raw_trades
            if isinstance(item, dict) and item.get("side") == "SELL" and item.get("net_pnl") is not None
        ]
        trades, rejected = eligible_closed_trades(raw_closed)
        trades = sorted(trades, key=lambda item: int(item["created_at_ms"]))
        pnls = [float(item["net_pnl"]) for item in trades]
        wins = sum(1 for value in pnls if value > 0)
        total = len(pnls)
        win_rate = wins / total * 100 if total else 0.0
        net_profit = sum(pnls)
        gross_loss = abs(sum(value for value in pnls if value < 0))
        gross_profit = sum(value for value in pnls if value > 0)
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)
        initial = _positive_env("AUTONOMOUS_PAPER_INITIAL_CASH", 10_000.0)
        reported_equity = _finite_or_default(state.get("equity"), initial)
        evidence_equity, drawdown = _evidence_equity_and_max_drawdown(initial, pnls)
        execution = self.journal.summary()
        testnet_orders = int(execution["verified_testnet_orders"])
        live_orders = int(execution["verified_live_orders"])
        metrics = {
            "closed_trades": float(total),
            "raw_closed_trades": float(len(raw_closed)),
            "rejected_evidence_trades": float(len(rejected)),
            "win_rate_percent": round(win_rate, 3),
            "net_profit": round(net_profit, 8),
            "profit_factor": round(profit_factor, 3),
            "drawdown_percent": round(drawdown, 3),
            "reported_equity": round(reported_equity, 8),
            "evidence_equity": round(evidence_equity, 8),
            "verified_testnet_orders": float(testnet_orders),
            "verified_live_orders": float(live_orders),
        }
        blockers: list[str] = []
        eligible = 2
        minimum_closed = int(os.getenv("STAGE3_MIN_CLOSED_TRADES", "30"))
        if total < minimum_closed:
            detail = f" Исключено неподтверждённых или синтетических записей: {len(rejected)}." if rejected else ""
            blockers.append(f"Недостаточно подтверждённых paper-сделок для testnet.{detail}")
        if net_profit <= 0 or profit_factor < float(os.getenv("STAGE3_MIN_PROFIT_FACTOR", "1.1")):
            blockers.append("Подтверждённая paper-стратегия ещё не показала положительное математическое ожидание.")
        if drawdown > float(os.getenv("STAGE3_MAX_DRAWDOWN_PERCENT", "10")):
            blockers.append("Просадка по подтверждённому paper-evidence превышает допустимый уровень.")
        if not blockers:
            eligible = 3

        if eligible >= 3:
            if testnet_orders < int(os.getenv("STAGE4_MIN_TESTNET_ORDERS", "50")):
                blockers.append("Недостаточно подтверждённых testnet-исполнений.")
            elif not os.getenv("LIVE_EXECUTION_APPROVED_AT", "").strip():
                blockers.append("Нет отдельного решения владельца на ограниченный live-этап.")
            else:
                eligible = 4

        if eligible >= 4:
            if live_orders < int(os.getenv("STAGE5_MIN_LIVE_TRADES", "100")):
                blockers.append("Недостаточно подтверждённой live-истории для масштабирования.")
            elif profit_factor < float(os.getenv("STAGE5_MIN_PROFIT_FACTOR", "1.25")):
                blockers.append("Profit factor ниже порога масштабирования.")
            elif drawdown > float(os.getenv("STAGE5_MAX_DRAWDOWN_PERCENT", "7")):
                blockers.append("Просадка слишком высока для увеличения капитала.")
            else:
                eligible = 5

        current = _stage_env("AUTONOMOUS_TRADING_STAGE", 2)
        cap = self._recommended_cap(eligible, profit_factor, drawdown)
        decision = "HOLD" if eligible <= current else "ELIGIBLE_FOR_REVIEW"
        return StageAssessment(current, eligible, decision, tuple(blockers), metrics, cap)

    @staticmethod
    def _recommended_cap(stage: int, profit_factor: float, drawdown: float) -> float:
        if stage <= 2:
            return 0.0
        if stage == 3:
            return 25.0
        if stage == 4:
            return 10.0
        cap = 10.0
        if profit_factor >= 1.5 and drawdown <= 4:
            cap = 25.0
        if profit_factor >= 2.0 and drawdown <= 3:
            cap = 50.0
        return cap

    def _load(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _evidence_equity_and_max_drawdown(initial: float, pnls: list[float]) -> tuple[float, float]:
    equity = initial
    peak = initial
    maximum_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            maximum_drawdown = max(maximum_drawdown, (peak - equity) / peak * 100)
    return equity, maximum_drawdown


def _positive_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def _finite_or_default(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _stage_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if 0 <= value <= 5 else default
