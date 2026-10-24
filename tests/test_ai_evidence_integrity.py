"""Regression tests use isolated databases; never production financial data."""
from dataclasses import replace

import pytest

from news_intelligence.agents import SourceAgent
from news_intelligence.council_lineage import publication_seconds
from news_intelligence.hub import NewsHub
from news_intelligence.models import SourceFetch
from news_intelligence.network import NewsAgentNetwork
from news_intelligence.sources import SourceDefinition, _article
from storage import ProjectDatabase
from learning_engine import OutcomeEvidence
from learning_engine.self_learning_supervisor import _require_verified_settlement_evidence


def definition():
    return SourceDefinition('test', 'Test', 'https://example.test/rss', 'crypto_news', trust_score=90)


def fetch():
    return SourceFetch('test', 'Test', 'rss', 'crypto_news', 1000, 2000, 200, True, '', 1)


def test_unknown_publication_is_not_invented_and_restart_deduplicates(tmp_path, monkeypatch):
    entry = {'title': 'Bitcoin announcement', 'link': 'https://example.test/1'}
    first = _article(definition(), entry)
    second = _article(definition(), entry)
    assert first.published_at == ''
    assert publication_seconds(first.published_at) is None
    assert first.article_id == second.article_id
    db = ProjectDatabase(f'sqlite:///{tmp_path / "news.db"}')
    hub = NewsHub(database=db)
    assert hub.ingest(SourceAgent(definition=definition()), [first], fetch()).accepted == 1
    restored = NewsHub(database=db)
    assert restored.ingest(SourceAgent(definition=definition()), [second], replace(fetch(), received_at_ms=3000)).duplicates == 1


def test_news_words_are_not_matched_inside_unrelated_words():
    article = _article(definition(), {'title': 'Bank publishes corporate methodology', 'summary': 'Whether a report is available.', 'published': '2026-10-24T10:00:00Z'})
    result = SourceAgent(definition=definition()).register(article, fetch())
    assert result.impact == 'neutral'  # bank is not ban; corporate is not rate
    assert 'market_term_hits=0' in result.reasons  # whether/methodology are not ETH
    real = replace(article, article_id='real', title='Bitcoin exchange hack: urgent alert', summary='')
    actual = SourceAgent(definition=definition()).register(real, fetch())
    assert actual.impact == 'bearish' and actual.urgency == 'critical'


def test_cycle_releases_busy_flag_when_start_event_write_fails():
    network = NewsAgentNetwork()
    original = network.hub.event
    def failure(*args, **kwargs):
        raise OSError('disk write failed')
    network.hub.event = failure
    with pytest.raises(OSError):
        network.cycle()
    assert network.snapshot()['running_cycle'] is False
    network.hub.event = original
    network.agents = []
    assert network.cycle()['status'] == 'ok'


def outcome():
    return dict(outcome_id='real-loss', decision_id='d', source='paper', selected_action='BUY', realized_outcome='LOSS', net_pnl=-3, drawdown_contribution=3, regime='trend', occurred_at_ms=1000, verified_market_data=True, evidence_class='verified_market', agents=[dict(agent_id='market', action='BUY', confidence=70, evidence_score=.8, evidence_class='verified_market', verified_market_data=True)])


@pytest.mark.parametrize('flag', ['learning_eligible', 'evidence_eligible', 'data_verified'])
def test_explicit_bad_history_is_excluded_at_both_boundaries(flag):
    payload = {**outcome(), flag: False}
    with pytest.raises(ValueError, match='not learning eligible'):
        OutcomeEvidence.from_mapping(payload)
    with pytest.raises(ValueError, match='not learning eligible'):
        _require_verified_settlement_evidence(payload)


def test_real_negative_outcome_remains_valid_learning_evidence():
    result = OutcomeEvidence.from_mapping(outcome())
    assert result.net_pnl == -3 and result.realized_outcome == 'LOSS'


