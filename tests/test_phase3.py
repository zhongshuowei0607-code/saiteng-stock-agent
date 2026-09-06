import json
from app.llm.base import explain, AIReport
from app.llm.factory import make_provider
from app.analysis.daily_report import render_reports
from app.analysis.stock_analyzer import StockAnalyzer
from app.analysis.risk_analyzer import risk_score
from app.config.settings import load_settings
from app.database.db import create_db
from app.database.repository import Repository
from test_phase2 import sample

def valid_ai():
    return dict(summary='仅观察',trend='观察',risk='观察',portfolio_analysis='观察',watch_zone='观察',stabilization='观察',bullish_factors=[],bearish_factors=[],next_day_focus=[],conclusion='观察',events=[])

def test_llm_validation():
    class Mock:
        def __init__(self,data): self.data=data
        def complete(self,facts): return self.data
    facts={'market':{'close':49}}
    assert explain(Mock(json.dumps(valid_ai())),facts)['status']=='generated'
    assert explain(Mock('not json'),facts)['status']=='unavailable'
    data=valid_ai();data['summary']='立即买入'
    assert explain(Mock(json.dumps(data)),facts)['status']=='unavailable'
    assert explain(None,facts)['status']=='unavailable'

def test_risk_missing():
    assert risk_score({})['score'] is None

def test_pipeline(tmp_path):
    settings=load_settings(); settings.root=tmp_path
    (tmp_path/'data').mkdir(); (tmp_path/'data/portfolio.json').write_text('{"code":"603283.SH","max_shares":1000,"buys":[{"price":50,"shares":200},{"price":48,"shares":200}]}')
    repo=Repository(create_db(tmp_path/'test.db'));repo.save_bars('603283.SH',sample())
    report=StockAnalyzer(settings,repo).analyze(refresh=False,use_llm=False)
    assert report['portfolio']['average_cost']==49
    assert 0<=report['risk']['score']<=100
    assert len(repo.reports())==1
    assert (tmp_path/'reports/603283'/f'{report["date"]}.html').exists()
    report['ai']['summary']='<script>alert(1)</script>'
    _,page=render_reports(report,tmp_path/'reports')
    assert '<script>' not in page.read_text()
