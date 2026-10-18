import pytest
from autonomous_trading.decision_trace import persist_decision_trace
from storage import ProjectDatabase

@pytest.mark.parametrize('phase',['preflight','market_evidence','market_verification','market_stream','quote','proposal_provider','proposal_interval','council'])
def test_new_observation_does_not_refresh_old_authorization(tmp_path,phase):
 db=ProjectDatabase(f'sqlite:///{tmp_path / "trace.db"}');db.initialize()
 persist_decision_trace(db,'BTCUSDT',{'phase':'council','decision_id':'old','authorized':True,'risk_blocks':['old_block'],'quote_age_ms':10,'market_verified':True},now_ms=100)
 result=persist_decision_trace(db,'BTCUSDT',{'phase':phase,'status':'WAIT','reason':'current'},now_ms=200)
 assert result['updated_at_ms']==200
 assert not {'decision_id','authorized','risk_blocks','quote_age_ms','market_verified'} & result.keys()

def test_same_decision_stages_preserve_current_evidence(tmp_path):
 db=ProjectDatabase(f'sqlite:///{tmp_path / "trace.db"}');db.initialize()
 persist_decision_trace(db,'BTCUSDT',{'phase':'council','decision_id':'current','market_verified':True,'quote_age_ms':12},now_ms=100)
 result=persist_decision_trace(db,'BTCUSDT',{'phase':'execution_gate','status':'WAIT','reason':'no spot position'},now_ms=101)
 assert result['decision_id']=='current' and result['market_verified'] and result['quote_age_ms']==12

def test_new_decision_identity_cannot_inherit_old_fields(tmp_path):
 db=ProjectDatabase(f'sqlite:///{tmp_path / "trace.db"}');db.initialize()
 persist_decision_trace(db,'BTCUSDT',{'decision_id':'old','authorized':True},now_ms=100)
 result=persist_decision_trace(db,'BTCUSDT',{'phase':'virtual_execution','decision_id':'new','status':'BLOCK'},now_ms=200)
 assert result['decision_id']=='new' and 'authorized' not in result


@pytest.mark.parametrize("exit_fields", [{"decision_id": "entry", "status": "SELL"}, {"status": "BLOCK"}])
def test_protective_exit_does_not_inherit_entry_vote(tmp_path, exit_fields):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'trace.db'}")
    db.initialize()
    persist_decision_trace(db, "BTCUSDT", {"phase": "council", "decision_id": "entry", "authorized": True, "risk_blocks": [], "decision_quality_confidence": 1.0}, now_ms=100)
    result = persist_decision_trace(db, "BTCUSDT", {"phase": "protective_exit", **exit_fields}, now_ms=200)
    assert not {"authorized", "risk_blocks", "decision_quality_confidence"} & result.keys()
    assert result["status"] == exit_fields["status"]
