"""Minimal passive Memory Layer example; no extraction or context injection."""
from memory_engine import MemoryService, MemorySettings
from storage import ProjectDatabase

settings = MemorySettings(enabled=True, extraction_enabled=False, context_injection_enabled=False)
database = ProjectDatabase()
service = MemoryService(database, settings=settings)
service.initialize()
service.record_dialog(
    team_id="sharipovai",
    user_id="owner",
    agent_id="learning_engine",
    session_id="example",
    message="A verified regression was fixed and all tests passed.",
    source_ref="example:manual",
)
print(service.health())
