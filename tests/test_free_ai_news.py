"""Isolated free-mode, content provenance and news quality contracts."""
from dataclasses import replace
from types import SimpleNamespace
import json
import httpx
import pytest
import agent_intelligence
from ai_provider_policy import provider_block_reason
from memory_engine.extraction import OpenAICompatibleEmbeddingProvider, OpenAICompatibleJSONClient
from news_intelligence.sources import SourceDefinition, SourceCollector, _article, source_definitions
from news_intelligence.full_text import PrimaryTextCollector
from news_intelligence.enrichment import descriptors, plain_text, corroboration_candidates
from news_intelligence.agents import SourceAgent
from news_intelligence.models import SourceFetch
from news_intelligence.hub import NewsHub
from storage import ProjectDatabase


def definition():
    return SourceDefinition('test', 'Publisher', 'https://example.com/feed', 'crypto_news')


def article(title='Bitcoin market announcement', **extra):
    return _article(definition(), {'title':title,'link':'https://example.com/a',
        'published':'2026-10-25T00:00:00Z', **extra})


def fetched():
    return SourceFetch('test','Publisher','rss','crypto_news',1792886400000,1792886405000,200,True,'',1)


def ask():
    return agent_intelligence.answer_with_intelligence(agent_id='risk_engine',agent_name='Risk',role='risk',question='status')


def test_offline_blocks_all_provider_entry_points_even_with_keys(monkeypatch):
    monkeypatch.delenv('AI_PROVIDER_MODE', raising=False)
    monkeypatch.setenv('AGENT_LLM_BASE_URL','https://openrouter.ai/api/v1')
    monkeypatch.setenv('AGENT_LLM_API_KEY','test-only')
    monkeypatch.setenv('AGENT_LLM_MODEL','qwen/test')
    monkeypatch.setattr(httpx,'post',lambda *a,**k:pytest.fail('network forbidden'))
    assert ask().error=='offline_policy_no_model_requests'
    for client in [OpenAICompatibleJSONClient(base_url='https://example.com',api_key='test',model='model'),
                   OpenAICompatibleEmbeddingProvider(base_url='https://example.com',api_key='test',model='model')]:
        with pytest.raises(RuntimeError,match='offline_policy'):
            client.embed('test') if hasattr(client,'embed') else client.complete_json(system='s',user='u')


@pytest.mark.parametrize('url',['https://openrouter.ai/v1','http://localhost:8001/v1','http://127.0.0.1.evil.test/v1','http://10.0.0.1/v1','http://127.0.0.1/v1?redirect=https://elsewhere'])
def test_local_policy_cannot_route_to_remote_or_ambiguous_names(monkeypatch,url):
    monkeypatch.setenv('AI_PROVIDER_MODE','local')
    assert provider_block_reason(url)


