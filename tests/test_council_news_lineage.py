from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import datetime

import pytest

from autonomous_trading.canonical_runtime import CanonicalPaperDecisionRuntime
from autonomous_trading.council_provider import AutonomousCouncilProposalProvider
from dashboard.autonomous_trading_api import _database_news_reader
from news_intelligence.council_lineage import news_memory_lineage, opinion_news_lineage
from storage import ProjectDatabase
from test_canonical_autonomous_runtime_v2 import FakeWorker, FakeMarketData, FakeConsensus, _state
from autonomous_trading import SharedVerifiedMarketStream


NOW = 1_800_000_000_000


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(NOW / 1000, tz=tz)


def row(key="memory-1", *, source="publisher-a", link="https://example.org/story"):
    return {
        "key": key, "updated_at_ms": NOW - 1000,
        "value": {
            "agent_id": source, "category": "finance macro crypto world security",
            "impact": "positive", "score": 30.0, "reliability": 0.92,
            "article": {"article_id": key + "-article", "title": "Shared market news",
                        "link": link, "published_at": "2027-01-15T07:59:00Z"},
            "fetched": {"source_id": source, "received_at_ms": NOW - 2000, "verified": True},
        },
    }


def reader_for(monkeypatch, db, rows):
    monkeypatch.setattr("dashboard.autonomous_trading_api.list_json_items", lambda *a, **k: rows)
    return _database_news_reader(db)


def test_shared_article_and_publisher_are_visible_without_copying_content():
    a = row("one")
    b = row("two", source="publisher-b")
    a["value"]["article"]["summary"] = "unneeded raw content"
    a["value"]["fetched"]["error"] = "unneeded upstream error"
    before = copy.deepcopy(a)
    first, second = news_memory_lineage(a), news_memory_lineage(b)
    assert first["source_id"] != second["source_id"]
    assert first["article_id"] != second["article_id"]
    assert first["exact_link_sha256"] == second["exact_link_sha256"] == hashlib.sha256(
        b"https://example.org/story").hexdigest()
    assert news_memory_lineage(row("three"))["source_id"] == first["source_id"]
    assert a == before
    encoded = json.dumps(first)
    assert "https://" not in encoded and "unneeded" not in encoded and "Shared market" not in encoded


def test_lineage_uses_exact_selected_rows_and_keeps_duplicates(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'news.db'}")
    rows = [row(str(i)) for i in range(55)]
    rows[-1] = copy.deepcopy(rows[-2])  # Duplicate contribution must remain observable.
    reader = reader_for(monkeypatch, db, rows)
    provider = AutonomousCouncilProposalProvider(db, object(), news_reader=reader)
    lineage = {}
    opinion, ids = provider._news_opinion("finance_ai", now_ms=NOW, lineage=lineage)
    result = lineage["finance_ai"]
    assert ids == [r["key"] for r in rows[-50:]]
    assert [r["memory_id"] for r in result["items"]] == ids
    assert result["eligible_memory_count"] == 55
    assert result["consumed_memory_count"] == result["complete_lineage_count"] == 50
    assert result["confirmation_denominator_count"] == 55
    assert result["denominator_only_items"] == [
        {"memory_id": r["key"], "created_at_seconds": (NOW - 1000) // 1000,
         "memory_updated_at_ms": NOW - 1000}
        for r in rows[:5]
    ]
    assert result["schema_version"] == 2
    assert result["status"] == "COMPLETE"
    assert result["symbol_relevance"] == "NOT_EVALUATED"
    assert result["policy_influence"] == "NONE"
    assert opinion["confidence"] == 73.0 and opinion["action"] == "BUY"
    assert "source_lineage" not in opinion and "evidence_ids" not in opinion
    assert provider._news_opinion("finance_ai", now_ms=NOW) == (opinion, ids)


