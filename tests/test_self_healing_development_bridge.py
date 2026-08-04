from __future__ import annotations

from types import SimpleNamespace

from development_control.general_controller import DevelopmentDecision
from development_control.self_healing_bridge import route_successful_ai_fix

BASE_SHA = "a" * 40


class Fixer:
    def attempt(self, **kwargs):
        assert kwargs["head"] == BASE_SHA
        return {
            "success": True,
            "patch": (
                "diff --git a/app/service.py b/app/service.py\n"
                "index 1111111..2222222 100644\n"
                "--- a/app/service.py\n"
                "+++ b/app/service.py\n"
                "@@ -1 +1 @@\n"
                "-VALUE = 1\n"
                "+VALUE = 2\n"
            ),
            "changed_files": ["app/service.py"],
            "test_results": "focused tests passed",
        }


class Controller:
    def __init__(self):
        self.calls = []
        self.decision = DevelopmentDecision(
            decision_id="a" * 64,
            short_id="a" * 12,
            fix_id="fix_" + "a" * 64,
            status="submitted",
            proposal={},
        )

    def submit_proposal(self, proposal):
        self.calls.append(("submit", proposal))
        self.decision.proposal = proposal
        return self.decision

    def security_review(self, decision_id):
        self.calls.append(("security", decision_id))
        self.decision.status = "security_approved"
        self.decision.security_verdict = {"allowed": True, "reasons": []}
        return self.decision

    def request_owner_approval(self, decision_id):
        self.calls.append(("owner", decision_id))
        self.decision.status = "awaiting_owner"
        return self.decision


def test_successful_fixer_result_is_routed_without_host_application() -> None:
    controller = Controller()
    agent = SimpleNamespace(ai_fixer=Fixer(), development_controller=controller)

    decision = route_successful_ai_fix(
        agent,
        head=BASE_SHA,
        output="pytest failed",
        command=["pytest", "-q"],
    )

    assert decision is not None
    assert decision.status == "awaiting_owner"
    assert [call[0] for call in controller.calls] == ["submit", "security", "owner"]
    assert all(call[0] != "queue" for call in controller.calls)
    assert decision.proposal["base_sha"] == BASE_SHA


def test_missing_or_failed_fixer_returns_none() -> None:
    assert route_successful_ai_fix(SimpleNamespace(), head=BASE_SHA, output="failed", command=[]) is None

    class FailedFixer:
        def attempt(self, **kwargs):
            return {"success": False, "patch": "diff --git a/a b/a"}

    assert (
        route_successful_ai_fix(
            SimpleNamespace(ai_fixer=FailedFixer()),
            head=BASE_SHA,
            output="failed",
            command=[],
        )
        is None
    )
