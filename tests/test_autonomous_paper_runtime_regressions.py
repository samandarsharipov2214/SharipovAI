import time
import unittest
from types import SimpleNamespace

from autonomous_trading.status_snapshot import nonblocking_loop_snapshot
from autonomous_trading.traced_council_provider import AutonomousCouncilProposalProvider


class _FakeDatabase:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    def get_json(self, namespace, key):
        return self.rows.get((namespace, key))

    def put_json(self, namespace, key, value, **_kwargs):
        current = self.rows.get((namespace, key))
        version = int(current.get("version", 0)) + 1 if isinstance(current, dict) else 1
        self.rows[(namespace, key)] = {"value": dict(value), "version": version}
        return self.rows[(namespace, key)]


class _SingleEvidenceStream:
    def __init__(self):
        self.calls = 0

    def evidence(self, _symbol):
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("market evidence was fetched more than once for one provider decision")
        return {
            "verified": False,
            "synthetic_fallback_used": False,
            "consensus_sources": ("bybit", "binance", "okx"),
        }


class _BusyLock:
    def acquire(self, *, blocking=True):
        if blocking:
            raise AssertionError("status snapshot must not perform a blocking PAPER lock acquire")
        return False

    def release(self):
        raise AssertionError("busy lock was never acquired")


class _StatusStream:
    def snapshot(self):
        return {
            "status": "online",
            "connected": True,
            "verified": True,
            "age_seconds": 0.1,
            "last_error": "",
            "quotes": {},
        }


class _BusyLoop:
    def __init__(self):
        self._lock = _BusyLock()
        self.state_namespace = "autonomous_paper_state"
        self.scope = "paper-test"
        self.database = _FakeDatabase(
            {
                (self.state_namespace, self.scope): {
                    "version": 7,
                    "value": {
                        "mode": "autonomous_paper",
                        "cash": 4321.0,
                        "equity": 4321.0,
                        "positions": {},
                        "trades": [],
                        "events": [],
                    },
                }
            }
        )
        self.stream = _StatusStream()
        self._last_backup_error = ""
        self._thread = SimpleNamespace(is_alive=lambda: True)
        self.wait_event_min_interval_seconds = 300.0

    def snapshot(self):
        raise AssertionError("busy status path must use committed database state")

    def _mark_state_to_market(self, state, _market, *, update_timestamp):
        self.assert_no_update_timestamp = update_timestamp
        state["marked_from_fallback"] = True

    def trade_history(self):
        return [1, 2]

    def event_history(self):
        return [1]


class AutonomousPaperRuntimeRegressionTests(unittest.TestCase):
    def test_wait_trace_reuses_exact_canonical_market_evidence(self):
        provider = AutonomousCouncilProposalProvider.__new__(AutonomousCouncilProposalProvider)
        provider.database = _FakeDatabase()
        provider.stream = _SingleEvidenceStream()
        provider.proposal_interval_ms = 60_000
        provider.entry_change_percent = 0.8
        provider.min_turnover_usdt = 5_000_000.0
        provider._last_market_evidence = {}

        quote = SimpleNamespace(
            price=100.0,
            change_24h_percent=1.0,
            volume_24h=10_000_000.0,
            received_at_unix_ms=int(time.time() * 1000),
        )
        result = provider(
            "ETHUSDT",
            quote,
            {"cash": 10_000.0, "equity": 10_000.0, "open_symbols": ()},
        )

        self.assertIsNone(result)
        self.assertEqual(provider.stream.calls, 1)
        trace = provider.database.get_json("council_decision_trace", "ETHUSDT")["value"]
        self.assertEqual(trace["phase"], "market_verification")
        self.assertFalse(trace["market_verified"])

    def test_status_uses_database_fallback_when_paper_lock_is_busy(self):
        loop = _BusyLoop()

        snapshot = nonblocking_loop_snapshot(loop)

        self.assertEqual(snapshot["cash"], 4321.0)
        self.assertEqual(snapshot["snapshot_state_source"], "project_database_fallback")
        self.assertTrue(snapshot["worker_running"])
        self.assertEqual(snapshot["trade_history_count"], 2)
        self.assertEqual(snapshot["event_history_count"], 1)
        self.assertTrue(snapshot["marked_from_fallback"])
        self.assertFalse(loop.assert_no_update_timestamp)


if __name__ == "__main__":
    unittest.main()