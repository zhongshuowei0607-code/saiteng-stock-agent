from datetime import date
import json
from app.scheduler.jobs import TradingCalendar, daily_job, build_scheduler

def test_calendar_holiday_and_coverage(tmp_path,monkeypatch):
    cache=tmp_path/'calendar.json'
    cache.write_text(json.dumps({'start':'2026-01-01','end':'2026-12-31','open_days':['2026-09-07']}))
    calendar=TradingCalendar(cache)
    assert calendar.is_open(date(2026,9,7)) is True
    assert calendar.is_open(date(2026,10,1)) is False
    assert calendar.is_open(date(2026,9,6)) is False
    monkeypatch.delenv('TUSHARE_TOKEN',raising=False)
    def fail(*args):raise RuntimeError()
    monkeypatch.setattr('app.scheduler.jobs.fetch',fail)
    assert calendar.is_open(date(2027,1,4)) is None

def test_schedule_and_duplicate():
    class Runner:
        called=0;busy=False;last_error=None
        def reserve(self):return not self.busy
        def run_reserved(self,code):self.called+=1
    class Calendar:
        value=True
        def is_open(self,day):return self.value
    runner=Runner();calendar=Calendar()
    assert daily_job(runner,calendar,date(2026,9,7))
    assert runner.called==1
    runner.busy=True
    assert not daily_job(runner,calendar)
    calendar.value=None
    assert not daily_job(runner,calendar)
    job=build_scheduler(runner,calendar,{'hour':17,'minute':30}).get_jobs()[0]
    assert '17' in str(job.trigger) and str(job.trigger.timezone)=='Asia/Shanghai'