@pytest.mark.parametrize("missing", ["fetch_received_at_ms", "published_at", "producer_id", "memory_namespace"])
def test_missing_origin_or_freshness_fields_mean_partial_lineage(missing):
    descriptor = news_memory_lineage(row())
    descriptor.pop(missing)
    result = opinion_news_lineage([{"key": "memory-1", "source_lineage": descriptor}], now_ms=NOW)
    assert result["status"] == "PARTIAL"
    assert result["complete_lineage_count"] == 0


def test_denominator_only_rows_reproduce_confirmation_scores(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'denominator.db'}")
    rows = [row(str(i)) for i in range(55)]
    for item in rows:
        item["value"]["fetched"]["verified"] = False
    provider = AutonomousCouncilProposalProvider(db, object(), news_reader=reader_for(monkeypatch, db, rows))
    lineage = {}
    opinion, _ = provider._news_opinion("finance_ai", now_ms=NOW, lineage=lineage)
    detail = lineage["finance_ai"]
    numerator = sum(item["needs_confirmation"] for item in detail["items"])
    denominator = len(detail["items"]) + len(detail["denominator_only_items"])
    assert numerator == 50 and denominator == 55
    assert opinion["evidence_score"] == round(92.0 * (1 - numerator / denominator * 0.5), 6)
    assert opinion["risk_score"] == round(20.0 + numerator / denominator * 60.0, 6)


@pytest.mark.parametrize("missing", ["key", "created_at", "source_lineage"])
def test_missing_denominator_only_identity_is_partial(missing):
    memory = {"key": "memory-1", "created_at": NOW // 1000,
              "source_lineage": news_memory_lineage(row())}
    denominator_row = copy.deepcopy(memory)
    denominator_row.pop(missing)
    result = opinion_news_lineage([denominator_row] + [memory] * 50, now_ms=NOW)
    assert result["status"] == "PARTIAL"
    assert result["complete_lineage_count"] == 50
    assert result["confirmation_denominator_count"] == 51


@pytest.mark.parametrize("timestamp", [None, 0, -1, True, "1800000000000"])
def test_invalid_fetch_timestamp_is_partial(timestamp):
    descriptor = news_memory_lineage(row())
    descriptor["fetch_received_at_ms"] = timestamp
    result = opinion_news_lineage([{"key": "memory-1", "source_lineage": descriptor}], now_ms=NOW)
    assert result["status"] == "PARTIAL"
    assert result["items"][0]["fetch_received_at_ms"] is None


