from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase8_policy_preserves_mainnet_and_manual_decision_locks() -> None:
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "MAINNET_EXECUTION_COMPILED=False" in constitution
    assert "manual decision" in constitution.lower()
    assert "10–25 USDT" in constitution
    assert "Mainnet remains unavailable" in readme
    assert "authenticated private Testnet fills" in readme
