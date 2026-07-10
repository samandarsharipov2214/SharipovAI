from architecture_registry import architecture_audit, capability_registry, owner_for


def test_registry_contains_existing_core_learning_bots() -> None:
    audit = architecture_audit()
    assert audit["learning_registry_missing"] == []
    assert audit["core_component_count"] == 11


def test_registry_reuses_existing_specialized_news_network() -> None:
    registry = capability_registry()
    ids = {item.component_id for item in registry}
    assert {"economy_ai", "finance_ai", "crypto_ai", "security_ai"} <= ids
    assert owner_for("crypto_news") == ["crypto_ai"]


def test_four_priorities_are_represented() -> None:
    priorities = architecture_audit()["priorities"]
    assert priorities[1]
    assert priorities[2]
    assert priorities[3]
    assert priorities[4]


def test_no_harmful_capability_duplication() -> None:
    assert architecture_audit()["harmful_duplicates"] == []
