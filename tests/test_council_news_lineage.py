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
from news_intelligence.council_lineage import compact_denominator_lineage, news_memory_lineage, opinion_news_lineage
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
        {**news_memory_lineage(r), "memory_id": r["key"], "created_at_seconds": (NOW - 1000) // 1000,
         "lineage_error_type": None}
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


@pytest.mark.parametrize("field", [
    "memory_namespace", "source_id", "producer_id", "article_id", "published_at", "exact_link_sha256",
])
@pytest.mark.parametrize("invalid", [None, "", "  ", 123])
def test_incomplete_denominator_origin_cannot_be_complete(field, invalid):
    memory = {"key": "memory-1", "created_at": NOW // 1000,
              "source_lineage": news_memory_lineage(row())}
    older = copy.deepcopy(memory)
    older["source_lineage"][field] = invalid
    result = opinion_news_lineage([older] + [memory] * 50, now_ms=NOW)
    assert result["status"] == "PARTIAL"
    assert result["complete_lineage_count"] == 50
    compact, _, snapshot = compact_denominator_lineage({"finance_ai": result})
    restored = dict(zip(snapshot["record_fields"], snapshot["records"][0]))
    assert restored[field] is None
    assert compact["finance_ai"]["confirmation_denominator_count"] == 51


def test_denominator_origin_versions_survive_snapshot_roundtrip(tmp_path):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'origin.db'}")
    provider = AutonomousCouncilProposalProvider(db, object())
    memory = {"key": "same-memory", "created_at": NOW // 1000,
              "source_lineage": news_memory_lineage(row())}
    original = opinion_news_lineage([memory] * 51, now_ms=NOW)
    first = provider._persist_news_lineage({"finance_ai": original})["finance_ai"]
    snapshot_id = first["denominator_snapshot_id"]
    snapshot = db.get_json("council_news_denominator_snapshots", snapshot_id)["value"]
    restored = dict(zip(snapshot["record_fields"], snapshot["records"][0]))
    assert restored == original["denominator_only_items"][0]
    for field, value in memory["source_lineage"].items():
        assert restored[field] == value
    assert original["status"] == "COMPLETE"
    changed = copy.deepcopy(memory)
    changed["source_lineage"]["source_id"] = "corrected-publisher"
    later = opinion_news_lineage([changed] + [memory] * 50, now_ms=NOW)
    second = provider._persist_news_lineage({"finance_ai": later})["finance_ai"]
    assert second["denominator_snapshot_id"] != snapshot_id
    assert db.get_json("council_news_denominator_snapshots", snapshot_id)["value"] == snapshot


@pytest.mark.parametrize("timestamp", [None, 0, -1, True, "1800000000000"])
def test_invalid_fetch_timestamp_is_partial(timestamp):
    descriptor = news_memory_lineage(row())
    descriptor["fetch_received_at_ms"] = timestamp
    result = opinion_news_lineage([{"key": "memory-1", "source_lineage": descriptor}], now_ms=NOW)
    assert result["status"] == "PARTIAL"
    assert result["items"][0]["fetch_received_at_ms"] is None


@pytest.mark.parametrize("denominator_only", [False, True])
def test_future_fetch_is_partial_and_reported(denominator_only):
    memory = {"key": "memory-1", "created_at": NOW // 1000,
              "source_lineage": news_memory_lineage(row())}
    future = copy.deepcopy(memory)
    future["source_lineage"]["fetch_received_at_ms"] = NOW + 1
    memories = [future] + [memory] * 50 if denominator_only else [future]
    result = opinion_news_lineage(memories, now_ms=NOW)
    assert result["status"] == "PARTIAL"
    assert result["rows_available_after_capture"] == 1


def test_denominator_only_error_is_preserved():
    memory = {"key": "memory-1", "created_at": NOW // 1000,
              "source_lineage": news_memory_lineage(row())}
    failed = {"key": "failed", "created_at": NOW // 1000,
              "source_lineage": {"error_type": "ValueError"}}
    result = opinion_news_lineage([failed] + [memory] * 50, now_ms=NOW)
    assert result["lineage_error_count"] == 1
    assert result["denominator_only_items"][0]["lineage_error_type"] == "ValueError"


