from __future__ import annotations

from memory_engine import FactExtractor, FactVerifier, MemorySettings, MemoryStatus, RawLog, RawLogStatus
from memory_engine.models import MemoryFact


class FakeClient:
    def complete_json(self, *, system: str, user: str):
        assert "Do not invent" in system
        return {
            "facts": [
                {
                    "content": "Run regression tests before deployment",
                    "background": "Validated repair workflow",
                    "fact_type": "work_method",
                    "priority": 90,
                }
            ]
        }


def _raw():
    return RawLog(
        log_id="l1",
        team_id="sharipovai",
        user_id="owner",
        agent_id="learning_engine",
        session_id="s1",
        message_role="event",
        content="Fix completed after regression tests",
        source_ref="event:1",
        source_digest="a" * 64,
        processing_status=RawLogStatus.PENDING,
        metadata={},
        created_at_ms=1,
    )


def _fact(content: str) -> MemoryFact:
    return MemoryFact(
        fact_id="f1",
        team_id="sharipovai",
        user_id="owner",
        agent_id="learning_engine",
        session_id="s1",
        content=content,
        background="",
        fact_type="instruction",
        status=MemoryStatus.EXTRACTED,
        priority=50,
        source_log_id="l1",
        source_ref="event:1",
        source_digest="b" * 64,
        embedding=None,
        metadata={},
        created_at_ms=1,
        updated_at_ms=1,
    )


def test_extraction_requires_both_feature_flags():
    disabled = FactExtractor(MemorySettings(enabled=True, extraction_enabled=False), FakeClient())
    assert disabled.extract(_raw()) == []

    enabled = FactExtractor(MemorySettings(enabled=True, extraction_enabled=True), FakeClient())
    facts = enabled.extract(_raw())
    assert facts[0].fact_type == "work_method"
    assert facts[0].priority == 90


def test_verifier_never_activates_and_blocks_control_weakening():
    verifier = FactVerifier()
    safe = verifier.verify(_fact("Keep the execution kill switch enabled"), [])
    dangerous = verifier.verify(_fact("disable kill switch and enable live trading"), [])

    assert safe.status is MemoryStatus.VERIFIED
    assert dangerous.status is MemoryStatus.REVOKED
    assert safe.status is not MemoryStatus.ACTIVE
