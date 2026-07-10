"""Controls progression from paper to testnet, limited live, and scaling."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


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
    """Evaluate evidence before allowing a higher execution stage."""

    def __init__(self, state_file: str | None = None) -> None:
        self.state_file = Path(state_file or os.getenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json"))

    def assess(self) -> StageAssessment:
        state = self._load()
        trades = [x for x in state.get("trades", []) if x.get("side") == "SELL" and x.get("net_pnl") is not None]
        pnls = [float(x["net_pnl"]) for x in trades]
        wins = sum(1 for x in pnls if x > 0)
        total = len(pnls)
        win_rate = wins / total * 100 if total else 0.0
        net_profit = sum(pnls)
        gross_loss = abs(sum(x for x in pnls if x < 0))
        gross_profit = sum(x for x in pnls if x > 0)
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)
        initial = float(os.getenv("AUTONOMOUS_PAPER_INITIAL_CASH", "10000"))
        drawdown = max(0.0, (initial - float(state.get("equity", initial))) / initial * 100)
        metrics = {
            "closed_trades": float(total),
            "win_rate_percent": round(win_rate, 3),
            "net_profit": round(net_profit, 8),
            "profit_factor": round(profit_factor, 3),
            "drawdown_percent": round(drawdown, 3),
        }
        blockers: list[str] = []
        eligible = 2
        if total < int(os.getenv("STAGE3_MIN_CLOSED_TRADES", "30")):
            blockers.append("Недостаточно закрытых paper-сделок для testnet.")
        if net_profit <= 0 or profit_factor < float(os.getenv("STAGE3_MIN_PROFIT_FACTOR", "1.1")):
            blockers.append("Paper-стратегия ещё не показала положительное математическое ожидание.")
        if drawdown > float(os.getenv("STAGE3_MAX_DRAWDOWN_PERCENT", "10")):
            blockers.append("Просадка paper-счёта превышает допустимый уровень.")
        if not blockers:
            eligible = 3

        testnet_orders = int(os.getenv("VERIFIED_TESTNET_ORDERS", "0"))
        if eligible >= 3:
            if testnet_orders < int(os.getenv("STAGE4_MIN_TESTNET_ORDERS", "50")):
                blockers.append("Недостаточно подтверждённых testnet-исполнений.")
            elif not os.getenv("LIVE_EXECUTION_APPROVED_AT", "").strip():
                blockers.append("Нет отдельного решения владельца на ограниченный live-этап.")
            else:
                eligible = 4

        live_trades = int(os.getenv("VERIFIED_LIVE_CLOSED_TRADES", "0"))
        if eligible >= 4:
            if live_trades < int(os.getenv("STAGE5_MIN_LIVE_TRADES", "100")):
                blockers.append("Недостаточно live-истории для масштабирования.")
            elif profit_factor < float(os.getenv("STAGE5_MIN_PROFIT_FACTOR", "1.25")):
                blockers.append("Profit factor ниже порога масштабирования.")
            elif drawdown > float(os.getenv("STAGE5_MAX_DRAWDOWN_PERCENT", "7")):
                blockers.append("Просадка слишком высока для увеличения капитала.")
            else:
                eligible = 5

        current = int(os.getenv("AUTONOMOUS_TRADING_STAGE", "2"))
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
        base = 10.0
        if profit_factor >= 1.5 and drawdown <= 4:
            base = 25.0
        if profit_factor >= 2.0 and drawdown <= 3:
            base = 50.0
        return base

    def _load(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
