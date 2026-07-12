"""Controls progression from paper to testnet, limited live, and scaling."""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from storage import ProjectDatabase, VersionConflict, list_json_items

from .evidence_integrity import eligible_closed_trades
from .execution_journal import ExecutionJournal
from .trade_identity import scope_for_path


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
    """Evaluate canonical evidence before allowing a higher execution stage.

    ProjectDatabase and its immutable paper-trade history are the source of truth.
    A legacy JSON state may be migrated once, but it is never preferred over the
    database. Any database/history ambiguity keeps the system at the paper stage.
    """

    def __init__(
        self,
        state_file: str | None = None,
        journal: ExecutionJournal | None = None,
        database: ProjectDatabase | None = None,
    ) -> None:
        self.state_file = Path(
            state_file or os.getenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json")
        )
        self.scope = scope_for_path(self.state_file)
        self.state_namespace = "autonomous_paper_state"
        self.trade_namespace = f"paper_trades:{self.scope}"
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.journal = journal or ExecutionJournal(database=self.database)
        self._state_database_backed = False
        self._state_error = ""

    def assess(self) -> StageAssessment:
        blockers: list[str] = []
        state = self._load()
        if self._state_error:
            blockers.append(self._state_error)

        raw_trades = self._canonical_trade_history(state, blockers)
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

        try:
            execution = self.journal.summary()
            testnet_orders = int(execution["verified_testnet_orders"])
            live_orders = int(execution["verified_live_orders"])
        except Exception:
            testnet_orders = 0
            live_orders = 0
            blockers.append("Канонический execution journal недоступен; повышение этапа заблокировано.")

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
            "paper_state_database_backed": 1.0 if self._state_database_backed else 0.0,
            "immutable_trade_history_count": float(len(raw_trades)),
        }

        eligible = 2
        minimum_closed = _positive_int_env("STAGE3_MIN_CLOSED_TRADES", 30)
        if total < minimum_closed:
            detail = (
                f" Исключено неподтверждённых или синтетических записей: {len(rejected)}."
                if rejected
                else ""
            )
            blockers.append(f"Недостаточно подтверждённых paper-сделок для testnet.{detail}")
        if net_profit <= 0 or profit_factor < _positive_env("STAGE3_MIN_PROFIT_FACTOR", 1.1):
            blockers.append("Подтверждённая paper-стратегия ещё не показала положительное математическое ожидание.")
        if drawdown > _nonnegative_env("STAGE3_MAX_DRAWDOWN_PERCENT", 10.0):
            blockers.append("Просадка по подтверждённому paper-evidence превышает допустимый уровень.")
        if not blockers:
            eligible = 3

        if eligible >= 3:
            if testnet_orders < _positive_int_env("STAGE4_MIN_TESTNET_ORDERS", 50):
                blockers.append("Недостаточно подтверждённых testnet-исполнений.")
            elif not os.getenv("LIVE_EXECUTION_APPROVED_AT", "").strip():
                blockers.append("Нет отдельного решения владельца на ограниченный live-этап.")
            else:
                eligible = 4

        if eligible >= 4:
            if live_orders < _positive_int_env("STAGE5_MIN_LIVE_TRADES", 100):
                blockers.append("Недостаточно подтверждённой live-истории для масштабирования.")
            elif profit_factor < _positive_env("STAGE5_MIN_PROFIT_FACTOR", 1.25):
                blockers.append("Profit factor ниже порога масштабирования.")
            elif drawdown > _nonnegative_env("STAGE5_MAX_DRAWDOWN_PERCENT", 7.0):
                blockers.append("Просадка слишком высока для увеличения капитала.")
            else:
                eligible = 5

        current = _stage_env("AUTONOMOUS_TRADING_STAGE", 2)
        cap = self._recommended_cap(eligible, profit_factor, drawdown)
        decision = "HOLD" if eligible <= current else "ELIGIBLE_FOR_REVIEW"
        return StageAssessment(current, eligible, decision, tuple(dict.fromkeys(blockers)), metrics, cap)

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

    def _canonical_trade_history(self, state: dict[str, Any], blockers: list[str]) -> list[dict[str, Any]]:
        try:
            records = list_json_items(self.database, self.trade_namespace)
        except Exception:
            blockers.append("Immutable paper trade history недоступна; повышение этапа заблокировано.")
            return []

        history: list[dict[str, Any]] = []
        for record in records:
            value = record.get("value") if isinstance(record, dict) else None
            if not isinstance(value, dict):
                blockers.append("Immutable paper trade history повреждена; повышение этапа заблокировано.")
                return []
            history.append(value)

        state_trades = state.get("trades", [])
        if not isinstance(state_trades, list):
            blockers.append("Каноническое paper-state содержит некорректную историю сделок.")
            return []
        if self._state_database_backed and state_trades and not history:
            blockers.append("Paper-state и immutable trade history не согласованы; повышение этапа заблокировано.")
            return []
        return history if self._state_database_backed else [item for item in state_trades if isinstance(item, dict)]

    def _load(self) -> dict[str, Any]:
        self._state_error = ""
        self._state_database_backed = False
        try:
            current = self.database.get_json(self.state_namespace, self.scope)
        except Exception:
            self._state_error = "Каноническая ProjectDatabase недоступна; повышение этапа заблокировано."
            return {}

        if current is not None:
            value = current.get("value")
            if not isinstance(value, dict):
                self._state_error = "Каноническое paper-state повреждено; повышение этапа заблокировано."
                return {}
            self._state_database_backed = True
            return dict(value)

        if not self.state_file.exists():
            self._state_error = "Каноническое paper-state ещё не создано; повышение этапа заблокировано."
            return {}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            self._state_error = "Legacy paper backup повреждён; повышение этапа заблокировано."
            return {}
        if not isinstance(data, dict):
            self._state_error = "Legacy paper backup имеет неверный формат; повышение этапа заблокировано."
            return {}

        try:
            self.database.put_json(self.state_namespace, self.scope, data, expected_version=0)
            for trade in data.get("trades", []):
                if not isinstance(trade, dict):
                    continue
                trade_id = str(trade.get("trade_id") or trade.get("id") or "").strip()
                if not trade_id:
                    continue
                try:
                    self.database.put_json(self.trade_namespace, trade_id, trade, expected_version=0)
                except VersionConflict:
                    existing = self.database.get_json(self.trade_namespace, trade_id)
                    if existing is None or existing.get("value") != trade:
                        raise RuntimeError("legacy paper trade conflicts with immutable history")
        except Exception:
            self._state_error = "Legacy paper backup не удалось мигрировать в ProjectDatabase; повышение этапа заблокировано."
            return {}

        self._state_database_backed = True
        return data


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


def _nonnegative_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value >= 0 else default


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


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
