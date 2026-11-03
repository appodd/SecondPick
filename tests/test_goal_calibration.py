"""Existing queue integration; offline runtimes, real persistence, controlled time."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from test_project_research import research, ingest, consume_summary_followup
from shopping_agent.project_research import ProjectResearch


def edit(store, *, budget=5000, goal='买电脑', hard=None, soft=None):
    version=store.goal(store.task_id)['revision']
    return store.save_goal(store.task_id,goal=goal,budget=budget,hard=hard if hard is not None else ['内存至少16GB'],
        soft=soft if soft is not None else ['优先个人闲置'],expected_revision=version,
        request_key=f'goal-change-{version}',confirmed=True)


@pytest.fixture
def timed(research):
    moment=[datetime(2026,10,23,tzinfo=timezone.utc)]
    research.clock=lambda:moment[0].isoformat()
    research.advance=lambda:moment.__setitem__(0,moment[0]+timedelta(seconds=6))
    return research


def test_hard_change_uses_bounded_queue_and_publishes_then_incremental_resumes(timed):
    store=timed
    expensive=ingest(store,price='6000')
    affordable=[ingest(store,price='4000',title='MacBook Pro M2 16GB 512GB') for _ in range(25)]
    store.favorite(store.task_id,affordable[0],True)
    store.create_window(store.task_id,'保留的监控','ongoing',60,dict(keyword='MacBook',max_pages=1,max_items=5,interval_seconds=600,collect_seller_profiles=False))
    store.enqueue(store.task_id); store.execute_next()
    before=store.monitors.list(store.task_id)
    edit(store); store.advance()
    queued=store.enqueue(store.task_id,automatic=True)
    view=store.overview(store.task_id)
    assert view['goal_context']['calibration_work']['state']=='scheduled'
    selected=view['studies'][0]['listing_ids']
    assert len(selected)==10 and expensive not in selected and affordable[0] in selected
    assert view['studies'][0]['kind']=='initial'  # Report-producing existing kind, not a selected chat.
    assert not view['goal_context']['report_current']
    during=[]
    store.runtime.callback=lambda:during.append(store.overview(store.task_id)['goal_context']['calibration_work']['state'])
    store.execute_next(); store.runtime.callback=None
    assert during==['running']
    view=store.overview(store.task_id)
    assert view['goal_context']['calibration_work']['state']=='current'
    assert view['report']['goal_revision']==2 and view['report']['study_id']==queued
    assert view['total']==26 and view['favorites']==[affordable[0]]
    assert store.monitors.list(store.task_id)==before
    consume_summary_followup(store)  # Only nominated/favorited summary inputs, no full historical backfill.
    store.advance()
    new=[ingest(store,price='4000') for _ in range(10)]
    assert store.enqueue(store.task_id,automatic=True)
    assert set(new)<=set(store.overview(store.task_id)['studies'][0]['listing_ids'])


def test_soft_only_and_no_usable_samples_do_not_call_ai(timed):
    ingest(timed); timed.enqueue(timed.task_id); timed.execute_next()
    edit(timed,budget=7000,soft=['优先同城'])
    timed.advance()
    assert timed.enqueue(timed.task_id,automatic=True) is None
    assert timed.overview(timed.task_id)['goal_context']['calibration_work']['state']=='not_needed'
    assert len(timed.runtime.requests)==1
    # A subsequent hard change is compared to the report, not merely the last soft edit.
    edit(timed,budget=100)
    timed.advance()
    assert timed.enqueue(timed.task_id,automatic=True) is None
    assert '没有可安排' in timed.overview(timed.task_id)['goal_context']['calibration_work']['reason']


def test_remaining_history_is_reachable_by_manual_batches_without_automatic_backfill(timed):
    items={ingest(timed,price='4000') for _ in range(25)}
    expensive=ingest(timed,price='8000')
    edit(timed);timed.advance()
    timed.enqueue(timed.task_id,automatic=True);timed.execute_next()
    view=timed.overview(timed.task_id)
    assert view['coverage']['waiting']==15
    consume_summary_followup(timed)
    timed.enqueue(timed.task_id);timed.execute_next()  # Existing UI's finite-batch action.
    with timed.db() as conn:
        covered={r[0] for r in conn.execute('SELECT listing_id FROM report_members WHERE report_id=?',(timed.overview(timed.task_id)['report']['id'],))}
    assert items<=covered and expensive not in covered
    view=timed.overview(timed.task_id)
    assert view['coverage']['waiting']==0 and view['coverage']['rule_excluded']==1
    assert view['pending']==1  # Unreported rule exclusion, not unfinished model work.


def test_soft_change_before_first_report_preserves_original_baseline_threshold(timed):
    ingest(timed,price='4000')
    edit(timed,budget=7000,soft=['优先同城'])
    timed.advance()
    assert timed.enqueue(timed.task_id,automatic=True) is None
    ingest(timed,price='4000')
    job=timed.enqueue(timed.task_id,automatic=True)
    assert job
    with timed.db() as conn:
        assert conn.execute('SELECT proof FROM study_goal_bindings WHERE study_id=?',(job,)).fetchone()[0]!='automatic_calibration'
    timed.execute_next()
    assert timed.overview(timed.task_id)['report']['goal_revision']==2


def test_pause_authorization_and_completed_are_checked_before_enqueue_and_claim(timed,monkeypatch):
    ingest(timed); edit(timed); timed.advance()
    timed.control(timed.task_id,'pause')
    with pytest.raises(ValueError):
        timed.enqueue(timed.task_id,automatic=True)
    assert timed.overview(timed.task_id)['goal_context']['calibration_work']['state']=='unavailable'
    timed.control(timed.task_id,'resume')
    with timed.db() as conn:
        conn.execute('UPDATE projects SET auto_research=0')
    assert timed.enqueue(timed.task_id,automatic=True) is None
    with timed.db() as conn:
        conn.execute('UPDATE projects SET auto_research=1')
    original=timed._request
    def snapshot(*args,**kwargs):
        request=original(*args,**kwargs)
        timed.control(timed.task_id,'pause')
        return request
    monkeypatch.setattr(timed,'_request',snapshot)
    assert timed.enqueue(timed.task_id,automatic=True) is None
    monkeypatch.setattr(timed,'_request',original)
    timed.control(timed.task_id,'resume')
    assert timed.enqueue(timed.task_id,automatic=True)
    timed.control(timed.task_id,'pause')
    assert not timed.execute_next() and not timed.runtime.requests
    timed.control(timed.task_id,'resume')
    with timed.db() as conn:
        conn.execute('UPDATE projects SET auto_research=0')
    assert not timed.execute_next() and not timed.runtime.requests
    with timed.db() as conn:
        conn.execute('UPDATE projects SET auto_research=1,completed=1')
    assert not timed.execute_next()


def test_continuous_edits_retire_only_unstarted_calibrations_and_restart_dedup(timed):
    item=ingest(timed,price='4000'); edit(timed); timed.advance()
    with ThreadPoolExecutor(2) as pool:
        ids=list(pool.map(lambda _:timed.enqueue(timed.task_id,automatic=True),range(2)))
    assert ids[0]==ids[1]
    reopened=ProjectResearch(timed.config,timed.runtime,timed.monitors,clock=timed.clock)
    assert reopened.enqueue(timed.task_id,automatic=True)==ids[0]
    manual=timed.enqueue(timed.task_id,ids=[item],question='手动检查配置')
    edit(timed,budget=4500); edit(timed,budget=4300); timed.advance()
    with timed.db() as conn:
        assert conn.execute('SELECT state FROM studies WHERE id=?',(ids[0],)).fetchone()[0]=='superseded'
        assert conn.execute('SELECT state FROM studies WHERE id=?',(manual,)).fetchone()[0]=='queued'
    timed.execute_next()  # Explicit manual work is never silently cancelled.
    new=timed.enqueue(timed.task_id,automatic=True)
    assert new and new!=ids[0]
    timed.execute_next()
    assert len(timed.runtime.requests)==2  # One manual and only latest calibration.
    assert timed.overview(timed.task_id)['report']['goal_revision']==4
    reopened.task_id=timed.task_id
    consume_summary_followup(reopened)


def test_running_calibration_old_goal_keeps_history_and_latest_gets_own_report(timed):
    ingest(timed,price='4000'); edit(timed); timed.advance()
    old=timed.enqueue(timed.task_id,automatic=True)
    timed.runtime.callback=lambda:edit(timed,budget=4500)
    timed.execute_next(); timed.runtime.callback=None
    view=timed.overview(timed.task_id)
    assert view['report']['goal_revision']==2 and not view['goal_context']['report_current']
    assert view['studies'][0]['state']=='completed'
    timed.advance()
    new=timed.enqueue(timed.task_id,automatic=True); assert new!=old
    timed.execute_next()
    assert timed.overview(timed.task_id)['report']['goal_revision']==3


def test_failure_and_recovery_do_not_create_an_automatic_retry_loop(timed):
    ingest(timed); edit(timed); timed.advance()
    job=timed.enqueue(timed.task_id,automatic=True)
    timed.runtime.fail=True; timed.execute_next()
    reopened=ProjectResearch(timed.config,timed.runtime,timed.monitors,clock=timed.clock)
    for _ in range(3):
        assert reopened.enqueue(timed.task_id,automatic=True)==job
        assert not reopened.execute_next()
    assert len(timed.runtime.requests)==1
    assert reopened.overview(timed.task_id)['goal_context']['calibration_work']['state']=='unavailable'
    timed.runtime.fail=False; reopened.retry(timed.task_id,job); reopened.execute_next()
    assert reopened.overview(timed.task_id)['goal_context']['report_current']


def test_hard_edit_followed_by_soft_edit_still_calibrates_latest(timed):
    ingest(timed); timed.enqueue(timed.task_id); timed.execute_next()
    edit(timed)
    edit(timed,soft=['优先同城'])
    timed.advance()
    assert timed.enqueue(timed.task_id,automatic=True)
    assert timed.overview(timed.task_id)['studies'][0]['goal_revision']==3


def test_real_startup_recovery_keeps_calibration_key_and_never_relaunches_interrupted_job(timed,monkeypatch):
    import threading
    ingest(timed); edit(timed); timed.advance()
    job=timed.enqueue(timed.task_id,automatic=True)
    with timed.db() as conn:
        frozen=conn.execute('SELECT request_json FROM studies WHERE id=?',(job,)).fetchone()[0]
        conn.execute("UPDATE studies SET state='running' WHERE id=?",(job,))
    reopened=ProjectResearch(timed.config,timed.runtime,timed.monitors,clock=timed.clock)
    monkeypatch.setattr(threading.Thread,'start',lambda self:None)
    reopened.start()  # The real startup recovery, with only background ticking disabled.
    assert reopened.enqueue(timed.task_id,automatic=True)==job
    assert not reopened.execute_next() and not timed.runtime.requests
    with reopened.db() as conn:
        row=conn.execute('SELECT * FROM studies WHERE id=?',(job,)).fetchone()
        assert row['state']=='failed' and row['request_json']==frozen
        assert conn.execute('SELECT COUNT(*) FROM studies').fetchone()[0]==1


def test_prior_structured_judgments_reused_as_context_not_current_coverage(timed):
    from shopping_agent.codex_runtime import AnswerResult
    item=ingest(timed,price='4000')
    def answer(request,**kwargs):
        return AnswerResult.model_validate(dict(type='answer',content='历史评价',candidate_ids=[item],research=dict(
            criteria=[dict(criterion_id='memory',description='内存',priority='hard',source_refs=['task_goal'],source_message_ids=[])],
            assessments=[dict(listing_id=item,conclusion='insufficient_evidence',summary='缺少凭证',judgments=[dict(criterion_id='memory',status='UNKNOWN',source_type='missing',reason='待核实',evidence_refs=[])])])) )
    timed.runtime.run=answer
    timed.enqueue(timed.task_id); timed.execute_next()
    edit(timed); timed.advance()
    job=timed.enqueue(timed.task_id,automatic=True)
    with timed.db() as conn:
        request=conn.execute('SELECT request_json FROM studies WHERE id=?',(job,)).fetchone()[0]
    assert '历史逐项评价' in request and '缺少凭证' in request
    assert timed.overview(timed.task_id)['coverage']['evaluated']==0