def test_future_denominator_eligibility_time_is_partial_and_reported():
    memory = {"key": "memory-1", "created_at": NOW // 1000,
              "source_lineage": news_memory_lineage(row())}
    future = copy.deepcopy(memory)
    future["created_at"] = NOW // 1000 + 1
    result = opinion_news_lineage([future] + [memory] * 50, now_ms=NOW)
    assert result["status"] == "PARTIAL"
    assert result["rows_available_after_capture"] == 1


def test_known_denominator_only_lineage_makes_assessment_partial():
    known = {"key": "known-old", "created_at": NOW // 1000,
             "source_lineage": news_memory_lineage(row("known-old"))}
    legacy = {"key": "legacy", "created_at": NOW // 1000}
    result = opinion_news_lineage([known] + [legacy] * 50, now_ms=NOW)
    assert result["status"] == "PARTIAL"
    assert result["complete_lineage_count"] == 0
    assert result["denominator_only_items"][0]["memory_id"] == "known-old"


def test_compact_denominator_preserves_order_duplicates_and_errors():
    memories = [{"key": str(i), "created_at": NOW // 1000,
                 "source_lineage": news_memory_lineage(row(str(i)))} for i in range(55)]
    memories[0]["source_lineage"] = {"error_type": "ValueError"}
    memories[1] = memories[0]
    original = opinion_news_lineage(memories, now_ms=NOW)
    compact, snapshot_id, snapshot = compact_denominator_lineage({"a": original, "b": original})
    assert len(snapshot["records"]) == 4
    assert compact["a"]["denominator_item_indices"] == compact["b"]["denominator_item_indices"]
    for detail in compact.values():
        assert detail["denominator_snapshot_id"] == snapshot_id
        recovered = [dict(zip(snapshot["record_fields"], snapshot["records"][index]))
                     for index in detail["denominator_item_indices"]]
        assert recovered == original["denominator_only_items"]
    assert compact_denominator_lineage({"a": original, "b": original}) == (compact, snapshot_id, snapshot)


def test_thousand_row_snapshot_is_shared_and_persisted_once(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'bounded.db'}")
    rows = [row(hashlib.sha256(str(i).encode()).hexdigest()) for i in range(1000)]
    provider = AutonomousCouncilProposalProvider(db, object(), news_reader=reader_for(monkeypatch, db, rows))
    lineage = {}
    for agent in ("crypto_ai", "finance_ai", "economy_ai", "security_ai", "world_ai"):
        provider._news_opinion(agent, now_ms=NOW, lineage=lineage)
    puts = []
    put_json = db.put_json
    def put(namespace, key, value, **kwargs):
        puts.append((namespace, key))
        return put_json(namespace, key, value, **kwargs)
    monkeypatch.setattr(db, "put_json", put)
    first = provider._persist_news_lineage(lineage)
    assert first == provider._persist_news_lineage(lineage)
    snapshot_ids = {detail["denominator_snapshot_id"] for detail in first.values()}
    assert len(snapshot_ids) == 1
    snapshot_id = snapshot_ids.pop()
    assert puts == [("council_news_denominator_snapshots", snapshot_id)]
    snapshot = db.get_json(*puts[0])["value"]
    assert len(snapshot["records"]) == 950
    assert len(json.dumps(first).encode()) < 225_000
    # Full origin is stored once per unique row version, shared by all members
    # and unchanged proposals; the assessment itself keeps its original bound.
    assert len(json.dumps(snapshot).encode()) < 325_000
    assert all(len(detail["denominator_item_indices"]) == 950 for detail in first.values())


def test_denominator_storage_failure_keeps_vote_and_marks_missing_evidence(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'snapshot-error.db'}")
    rows = [row(str(i)) for i in range(55)]
    provider = AutonomousCouncilProposalProvider(db, object(), news_reader=reader_for(monkeypatch, db, rows))
    lineage = {}
    expected = provider._news_opinion("finance_ai", now_ms=NOW, lineage=lineage)
    def fail(*args, **kwargs):
        raise OSError("private database connection detail")
    monkeypatch.setattr(provider, "_put_once", fail)
    failed = provider._persist_news_lineage(lineage)
    assert provider._news_opinion("finance_ai", now_ms=NOW) == expected
    assert failed["finance_ai"]["status"] == "ERROR"
    assert failed["finance_ai"]["denominator_error_type"] == "OSError"
    assert failed["finance_ai"]["denominator_unavailable_count"] == 5
    assert "denominator_only_items" not in failed["finance_ai"]
    assert "private database" not in json.dumps(failed)


def test_snapshot_failure_preserves_agents_without_denominator_rows(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'mixed-snapshot-error.db'}")
    provider = AutonomousCouncilProposalProvider(db, object(), news_reader=lambda *a, **k: {"memory": []})
    memory = {"key": "memory-1", "created_at": NOW // 1000,
              "source_lineage": news_memory_lineage(row())}
    short = opinion_news_lineage([memory], now_ms=NOW)
    long = opinion_news_lineage([memory] * 51, now_ms=NOW)
    monkeypatch.setattr(provider, "_put_once", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    failed = provider._persist_news_lineage({"short": short, "long": long})
    assert failed["short"]["status"] == "COMPLETE"
    assert failed["short"]["denominator_unavailable_count"] == 0
    assert failed["short"]["denominator_error_type"] is None
    assert failed["long"]["status"] == "ERROR"
    assert failed["long"]["denominator_unavailable_count"] == 1
    assert failed["long"]["denominator_error_type"] == "OSError"


def test_denominator_storage_failure_preserves_full_proposal_and_authority(tmp_path, monkeypatch):
    monkeypatch.setattr("time.time", lambda: NOW / 1000)
    monkeypatch.setattr("decision_quality.service.datetime", FrozenDateTime)
    outputs = []
    for fails in (False, True):
        db = ProjectDatabase(f"sqlite:///{tmp_path / ('failure-' + str(fails))}.db")
        reader = reader_for(monkeypatch, db, [row(str(i)) for i in range(55)])
        worker = FakeWorker()
        worker.database = db
        stream = SharedVerifiedMarketStream(worker, FakeMarketData(), FakeConsensus(), database=db)
        quote = replace(stream.quote("BTCUSDT"), change_24h_percent=2.4)
        original_put = db.put_json
        def put(namespace, key, value, **kwargs):
            if fails and namespace == "council_news_denominator_snapshots":
                raise OSError("unpersisted private detail")
            return original_put(namespace, key, value, **kwargs)
        monkeypatch.setattr(db, "put_json", put)
        proposal = AutonomousCouncilProposalProvider(db, stream, news_reader=reader)("BTCUSDT", quote, _state())
        assert proposal is not None
        auth = CanonicalPaperDecisionRuntime(db).assess_entry(
            proposal.decision_id, proposal.agent_payloads, proposal.evidence_packet,
            general_controller_decision=proposal.general_controller_decision, now_ms=NOW, regime=proposal.regime)
        outputs.append((proposal, auth.to_dict()))
        assessment = db.get_json("council_news_assessments", proposal.evidence_packet.news_assessment_id)["value"]
        assert {detail["status"] for detail in assessment["opinion_lineage"].values()} == ({"ERROR"} if fails else {"COMPLETE"})
        assert "private detail" not in json.dumps(assessment)
    assert outputs[0] == outputs[1]


def test_denominator_origin_status_does_not_change_proposal_or_authority(tmp_path, monkeypatch):
    monkeypatch.setattr("time.time", lambda: NOW / 1000)
    monkeypatch.setattr("decision_quality.service.datetime", FrozenDateTime)
    outputs = []
    for missing in (False, True):
        db = ProjectDatabase(f"sqlite:///{tmp_path / ('origin-' + str(missing))}.db")
        rows = [row(str(i)) for i in range(55)]
        if missing:
            for r in rows[:5]:
                r["value"]["fetched"].pop("source_id")
        worker = FakeWorker()
        worker.database = db
        stream = SharedVerifiedMarketStream(worker, FakeMarketData(), FakeConsensus(), database=db)
        quote = replace(stream.quote("BTCUSDT"), change_24h_percent=2.4)
        proposal = AutonomousCouncilProposalProvider(
            db, stream, news_reader=reader_for(monkeypatch, db, rows))("BTCUSDT", quote, _state())
        assert proposal is not None
        auth = CanonicalPaperDecisionRuntime(db).assess_entry(
            proposal.decision_id, proposal.agent_payloads, proposal.evidence_packet,
            general_controller_decision=proposal.general_controller_decision, now_ms=NOW, regime=proposal.regime)
        outputs.append((proposal, auth.to_dict()))
        assessment = db.get_json("council_news_assessments", proposal.evidence_packet.news_assessment_id)["value"]
        assert {d["status"] for d in assessment["opinion_lineage"].values()} == ({"PARTIAL"} if missing else {"COMPLETE"})
    assert outputs[0] == outputs[1]


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
