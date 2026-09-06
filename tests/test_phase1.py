import pandas as pd
import pytest
from app.data.market_provider import normalize_code, validate, MarketService
from app.data.tushare_provider import TushareProvider
from app.data.akshare_provider import AKShareProvider
from app.database.repository import Repository
from app.database.db import create_db
from app.config.settings import load_settings

@pytest.mark.parametrize('code', ['603283','603283.SH','sh603283'])
def test_codes(code):
    assert normalize_code(code) == '603283.SH'

@pytest.mark.parametrize('code', ['../603283','603283.SZ','oops'])
def test_invalid_codes(code):
    with pytest.raises(ValueError): normalize_code(code)

def bars():
    return pd.DataFrame([dict(date='2026-09-04',open=48,close=49,high=50,low=47,volume=100,amount=490000)])

def test_upsert(tmp_path):
    repo = Repository(create_db(tmp_path / 'test.db'))
    frame = validate(bars())
    repo.save_bars('603283.SH', frame)
    frame.loc[0,'close'] = 48
    repo.save_bars('603283.SH', frame)
    assert len(repo.history('603283.SH')) == 1
    assert repo.history('603283.SH').iloc[0]['close'] == 48

def test_validation():
    frame = bars(); frame.loc[0,'high'] = 1
    with pytest.raises(ValueError): validate(frame)

def test_fallback(tmp_path):
    class Bad:
        def history(self,*args): raise RuntimeError('failure')
    class Good:
        def history(self,*args): return bars()
    repo = Repository(create_db(tmp_path/'db'))
    frame, warnings = MarketService([Bad(),Good()],repo).update('603283.SH')
    assert len(frame) == 1 and len(warnings) == 1
    cached, warnings = MarketService([Bad()],repo).update('603283.SH')
    assert len(cached) == 1 and '缓存' in warnings[-1]

def test_tushare_units(monkeypatch):
    class Client:
        def daily(self,**kwargs):
            return pd.DataFrame([dict(ts_code='603283.SH',trade_date='20260904',amount=123,vol=45,close=49)])
        def daily_basic(self,**kwargs):
            return pd.DataFrame([dict(ts_code='603283.SH',trade_date='20260904',total_mv=100,circ_mv=80)])
    provider = TushareProvider()
    monkeypatch.setattr(provider,'client',lambda:Client())
    frame = provider.history('603283','20250101','20260904')
    assert frame.iloc[0].amount == 123000 and frame.iloc[0].total_mv == 1000000

def test_config():
    settings = load_settings()
    assert settings.config['stocks'][0]['code'] == '603283.SH'