@pytest.mark.parametrize('failure',['402','offline','timeout'])
def test_model_failure_never_generates_fake_answer_or_paid_fallback(monkeypatch,failure):
    monkeypatch.setenv('AI_PROVIDER_MODE','local');monkeypatch.setenv('AGENT_LLM_BASE_URL','http://127.0.0.1:8081/v1')
    monkeypatch.setenv('AGENT_LLM_MODEL','local-model');monkeypatch.setenv('MEMORY_LLM_API_KEY','remote-secret-must-not-leak')
    calls=[]
    def fail(url,**kwargs):
        calls.append(url);assert 'remote-secret' not in str(kwargs)
        if failure=='offline':raise httpx.ConnectError('no internet')
        if failure=='timeout':raise httpx.ReadTimeout('timeout')
        return httpx.Response(402,request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',fail)
    answer=ask();assert answer.status=='unavailable' and not answer.text and not answer.grounded
    assert calls==['http://127.0.0.1:8081/v1/chat/completions']


def test_default_sources_replace_failures_with_explicit_distinct_ids(monkeypatch):
    monkeypatch.delenv('NEWS_AGENT_SOURCE_IDS',raising=False)
    ids={x.source_id for x in source_definitions()}
    assert {'coinbase_status','marketwatch_top','bank_of_england_news','bleepingcomputer'}<=ids
    assert not {'coinbase_blog','reuters_markets','treasury_press','cisa_alerts'}&ids


def test_feed_body_is_text_only_and_does_not_invent_publication():
    a=article(content=[{'value':'<p>Actual publisher text.</p><script>fake()</script>'}],published='')
    assert a.content=='Actual publisher text.' and a.content_scope=='publisher_feed_body'
    d=descriptors(a,fetched());assert d['publication_time_status']=='unknown' and d['publication_delay_ms'] is None
    assert not d['fact_confirmed'] and d['available_at_ms']==fetched().received_at_ms


@pytest.mark.parametrize('title,expected',[
    ('Unconfirmed Bitcoin ETF approval rumor','unconfirmed_report'),
    ('Bitcoin could rise next month: forecast','forecast'),
    ('Opinion: Bitcoin adoption is improving','opinion'),
    ('Bitcoin exchange announces maintenance','reported_event')])
def test_claim_types_are_not_misrepresented_as_confirmed_facts(title,expected):
    d=descriptors(article(title),fetched());assert d['claim_type']==expected
    assert d['assets']==['BTC'] and not d['fact_confirmed']


def test_language_and_latency_are_measurements_not_fake_confidence():
    d=descriptors(article('Биткоин: опубликовано сообщение о событии'),fetched())
    assert d['detected_language']=='ru' and d['publication_delay_ms']==5000
    assert d['news_predictive_utility']=='NOT_VALIDATED'


def test_primary_fetch_denies_redirects_private_urls_and_robots(monkeypatch):
    p=PrimaryTextCollector();calls=[]
    def get(url):calls.append(url);return 200,'User-agent: *\nDisallow: /'
    monkeypatch.setattr(p,'_read',get)
    assert p.fetch('http://127.0.0.1/latest')['status']=='not_allowlisted' and not calls
    url='https://www.federalreserve.gov/newsevents/pressreleases/a.htm'
    assert p.fetch(url)['status']=='robots_denied_or_unavailable' and len(calls)==1
    p=PrimaryTextCollector();monkeypatch.setattr(p,'_read',lambda url:(404,'') if url.endswith('robots.txt') else (302,''))
    assert p.fetch(url)['status']=='unavailable'


def test_primary_text_is_bounded_cached_and_preserved_after_restart(tmp_path,monkeypatch):
    p=PrimaryTextCollector();calls=[]
    body='The Federal Reserve published an official decision about policy. '*4
    def get(url):
        calls.append(url)
        return (404,'') if url.endswith('robots.txt') else (200,f'<nav>Ignore</nav><div id="article"><p>{body}</p></div><p>Footer</p>')
    monkeypatch.setattr(p,'_read',get)
    url='https://www.federalreserve.gov/newsevents/pressreleases/a.htm'
    result=p.fetch(url);assert result['status']=='ok' and result['text']==body.strip()
    assert p.fetch(url)==result and len(calls)==2
    a=replace(article(),content=result['text'],content_scope='primary_full_text',content_observed_at_ms=result['observed_at_ms'],content_status='ok')
    db=ProjectDatabase(f'sqlite:///{tmp_path / "news.db"}');h=NewsHub(database=db)
    assert h.ingest(SourceAgent(definition=definition()),[a],fetched()).accepted==1
    restored=NewsHub(database=db)
    assert restored.memory()[0]['article']['content']==body.strip()
    assert restored.memory()[0]['analysis']['available_at_ms']>=result['observed_at_ms']
    assert restored.ingest(SourceAgent(definition=definition()),[a],fetched()).duplicates==1


def test_syndicated_copy_is_not_independent_confirmation():
    agent=SourceAgent(definition=definition())
    a=agent.register(article('Bitcoin exchange announces new policy after security event',summary='Reuters reports the news'),fetched())
    b=replace(a,article=replace(a.article,link='https://different.example/story',source='Different',title='Bitcoin exchange announces policy after security event'))
    assert corroboration_candidates(b,[a])==[]


def test_changed_historical_label_quarantines_learning_without_rewriting_history(tmp_path):
    from learning_engine import SelfLearningSupervisor
    from tests.test_ai_evidence_integrity import outcome
    db=ProjectDatabase(f'sqlite:///{tmp_path / "learning.db"}');db.initialize()
    worker=SelfLearningSupervisor(db)
    evidence={**outcome(),'decision_id':'d','outcome_id':'paper:d'}
    worker.attribution.record(evidence)
    original=db.get_json('self_learning_outcomes_v2','paper:d')
    db.put_json('paper_decision_settlements','d',{**evidence,'net_pnl':5},expected_version=0)
    for _ in range(2):
        result=SelfLearningSupervisor(db).run_once()
        assert result['contaminated_count']==1 and result['challenger']['status']=='blocked'
        quality=db.get_json('self_learning_source_quality','d')['value']
        assert quality['reason']=='attributed_financial_label_changed'
        assert db.get_json('self_learning_outcomes_v2','paper:d')==original
        assert db.get_json('paper_decision_settlements','d')['value']['net_pnl']==5


def test_news_answer_uses_canonical_memory_without_legacy_fetch(tmp_path, monkeypatch):
    import ai_chat_orchestrator as chat
    db = ProjectDatabase(f'sqlite:///{tmp_path / "chat.db"}')
    db.initialize()
    db.put_json('ai_organ_runtime', 'news_intelligence', {'status':'healthy', 'checked_at_ms':1000})
    db.put_json('news_memory', 'article', {'article':{'title':'Real stored evidence', 'source':'Publisher',
                'published_at':'2026-10-25T00:00:00Z', 'link':'https://example.com/a'},
                'analysis':{'claim_type':'unconfirmed_report'}})
    monkeypatch.setattr(chat, 'ProjectDatabase', lambda:db)
    monkeypatch.setattr(chat.time, 'time', lambda:1.5)
    monkeypatch.setattr(chat, 'run_news_agents', lambda:pytest.fail('legacy network must not run'))
    result = chat._answer_news()
    assert result['status']=='ok' and result['data']['fresh']
    assert 'Real stored evidence' in result['reply'] and 'unconfirmed_report' in result['reply']
    assert 'достоверность' not in result['reply']
    monkeypatch.setattr(chat.time, 'time', lambda:1000)
    assert chat._answer_news()['status']=='unavailable'


@pytest.mark.parametrize('kind',['json','embedding'])
def test_local_memory_never_forwards_remote_credentials(monkeypatch, kind):
    monkeypatch.setenv('AI_PROVIDER_MODE','local')
    monkeypatch.delenv('AI_LOCAL_LLM_API_KEY', raising=False)
    def post(url, **kwargs):
        assert 'Authorization' not in kwargs['headers']
        payload = {'choices':[{'message':{'content':'{}'}}]} if kind=='json' else {'data':[{'embedding':[0.1,0.2]}]}
        return httpx.Response(200,json=payload,request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    client = (OpenAICompatibleJSONClient if kind=='json' else OpenAICompatibleEmbeddingProvider)(
        base_url='http://127.0.0.1:8080/v1', api_key='remote-key-must-not-leak', model='local')
    assert client.complete_json(system='s',user='u')=={} if kind=='json' else client.embed('u')==[0.1,0.2]


def test_malformed_publisher_url_does_not_interrupt_news_analysis():
    a = replace(article(), link='https://[malformed')
    assert descriptors(a, fetched())['publisher_host'] is None
    assert PrimaryTextCollector().fetch(a.link)['status']=='not_allowlisted'
    envelope = SourceAgent(definition=definition()).register(a, fetched())
    assert corroboration_candidates(envelope, [envelope])==[]
