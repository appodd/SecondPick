"""No CLI/collection: real queue persistence with controllable research output."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from test_project_research import research, ingest
from shopping_agent.codex_runtime import AnswerResult
from shopping_agent.project_research import ProjectResearch


def structured(request, **kwargs):
    criteria = [c.model_dump() for c in request.current_criteria] or [dict(
        criterion_id='goal',description='选购要求',priority='hard',source_refs=['task_goal'])]
    return AnswerResult.model_validate(dict(type='answer',content='逐件检查保存证据，缺失部分保持未知。',candidate_ids=[],
        research=dict(criteria=criteria,assessments=[dict(listing_id=i,conclusion='insufficient_evidence',summary='保存信息尚不足以核实全部要求',
            judgments=[dict(criterion_id=c['criterion_id'],status='UNKNOWN',source_type='missing',reason='缺少核实证据',evidence_refs=[])
                       for c in criteria]) for i in request.allowed_listing_ids])))


def seed(store, count=4):
    ids = [ingest(store,price='4000') for _ in range(count)]
    store.enqueue(store.task_id)
    store.execute_next()  # Summary with three nominations; no assessments.
    with store.db() as conn:
        conn.execute("UPDATE versions SET observed_at='2020-01-01T00:00:00+00:00'")
    return ids


def test_later_summary_failure_and_active_run_do_not_erase_valid_judgments(research):
    ids = seed(research,2)
    research.runtime.run = structured
    research.enqueue(research.task_id,ids=ids)
    research.execute_next()
    # Revisit explicitly, then persist a later summary. Frozen prior results unchanged.
    with research.db() as conn:
        original = conn.execute('SELECT result_json FROM studies WHERE id=2').fetchone()[0]
    research.runtime.run = lambda request,**kwargs: AnswerResult(type='answer',content='只有摘要，提到了商品编号',candidate_ids=ids)
    research.enqueue(research.task_id,ids=ids)
    assert research.overview(research.task_id)['coverage']['evaluated']==2
    research.execute_next()
    view = research.overview(research.task_id)
    assert view['coverage']['evaluated']==2 and view['research_work']['unassessed']==0
    assert research.enqueue(research.task_id,automatic=True) is None
    with research.db() as conn:
        assert conn.execute('SELECT result_json FROM studies WHERE id=2').fetchone()[0]==original
    # Same item, new goal: earlier judgment must not be inherited.
    research.save_goal(research.task_id,goal='新的选购要求',budget=5000,hard=[],soft=[],expected_revision=1,request_key='next',confirmed=True)
    assert research.overview(research.task_id)['coverage']['evaluated']==0


def test_followup_is_bounded_and_report_members_are_not_completion(research):
    ids = seed(research,12)
    research.favorite(research.task_id,ids[-1],True)
    with research.db() as conn:
        conn.execute('UPDATE projects SET batch_size=2')
    before = research.overview(research.task_id)
    assert before['pending']==0 and before['research_work']['counts']['ready']==4
    job = research.enqueue(research.task_id)  # Real UI default action, no explicit IDs.
    view = research.overview(research.task_id)
    assert view['studies'][0]['kind']=='followup'
    chosen=view['studies'][0]['listing_ids']
    assert len(chosen)==2 and ids[-1] in chosen
    research.runtime.run=structured
    research.execute_next()
    after=research.overview(research.task_id)
    assert after['coverage']['evaluated']==2 and after['report']==before['report']
    assert after['favorites']==[ids[-1]] and after['total']==12
    second=research.enqueue(research.task_id,automatic=True)
    assert second and second!=job
    assert set(research.overview(research.task_id)['studies'][0]['listing_ids']).isdisjoint(chosen)
    research.execute_next()
    assert research.overview(research.task_id)['coverage']['evaluated']==4
    assert research.enqueue(research.task_id,automatic=True) is None  # Other eight aren't forced into AI.


@pytest.mark.parametrize('output', ['summary','partial','bad_criteria','exception'])
def test_incomplete_followup_stops_durably_and_supports_explicit_retry(research,output):
    ids=seed(research)
    calls=[]
    def run(request,**kwargs):
        calls.append(request)
        if output=='exception':
            raise RuntimeError('controlled provider failure')
        if output=='summary':
            return AnswerResult(type='answer',content='仅文本摘要，没有逐项判断',candidate_ids=ids[:1])
        answer=structured(request)
        if output=='partial':
            answer.research.assessments=answer.research.assessments[:1]
        else:
            answer.research.criteria[0].description='不属于本次目标的条件'
        return answer
    research.runtime.run=run
    job=research.enqueue(research.task_id,automatic=True)
    assert job
    research.execute_next()
    view=research.overview(research.task_id)
    assert view['studies'][0]['state']=='failed' and view['coverage']['evaluated']==0
    assert view['research_work']['counts']['failed']==3
    for _ in range(3):
        assert research.enqueue(research.task_id,automatic=True) is None
    reopened=ProjectResearch(research.config,research.runtime,research.monitors)
    assert reopened.enqueue(research.task_id,automatic=True) is None
    assert len(calls)==1
    research.runtime.run=structured
    research.retry(research.task_id,job)
    research.execute_next()
    assert research.overview(research.task_id)['coverage']['evaluated']==3
    assert research.enqueue(research.task_id,automatic=True) is None


@pytest.mark.parametrize('gate',['paused','unauthorized','completed'])
def test_authorization_and_pause_are_rechecked_before_claim(research,gate):
    seed(research)
    job=research.enqueue(research.task_id,automatic=True)
    assert job
    with research.db() as conn:
        conn.execute(dict(paused='UPDATE projects SET paused=1',unauthorized='UPDATE projects SET auto_research=0',completed='UPDATE projects SET completed=1')[gate])
    assert research.overview(research.task_id)['research_work']['gate']==gate
    assert research.execute_next() is False
    assert len(research.runtime.requests)==1


def test_followup_concurrent_claim_and_reopen_do_not_duplicate(research):
    seed(research)
    with ThreadPoolExecutor(3) as pool:
        jobs=list(pool.map(lambda _:research.enqueue(research.task_id,automatic=True),range(3)))
    assert len(set(jobs))==1 and jobs[0]
    reopened=ProjectResearch(research.config,research.runtime,research.monitors)
    assert reopened.enqueue(research.task_id,automatic=True)==jobs[0]
    with research.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM studies WHERE kind='followup'").fetchone()[0]==1


def test_followup_respects_existing_wait_and_stale_goal_does_not_execute(research):
    moment=datetime.now(timezone.utc)
    research.clock=lambda:moment.isoformat()
    seed(research)
    with research.db() as conn:
        conn.execute('UPDATE versions SET observed_at=?',(moment.isoformat(),))
    assert research.overview(research.task_id)['research_work']['gate']=='waiting'
    assert research.enqueue(research.task_id,automatic=True) is None
    research.clock=lambda:(moment+timedelta(seconds=601)).isoformat()
    job=research.enqueue(research.task_id,automatic=True)
    assert job
    research.save_goal(research.task_id,goal='新的要求',budget=5000,hard=[],soft=[],expected_revision=1,request_key='edit',confirmed=True)
    assert research.execute_next() is False
    with research.db() as conn:
        assert conn.execute('SELECT state FROM studies WHERE id=?',(job,)).fetchone()[0]=='superseded'
    assert len(research.runtime.requests)==1


def test_actual_startup_recovery_keeps_interrupted_followup_attempt(research,monkeypatch):
    seed(research)
    job=research.enqueue(research.task_id,automatic=True)
    with research.db() as conn:
        conn.execute("UPDATE studies SET state='running' WHERE id=?",(job,))
    class NoWorker:
        def __init__(self,**kwargs): pass
        def start(self): pass
    monkeypatch.setattr('shopping_agent.project_research.threading.Thread',NoWorker)
    reopened=ProjectResearch(research.config,research.runtime,research.monitors)
    reopened.start()  # Invoke actual recovery path, suppress background execution only.
    assert reopened.overview(research.task_id)['studies'][0]['state']=='failed'
    assert reopened.enqueue(research.task_id,automatic=True) is None
    assert len(research.runtime.requests)==1
