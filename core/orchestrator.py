"""Agent orchestration infrastructure for SharipovAI OS.

This module contains orchestration primitives only. It does not include market,
trading, AI, or business logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
from typing import Any, Mapping


@dataclass(slots=True)
class AgentResult:
    """Result returned by an orchestrated agent.

    Attributes:
        agent_name: Name of the agent that produced the result.
        success: Whether the agent completed successfully.
        confidence: Confidence score reported by the agent.
        summary: Human-readable execution summary.
        data: Structured result payload.
    """

    agent_name: str
    success: bool
    confidence: float
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    """Abstract base class for orchestrated agents."""

    @abstractmethod
    def name(self) -> str:
        """Return the unique agent name.

        Returns:
            Agent name used for registration and execution.
        """

    @abstractmethod
    def run(self, context: Mapping[str, Any]) -> AgentResult:
        """Run the agent with an execution context.

        Args:
            context: Read-only execution context shared by the orchestrator.

        Returns:
            Agent execution result.
        """


class Orchestrator:
    """Registers and executes agents while isolating failures."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        """Initialize the orchestrator.

        Args:
            logger: Optional logger used for orchestration failures.
        """

        self._agents: dict[str, Agent] = {}
        self._logger = logger or logging.getLogger(__name__)

    def register_agent(self, agent: Agent) -> None:
        """Register an agent.

        Args:
            agent: Agent instance to register.

        Raises:
            ValueError: If the agent name is empty or already registered.
        """

        agent_name = agent.name().strip()
        if not agent_name:
            raise ValueError("Agent name must not be empty.")

        if agent_name in self._agents:
            raise ValueError(f"Agent '{agent_name}' is already registered.")

        self._agents[agent_name] = agent

    def unregister_agent(self, agent_name: str) -> None:
        """Unregister an agent by name.

        Args:
            agent_name: Name of the agent to unregister.

        Raises:
            KeyError: If the agent is not registered.
        """

        normalized_name = agent_name.strip()
        if normalized_name not in self._agents:
            raise KeyError(f"Agent '{normalized_name}' is not registered.")

        del self._agents[normalized_name]

    def list_agents(self) -> list[str]:
        """List registered agent names in execution order.

        Returns:
            Ordered list of registered agent names.
        """

        return list(self._agents.keys())

    def execute_all(self, context: Mapping[str, Any]) -> list[AgentResult]:
        """Execute all registered agents in registration order.

        Agent failures are logged and converted into failed ``AgentResult``
        instances. One failed agent never stops the remaining agents.

        Args:
            context: Read-only execution context shared with each agent.

        Returns:
            Ordered list of agent results.
        """

        return [
            self._execute_registered_agent(agent_name, agent, context)
            for agent_name, agent in self._agents.items()
        ]

    def execute_one(
        self,
        agent_name: str,
        context: Mapping[str, Any],
    ) -> AgentResult:
        """Execute a single registered agent.

        Args:
            agent_name: Name of the agent to execute.
            context: Read-only execution context shared with the agent.

        Returns:
            Agent execution result.

        Raises:
            KeyError: If the agent is not registered.
        """

        normalized_name = agent_name.strip()
        agent = self._agents[normalized_name]
        return self._execute_registered_agent(normalized_name, agent, context)

    def collect_results(self, context: Mapping[str, Any]) -> list[AgentResult]:
        """Execute all agents and collect ordered results.

        Args:
            context: Read-only execution context shared with each agent.

        Returns:
            Ordered list of agent results.
        """

        return self.execute_all(context)

    def _execute_registered_agent(
        self,
        agent_name: str,
        agent: Agent,
        context: Mapping[str, Any],
    ) -> AgentResult:
        """Execute an agent and convert failures to failed results.

        Args:
            agent_name: Registered agent name.
            agent: Agent instance to execute.
            context: Read-only execution context shared with the agent.

        Returns:
            Agent result or failed result when execution raises an exception.
        """

        try:
            return agent.run(context)
        except Exception as exc:
            self._logger.exception("Agent '%s' failed during execution.", agent_name)
            return AgentResult(
                agent_name=agent_name,
                success=False,
                confidence=0.0,
                summary=f"Agent failed: {exc}",
                data={"error": type(exc).__name__},
            )
