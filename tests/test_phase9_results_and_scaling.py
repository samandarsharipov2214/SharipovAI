from campaigns.phase9_results import CampaignResultsService, ScalingPolicy
from storage import ProjectDatabase


def test_phase9_report_and_scaling_are_fail_closed(tmp_path):
    db = ProjectDatabase(tmp_path / 'phase9.db')
    db.initialize()
    service = CampaignResultsService(db, policy=ScalingPolicy(minimum_campaigns=1, minimum_fills=2))
    analysis = {'campaign_id':'c1','analysis_id':'a1','fill_count':2,'matched_fill_count':2,'fee_ratio_bps':5,'failed_gates':[], 'pnl':{'net_realized_pnl_usdt':0.8}, 'divergence':{'price_divergence_bps':2}}
    fills = [
        {'symbol':'BTCUSDT','side':'Buy','filled_quantity':1,'average_fill_price':10,'actual_fee':0.01,'last_exec_time_ms':1},
        {'symbol':'BTCUSDT','side':'Sell','filled_quantity':1,'average_fill_price':11,'actual_fee':0.01,'last_exec_time_ms':2},
    ]
    report = service.build_report(analysis, fills, generated_at_ms=10)
    assert report['risk_metrics']['closed_trade_count'] == 1
    assert report['risk_metrics']['maximum_drawdown_bps'] == 0
    plan = service.prepare_scaling([report], actor='operator', reason='measured evidence')
    assert plan['automatic_scaling'] is False
    assert plan['runtime_flags_changed'] is False
    assert plan['mainnet_enabled'] is False
