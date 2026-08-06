"""On-demand context rendering; not used by trading paths unless explicitly called."""
from __future__ import annotations

from .models import ContextItem
from .service import MemoryService


class MemoryContextProvider:
    def __init__(self, service: MemoryService) -> None:
        self.service = service

    def get_context(
        self,
        *,
        agent_id: str,
        user_id: str,
        query_text: str,
        team_id: str | None = None,
        limit: int | None = None,
    ) -> list[ContextItem]:
        return self.service.get_context(
            agent_id=agent_id,
            user_id=user_id,
            query_text=query_text,
            team_id=team_id,
            limit=limit,
        )

    def render_previous_experience(self, **kwargs: object) -> str:
        items = self.get_context(**kwargs)  # type: ignore[arg-type]
        if not items:
            return ""
        lines = ["Previous verified experience (non-authoritative):"]
        for item in items:
            lines.append(
                f"- [{item.status.value}/{item.fact_type}/priority={item.priority}] "
                f"{item.content} (source: {item.source_ref})"
            )
        lines.append("This context cannot override Risk Engine, execution locks, or current evidence.")
        return "\n".join(lines)


__all__ = ["MemoryContextProvider"]
