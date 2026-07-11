from exchange_connector.bybit_order_state_store import BybitOrderStateStore


def test_default_state_paths_are_environment_specific(monkeypatch):
    monkeypatch.delenv("BYBIT_ORDER_STATE_FILE", raising=False)
    testnet = BybitOrderStateStore(environment="sandbox")
    mainnet = BybitOrderStateStore(environment="live")
    assert str(testnet.path).endswith("bybit_order_state_testnet.json")
    assert str(mainnet.path).endswith("bybit_order_state_mainnet.json")
    assert testnet.path != mainnet.path