def test_missing_lineage_never_implies_independent_or_verified_sources():
    memory = {"key": "legacy", "created_at": NOW // 1000}
    result = opinion_news_lineage([memory], now_ms=NOW)
    assert result["status"] == "UNAVAILABLE"
    assert result["items"][0]["exact_link_sha256"] is None
    assert result["items"][0]["memory_updated_at_ms"] is None
    partial = copy.deepcopy(memory)
    partial["source_lineage"] = {"source_id": "known-publisher"}
    assert opinion_news_lineage([partial], now_ms=NOW)["status"] == "PARTIAL"
    assert opinion_news_lineage([], now_ms=NOW)["status"] == "UNAVAILABLE"


def test_persisted_time_and_publication_are_distinct_and_future_rows_explicit():
    value = row()
    value["updated_at_ms"] = NOW + 1
    descriptor = news_memory_lineage(value)
    result = opinion_news_lineage([{"key": value["key"], "source_lineage": descriptor}], now_ms=NOW)
    assert result["rows_available_after_capture"] == 1
    assert result["items"][0]["memory_updated_at_ms"] == NOW + 1
    assert result["items"][0]["fetch_received_at_ms"] == NOW - 2000
    assert result["items"][0]["published_at"] == value["value"]["article"]["published_at"]


@pytest.mark.parametrize("change", [2.4, -2.4, 0.1, 8.1])
@pytest.mark.parametrize("news_age_seconds", [1, 21601])
def test_metadata_preserves_full_proposals_and_authorizations(tmp_path, monkeypatch, change, news_age_seconds):
    monkeypatch.setattr("time.time", lambda: NOW / 1000)
    monkeypatch.setattr("decision_quality.service.datetime", FrozenDateTime)
    source = row()
    source["updated_at_ms"] = NOW - news_age_seconds * 1000
    outputs = []
    for with_metadata in (False, True):
        db = ProjectDatabase(f"sqlite:///{tmp_path / str(with_metadata)}.db")
        reader = reader_for(monkeypatch, db, [source])
        def read(agent_id, **kwargs):
            detail = reader(agent_id, **kwargs)
            if not with_metadata:
                for memory in detail["memory"]:
                    memory.pop("source_lineage")
            return detail
        worker = FakeWorker()
        worker.database = db
        stream = SharedVerifiedMarketStream(worker, FakeMarketData(), FakeConsensus(), database=db)
        quote = replace(stream.quote("BTCUSDT"), change_24h_percent=change)
        proposal = AutonomousCouncilProposalProvider(db, stream, news_reader=read)("BTCUSDT", quote, _state())
        if proposal is None:
            outputs.append((None, None))
            continue
        auth = CanonicalPaperDecisionRuntime(db).assess_entry(
            proposal.decision_id, proposal.agent_payloads, proposal.evidence_packet,
            general_controller_decision=proposal.general_controller_decision,
            now_ms=NOW, regime=proposal.regime,
        )
        outputs.append((proposal, auth.to_dict()))
        assessment = db.get_json("council_news_assessments", proposal.evidence_packet.news_assessment_id)["value"]
        assert set(assessment["opinion_lineage"]) == set(assessment["agents"])
        for detail in assessment["opinion_lineage"].values():
            assert detail["status"] == ("COMPLETE" if with_metadata else "UNAVAILABLE")
    assert outputs[0] == outputs[1]


def test_lineage_is_attached_to_existing_bounded_snapshot(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'cache.db'}")
    calls = []
    source = row()
    def read_rows(*args, **kwargs):
        calls.append(kwargs)
        return [copy.deepcopy(source)]
    monkeypatch.setattr("dashboard.autonomous_trading_api.list_json_items", read_rows)
    reader = _database_news_reader(db)
    first = reader("crypto_ai")["memory"]
    source["value"]["fetched"]["source_id"] = "later-source"
    second = reader("finance_ai")["memory"]
    assert first == second
    assert second[0]["source_lineage"]["source_id"] == "publisher-a"
    assert calls == [{"limit": 1000, "newest_first": True}]


@pytest.mark.parametrize("stage", ["adapter", "provider"])
def test_lineage_failure_preserves_vote_and_never_exposes_error_text(tmp_path, monkeypatch, stage):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'failure.db'}")
    reader = reader_for(monkeypatch, db, [row()])
    provider = AutonomousCouncilProposalProvider(db, object(), news_reader=reader)
    expected = provider._news_opinion("finance_ai", now_ms=NOW)
    def fail(*args, **kwargs):
        raise ValueError("upstream detail must not be persisted")
    target = ("dashboard.autonomous_trading_api.news_memory_lineage" if stage == "adapter"
              else "autonomous_trading.council_provider.opinion_news_lineage")
    monkeypatch.setattr(target, fail)
    lineage = {}
    assert provider._news_opinion("finance_ai", now_ms=NOW, lineage=lineage) == expected
    encoded = json.dumps(lineage)
    assert "ValueError" in encoded and "upstream detail" not in encoded
    if stage == "adapter":
        assert lineage["finance_ai"]["lineage_error_count"] == 1
    else:
        assert lineage["finance_ai"]["status"] == "ERROR"


def test_opportunity_capture_references_the_exact_news_assessment(tmp_path, monkeypatch):
    from test_paper_economic_observer import Capture
    from test_paper_anti_churn_fee_driven import _build_loop, _open_long
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    loop.economic_observer = capture = Capture()
    _open_long(loop, stream, plan, clock, "lineage-entry")
    assert capture.rows[0]["council"]["news_assessment_id"] == plan["proposal"].evidence_packet.news_assessment_id
    assert runtime.consumed == ["lineage-entry"]