def test_source_quality_survives_restart_and_keeps_genuine_losses(tmp_path, monkeypatch):
    from learning_engine import SelfLearningSupervisor
    from meta_ai_persistence import EVENT_NAMESPACE
    monkeypatch.setattr('storage.project_database._now_ms', lambda: 2000)
    db = ProjectDatabase(f'sqlite:///{tmp_path / "learning.db"}')
    db.initialize()
    opinions = [{**outcome()['agents'][0], 'confidence': .7}]
    db.append_event(EVENT_NAMESPACE, 'decision_assessment', 'd',
                    {'assessment': {'action': 'BUY'}, 'opinions': opinions},
                    event_id='assessment-d', created_at_ms=1000)
    db.put_json('paper_decision_settlements', 'd', {**outcome(), 'decision_id': 'd', 'settled_at_ms': 1500, 'producer_sha': 'a' * 40}, expected_version=0)
    first = SelfLearningSupervisor(db).run_once(now_ms=3000)
    assert first['processed_count'] == 1 and first['excluded_count'] == 0
    q = db.get_json('self_learning_source_quality', 'd')
    assert q['value']['producer_sha'] == 'a' * 40
    assert q['value']['source_version'] == 1
    assert q['value']['status'] == 'accepted'
    assert SelfLearningSupervisor(db).run_once(now_ms=4000)['skipped_count'] == 1
    assert db.get_json('self_learning_source_quality', 'd')['version'] == q['version']
    # An explicit later technical-quality correction cannot silently keep the
    # old aggregate eligible for challenger promotion; history is preserved.
    row = db.get_json('paper_decision_settlements', 'd')
    db.put_json('paper_decision_settlements', 'd', {**row['value'], 'learning_eligible': False}, expected_version=row['version'])
    rejected = SelfLearningSupervisor(db).run_once(now_ms=5000)
    assert rejected['excluded_count'] == 1
    assert rejected['challenger']['status'] == 'blocked'
    q = db.get_json('self_learning_source_quality', 'd')
    assert q['value']['status'] == 'excluded' and q['value']['source_version'] == 2
    assert 'learning_eligible' in q['value']['reason']
    assert SelfLearningSupervisor(db).run_once(now_ms=6000)['excluded_count'] == 1
    assert db.get_json('self_learning_source_quality', 'd')['version'] == q['version']
    assert db.get_json('self_learning_outcomes_v2', 'paper:d')['value']['net_pnl'] == -3


def test_failed_source_degrades_canonical_organ_instead_of_false_healthy(tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from dashboard.ai_organ_state_api import AIOrganRuntimeMonitor
    db = ProjectDatabase(f'sqlite:///{tmp_path / "monitor.db"}')
    app = FastAPI()
    app.state.news_agent_network = SimpleNamespace(database=db, agents=[object(), object()],
        snapshot=lambda: {'status': 'running', 'last_cycle_at_ms': 2000, 'last_error': '',
                          'agents': [{'source_id': 'good', 'status': 'active'}, {'source_id': 'bad', 'status': 'error'}]})
    monitor = AIOrganRuntimeMonitor(app, db, clock_ms=lambda: 3000)
    evidence, blockers = monitor._news_intelligence()
    assert 'news_worker_running' in evidence
    assert any('bad' in blocker for blocker in blockers)


@pytest.mark.parametrize('flag', ['learning_eligible', 'evidence_eligible', 'data_verified'])
@pytest.mark.parametrize('value', [None, 0, 'false', 'true'])
def test_malformed_explicit_eligibility_fails_closed(flag, value):
    with pytest.raises(ValueError, match='not learning eligible'):
        OutcomeEvidence.from_mapping({**outcome(), flag: value})


@pytest.mark.parametrize('evidence_class', [None, '', 'unknown'])
def test_unknown_outcome_class_is_not_assumed_verified(evidence_class):
    with pytest.raises(ValueError, match='verified outcome evidence class'):
        OutcomeEvidence.from_mapping({**outcome(), 'evidence_class': evidence_class})
