"""SharipovAI OS analytical pipeline coordinator.

The AI Core coordinates deterministic analytical engines and registered agents.
It does not call AI models, execute exchange operations, manage API keys, or
perform trading execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from analysis import FactorScore
from confidence import ConfidenceEngine, ConfidenceInput
from consensus import ConsensusEngine, ConsensusInput
from core.orchestrator import AgentResult, Orchestrator
from decision import DecisionEngine, DecisionInput
from memory import DecisionRecord, MemoryEngine
from portfolio_engine import PortfolioEngine
from risk_engine import RiskEngine

from .exceptions import AICoreError
from .models import AICoreInput, AICoreOutput


class AICore:
    """Coordinates the complete SharipovAI analytical pipeline."""

    DEFAULT_DATA_QUALITY: float = 100.0

    def __init__(
        self,
        orchestrator: Orchestrator | None = None,
        consensus_engine: ConsensusEngine | None = None,
        confidence_engine: ConfidenceEngine | None = None,
        portfolio_engine: PortfolioEngine | None = None,
        risk_engine: RiskEngine | None = None,
        decision_engine: DecisionEngine | None = None,
        memory_engine: MemoryEngine | None = None,
    ) -> None:
        """Initialize the AI Core with optional dependencies.

        Args:
            orchestrator: Optional orchestrator for agent execution.
            consensus_engine: Optional consensus engine.
            confidence_engine: Optional confidence engine.
            portfolio_engine: Optional portfolio engine.
            risk_engine: Optional risk engine.
            decision_engine: Optional decision engine.
            memory_engine: Optional memory engine.
        """

        self._orchestrator = orchestrator or Orchestrator()
        self._consensus_engine = consensus_engine or ConsensusEngine()
        self._confidence_engine = confidence_engine or ConfidenceEngine()
        self._portfolio_engine = portfolio_engine or PortfolioEngine()
        self._risk_engine = risk_engine or RiskEngine()
        self._decision_engine = decision_engine or DecisionEngine()
        self._memory_engine = memory_engine or MemoryEngine()

    @property
    def orchestrator(self) -> Orchestrator:
        """Return the configured orchestrator."""

        return self._orchestrator

    def run(self, input: AICoreInput) -> AICoreOutput:
        """Execute the complete analytical pipeline.

        Args:
            input: Typed AI Core input.

        Returns:
            Complete AI Core output.

        Raises:
            AICoreError: If infrastructure input is invalid.
        """

        self._validate_input(input)

        agent_results = self._orchestrator.execute_all(input.context)
        consensus = self._consensus_engine.evaluate(
            ConsensusInput(agent_results=agent_results)
        )
        factor_scores = self._extract_factor_scores(agent_results)
        confidence = self._confidence_engine.calculate(
            ConfidenceInput(
                consensus_agreement=consensus.agreement,
                factor_scores=factor_scores,
                failed_agents=consensus.failed_agents,
                total_agents=len(agent_results),
                data_quality=self._data_quality(input.context),
            )
        )
        portfolio = self._portfolio_engine.evaluate(input.portfolio)
        risk = self._risk_engine.evaluate(input.risk)
        decision = self._decision_engine.make_decision(
            DecisionInput(
                agent_results=agent_results,
                factor_scores=factor_scores,
                portfolio_risk=risk.risk_score,
                confidence=confidence.confidence,
            )
        )

        self._memory_engine.save(
            self._build_decision_record(
                agent_results=agent_results,
                factor_scores=factor_scores,
                decision=decision,
                symbol=self._symbol(input.context, agent_results),
            )
        )

        return AICoreOutput(
            agent_results=agent_results,
            consensus=consensus,
            confidence=confidence,
            portfolio=portfolio,
            risk=risk,
            decision=decision,
        )

    def _validate_input(self, input: AICoreInput) -> None:
        """Validate AI Core input.

        Args:
            input: Candidate AI Core input.

        Raises:
            AICoreError: If input is invalid.
        """

        if not isinstance(input, AICoreInput):
            raise AICoreError("AICore requires an AICoreInput instance.")

    def _extract_factor_scores(
        self,
        agent_results: list[AgentResult],
    ) -> list[FactorScore]:
        """Extract factor scores from agent result data.

        Args:
            agent_results: Agent results returned by the orchestrator.

        Returns:
            Parsed factor scores.
        """

        factor_scores: list[FactorScore] = []
        for result in agent_results:
            raw_scores = result.data.get("factor_scores")
            if not isinstance(raw_scores, list):
                continue

            for raw_score in raw_scores:
                if isinstance(raw_score, FactorScore):
                    factor_scores.append(raw_score)
                elif isinstance(raw_score, dict):
                    factor_scores.append(
                        FactorScore(
                            name=str(raw_score.get("name", "")),
                            score=float(raw_score.get("score", 0.0)),
                            weight=float(raw_score.get("weight", 0.0)),
                            reason=str(raw_score.get("reason", "")),
                        )
                    )

        return factor_scores

    def _data_quality(self, context: Any) -> float:
        """Read data quality from context.

        Args:
            context: Shared execution context.

        Returns:
            Data quality score from 0 to 100.
        """

        if not isinstance(context, dict):
            return self.DEFAULT_DATA_QUALITY

        value = context.get("data_quality", self.DEFAULT_DATA_QUALITY)
        return max(0.0, min(float(value), 100.0))

    def _symbol(
        self,
        context: Any,
        agent_results: list[AgentResult],
    ) -> str:
        """Resolve the symbol used for memory storage.

        Args:
            context: Shared execution context.
            agent_results: Agent results returned by the orchestrator.

        Returns:
            Resolved symbol or ``UNKNOWN``.
        """

        if isinstance(context, dict) and context.get("symbol"):
            return str(context["symbol"])

        for result in agent_results:
            top_symbol = result.data.get("top_symbol")
            if top_symbol:
                return str(top_symbol)

        return "UNKNOWN"

    def _build_decision_record(
        self,
        *,
        agent_results: list[AgentResult],
        factor_scores: list[FactorScore],
        decision: Any,
        symbol: str,
    ) -> DecisionRecord:
        """Build a memory record for the final decision.

        Args:
            agent_results: Agent results returned by the orchestrator.
            factor_scores: Factor scores used by the decision engine.
            decision: Final decision output.
            symbol: Symbol associated with the decision.

        Returns:
            Decision record ready for storage.
        """

        return DecisionRecord(
            id=str(uuid4()),
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            decision=decision.decision.value,
            confidence=decision.confidence,
            agents=[result.agent_name for result in agent_results],
            factor_scores=[
                {
                    "name": factor.name,
                    "score": factor.score,
                    "weight": factor.weight,
                    "reason": factor.reason,
                }
                for factor in factor_scores
            ],
            reason=decision.reason,
            result=None,
            profit_loss=None,
            notes="Stored by AICore analytical pipeline.",
        )
