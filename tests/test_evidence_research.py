"""P2 uses real queue/persistence with controlled model output, no live access."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone

import pytest

from test_project_research import research,ingest
from test_research_followup import structured
from test_project_investigations import save_detail
from shopping_agent.codex_runtime import AnswerResult
from shopping_agent.project_research import ProjectResearch
from shopping_agent import evidence_research
from shopping_agent.db import add_listing_snapshot,add_detail_snapshot


def supported_improvement(request, **kwargs):
    """Mock changed hard-condition assessment citing an actual new excerpt."""
    from shopping_agent.assessment import input_refs
    result=structured(request)
    refs=input_refs(request)
    for a in result.research.assessments:
        a.conclusion='conditional'
        a.summary='新增完整描述支持内存条件；机况仍待核实'
        hard=next((j for j in a.judgments if j.criterion_id=='hard_1'),None)
        if hard:
            hard.status='MET';hard.source_type='seller_claim'
            hard.reason='卖家在新增完整描述中明确声明16GB内存；不代表实物已核验'
            hard.evidence_refs=[next(ref for ref in refs if ref.startswith(f'detail:{a.listing_id}:'))]
    result.candidate_ids=list(request.allowed_listing_ids)
    return result


def seed(p):
    ids=[ingest(p,price='3000') for _ in range(3)]
    p.enqueue(p.task_id);p.execute_next()
    p.runtime.run=structured;p.enqueue(p.task_id,ids=ids,_followup=True);p.execute_next()
    p.clock=lambda:(datetime.now(timezone.utc)+timedelta(seconds=1000)).isoformat()
    return ids


def changed(p,listing,description='Seller discloses repaired buttons'):
    save_detail(p,listing,description)
    p.overview(p.task_id)
    with p.db() as conn:
        conn.execute("UPDATE versions SET observed_at='2020-01-01T00:00:00+00:00'")


def test_delta_semantics_no_cross_category_amount_threshold():
    a=dict(title='a',price=100,description='',attributes={},condition='',seller={},statements=[])
    assert not evidence_research.changes(a,dict(a,price=999),None)['important']
    assert evidence_research.changes(a,dict(a,price=101),100)['budget_crossed']
    for key,value in [('attributes',{'型号':'b'}),('description','卖家称维修过'),('seller',{'seller_credit_level':'变更'})]:
        assert evidence_research.changes(a,dict(a,**{key:value}),None)['important']
    assert not evidence_research.changes(a,a,None)['important']
    assert evidence_research.facts({'seller_fields':{'seller_good_rate':'100.00%'}})==evidence_research.facts({'seller_fields':{'seller_good_rate':'100%'}})


def test_saved_new_facts_structured_reassessment_preserves_report_and_history(research):
    ids=seed(research);before=research.overview(research.task_id)
    changed(research,ids[0]);view=research.overview(research.task_id)
    item=view['evidence_work']['items'][0]
    assert item['state']=='priority' and '商品属性变化' in item['reason']
    assert view['coverage']['evaluated']==2
    job=research.enqueue(research.task_id,automatic=True)
    with research.db() as conn:
        row=conn.execute('SELECT * FROM studies WHERE id=?',(job,)).fetchone()
        request=json.loads(row['request_json'])
        assert row['kind']=='reassessment' and len(request['candidates'])==1
        assert 'research.assessments' in request['messages'][0]['content']
        assert 'previous' in request['messages'][0]['content'] and 'delta' in request['messages'][0]['content']
        assert request['phase']=='review_batch'
    assert research.execute_next()
    after=research.overview(research.task_id)
    assert after['coverage']['evaluated']==3 and after['report']==view['report']
    assert after['report']['id']==before['report']['id']
    assert after['integration_work']['state']=='none'
    assert research.enqueue(research.task_id,automatic=True) is None


@pytest.mark.parametrize('gate',['paused','unauthorized','completed'])
def test_policy_blocks_enqueue_and_claim_without_losing_changes(research,gate):
    ids=seed(research);changed(research,ids[0])
    if gate=='paused':
        research.control(research.task_id,'pause')
        with pytest.raises(ValueError):research.enqueue(research.task_id,automatic=True)
    else:
        with research.db() as conn:conn.execute('UPDATE projects SET '+('auto_research=0' if gate=='unauthorized' else 'completed=1'))
        if gate=='unauthorized':assert research.enqueue(research.task_id,automatic=True) is None
        else:
            with pytest.raises(ValueError):research.enqueue(research.task_id,automatic=True)
    view=research.overview(research.task_id)
    assert view['evidence_work']['gate']==gate and len(view['evidence_work']['items'])==1
    assert research.execute_next() is False


@pytest.mark.parametrize('mode',['summary','partial','image','exception'])
def test_invalid_reassessment_durable_attempt_no_automatic_loop(research,mode):
    ids=seed(research);changed(research,ids[0]);calls=[]
    def run(req,**kwargs):
        calls.append(req)
        if mode=='exception':raise RuntimeError('controlled failure')
        if mode=='summary':return AnswerResult(type='answer',content='Only text')
        result=structured(req)
        if mode=='partial':result.research.assessments=[]
        else:result.research.assessments[0].judgments[0].source_type='image_observation'
        return result
    research.runtime.run=run
    job=research.enqueue(research.task_id,automatic=True);research.execute_next()
    assert research.overview(research.task_id)['studies'][0]['state']=='failed'
    for _ in range(3):assert research.enqueue(research.task_id,automatic=True) is None
    reopened=ProjectResearch(research.config,research.runtime,research.monitors,clock=research.clock)
    assert reopened.enqueue(research.task_id,automatic=True) is None and len(calls)==1
    assert reopened.overview(research.task_id)['coverage']['evaluated']==2


def test_concurrent_triggers_and_restart_share_one_frozen_attempt(research):
    ids=seed(research);changed(research,ids[0])
    with ThreadPoolExecutor(3) as pool:
        jobs=list(pool.map(lambda _:research.enqueue(research.task_id,automatic=True),range(3)))
    assert len(set(jobs))==1 and jobs[0]
    reopened=ProjectResearch(research.config,research.runtime,research.monitors,clock=research.clock)
    assert reopened.enqueue(research.task_id,automatic=True)==jobs[0]
    with research.db() as conn:assert conn.execute("SELECT COUNT(*) FROM studies WHERE kind='reassessment'").fetchone()[0]==1


@pytest.mark.parametrize('when',['queued','running'])
@pytest.mark.parametrize('change',['evidence','goal'])
def test_stale_goal_or_evidence_never_becomes_current(research,when,change):
    ids=seed(research);changed(research,ids[0]);report=research.overview(research.task_id)['report']['id']
    job=research.enqueue(research.task_id,automatic=True)
    def mutate():
        if change=='evidence':save_detail(research,ids[0],'Seller now says a different repair history')
        else:research.save_goal(research.task_id,goal='Changed',budget=4000,hard=['new hard requirement'],soft=[],expected_revision=1,request_key='p2-goal-change',confirmed=True)
    if when=='queued':mutate()
    else:
        def run(req,**kwargs):mutate();return structured(req)
        research.runtime.run=run
    research.execute_next()
    with research.db() as conn:row=conn.execute('SELECT * FROM studies WHERE id=?',(job,)).fetchone();assert row['state']==('superseded' if when=='queued' else 'completed')
    view=research.overview(research.task_id)
    assert view['report']['id']==report
    assert view['coverage']['evaluated']<3


def test_coalescing_keeps_newest_evidence_and_existing_wait(research):
    ids=seed(research)
    moment=datetime.now(timezone.utc);research.clock=lambda:moment.isoformat()
    save_detail(research,ids[0]);v=research.overview(research.task_id)
    assert v['evidence_work']['gate']=='waiting'
    assert research.enqueue(research.task_id,automatic=True) is None
    save_detail(research,ids[0],'A second description before any model call')
    research.clock=lambda:(moment+timedelta(seconds=601)).isoformat()
    job=research.enqueue(research.task_id,automatic=True)
    with research.db() as conn:
        req=conn.execute('SELECT request_json FROM studies WHERE id=?',(job,)).fetchone()[0]
        assert 'A second description' in req


def test_meaningful_candidate_change_integrates_with_all_top_context(research):
    ids=seed(research);before=research.overview(research.task_id)['report']
    changed(research,ids[0],'Seller explicitly declares 16GB memory in the complete description')
    research.runtime.run=supported_improvement
    research.enqueue(research.task_id,automatic=True);research.execute_next()
    mid=research.overview(research.task_id)
    assert mid['report']['id']==before['id'] and mid['integration_work']['state']=='ready'
    job=research.enqueue(research.task_id,automatic=True)
    with research.db() as conn:
        row=conn.execute('SELECT * FROM studies WHERE id=?',(job,)).fetchone()
        assert row['kind']=='integration' and len(json.loads(row['versions_json']))==3
        assert before['content'] in row['request_json']
    research.execute_next()
    after=research.overview(research.task_id)
    assert after['report']['id']!=before['id'] and after['report']['evidence_current']
    assert len(json.loads(after['report']['candidate_ids_json']))==3


def test_timestamp_price_only_or_no_new_fact_does_not_spend_ai(research):
    ids=seed(research)
    # Current signature ignores observation time; same title/asking price yields
    # no revisit even after repeated ingest observations.
    with research.source_db() as conn:
        row=conn.execute('SELECT * FROM listing_snapshots WHERE listing_id=? ORDER BY id DESC LIMIT 1',(ids[0],)).fetchone()
        add_listing_snapshot(conn,ids[0],row['run_id'],title=row['title'],price_text='3010')
    view=research.overview(research.task_id)
    assert view['evidence_work']['items'][0]['state']=='not_needed'
    assert research.enqueue(research.task_id,automatic=True) is None


def test_post_read_item_changes_are_visible_without_rewriting_report(research):
    ids=seed(research);before=research.overview(research.task_id)
    research.mark_read(research.task_id,before['report']['id'])
    changed(research,ids[0]);research.enqueue(research.task_id,automatic=True);research.execute_next()
    view=research.overview(research.task_id)
    assert any(i['kind']=='evidence_reassessed' for i in view['changes'])
    research.mark_read(research.task_id,before['report']['id'])
    assert not research.overview(research.task_id)['changes']


def test_no_fact_detail_and_image_only_updates_do_not_trigger_ai(research):
    ids=seed(research)
    with research.source_db() as conn:
        row=conn.execute('SELECT * FROM listing_snapshots WHERE listing_id=? ORDER BY id DESC LIMIT 1',(ids[0],)).fetchone()
        missing=research.config.database_path.parent/'none.txt'
        add_detail_snapshot(conn,ids[0],row['run_id'],f'https://www.goofish.com/item?id={ids[0]}','No new facts',missing,missing,missing,missing,missing,0,0,False,attributes_json='{}')
    view=research.overview(research.task_id)
    assert view['evidence_work']['items'][0]['state']=='not_needed'
    assert research.enqueue(research.task_id,automatic=True) is None


def test_budget_crossing_is_selected_even_if_rule_would_exclude(research):
    ids=seed(research)
    with research.source_db() as conn:
        r=conn.execute('SELECT * FROM listing_snapshots WHERE listing_id=? ORDER BY id DESC LIMIT 1',(ids[0],)).fetchone()
        add_listing_snapshot(conn,ids[0],r['run_id'],title=r['title'],price_text='8000')
    research.overview(research.task_id)
    with research.db() as conn:conn.execute("UPDATE versions SET observed_at='2020-01-01T00:00:00+00:00'")
    view=research.overview(research.task_id)
    assert view['evidence_work']['items'][0]['delta']['budget_crossed']
    job=research.enqueue(research.task_id,automatic=True)
    assert job


def test_summary_only_nominations_can_gain_real_item_judgment(research):
    ids=[ingest(research) for _ in range(3)]
    research.enqueue(research.task_id);research.execute_next()
    changed(research,ids[0]);research.runtime.run=structured
    research.enqueue(research.task_id,automatic=True);research.execute_next()
    assert research.overview(research.task_id)['coverage']['evaluated']==1


@pytest.mark.parametrize('gate',['paused','unauthorized'])
def test_live_authorization_rechecked_after_enqueue(research,gate):
    ids=seed(research);changed(research,ids[0]);job=research.enqueue(research.task_id,automatic=True)
    with research.db() as conn:conn.execute('UPDATE projects SET '+('paused=1' if gate=='paused' else 'auto_research=0'))
    assert research.execute_next() is False
    with research.db() as conn:assert conn.execute('SELECT state FROM studies WHERE id=?',(job,)).fetchone()[0]=='queued'


def test_automatic_failed_restart_is_a_durable_attempt(research,monkeypatch):
    ids=seed(research);changed(research,ids[0]);job=research.enqueue(research.task_id,automatic=True)
    with research.db() as conn:conn.execute("UPDATE studies SET state='running' WHERE id=?",(job,))
    class NoThread:
        def __init__(self,*a,**kw):pass
        def start(self):pass
        def join(self,*a,**kw):pass
        def is_alive(self):return False
    monkeypatch.setattr('shopping_agent.project_research.threading.Thread',NoThread)
    reopened=ProjectResearch(research.config,research.runtime,research.monitors,clock=research.clock)
    reopened.start();reopened.shutdown()
    with reopened.db() as conn:assert conn.execute('SELECT state FROM studies WHERE id=?',(job,)).fetchone()[0]=='failed'
    assert reopened.enqueue(research.task_id,automatic=True) is None


def test_report_publish_checks_evidence_for_ordinary_runs_too(research):
    ids=seed(research);old=research.overview(research.task_id)['report']['id']
    # An existing normal incremental can be in flight as evidence changes.
    with research.db() as conn:
        original=conn.execute("SELECT * FROM studies WHERE kind='initial' LIMIT 1").fetchone()
        inserted=conn.execute("INSERT INTO studies(task_id,kind,state,request_json,versions_json,snapshot_at,created_at,request_key) VALUES(?,'incremental','queued',?,?,?,?,?)",(research.task_id,original['request_json'],original['versions_json'],original['snapshot_at'],research.clock(),'old-incremental'))
        conn.execute('INSERT INTO study_goal_bindings VALUES(?,?,1,?)',(inserted.lastrowid,research.task_id,'automatic_snapshot'))
    def run(req,**kw):save_detail(research,ids[0]);return structured(req)
    research.runtime.run=run;research.execute_next()
    assert research.overview(research.task_id)['report']['id']==old
    assert len(research.report_history(research.task_id)['items'])==2


@pytest.mark.parametrize('mode',['failure','stale'])
def test_integration_failure_or_stale_evidence_never_publishes(research,mode):
    ids=seed(research);old=research.overview(research.task_id)['report']['id'];changed(research,ids[0],'Seller explicitly declares 16GB memory in the complete description')
    positive=supported_improvement
    research.runtime.run=positive;research.enqueue(research.task_id,automatic=True);research.execute_next()
    job=research.enqueue(research.task_id,automatic=True);assert job
    def bad(req,**kw):
        if mode=='failure':return AnswerResult(type='answer',content='Summary only')
        save_detail(research,ids[0],'Again different evidence during integration')
        return positive(req)
    research.runtime.run=bad;research.execute_next()
    assert research.overview(research.task_id)['report']['id']==old
    if mode=='failure':
        assert research.overview(research.task_id)['integration_work']['state']=='failed'
        assert research.enqueue(research.task_id,automatic=True) is None


def test_independent_projects_do_not_share_reassessment_attempts(research):
    ids=seed(research);changed(research,ids[0]);research.enqueue(research.task_id,automatic=True)
    other=research.create('Other','A different selection',None,[],[],2,True)['id']
    view=research.overview(other)
    assert view['evidence_work']['items']==[] and research.enqueue(other,automatic=True) is None


def test_resuming_backlog_does_not_drain_many_batches_immediately(research):
    ids=seed(research)
    for i in ids:changed(research,i)
    with research.db() as conn:conn.execute('UPDATE projects SET batch_size=1')
    job=research.enqueue(research.task_id,automatic=True);research.execute_next()
    view=research.overview(research.task_id)
    assert view['evidence_work']['gate']=='waiting' and '历史积压' in view['evidence_work']['reason']
    assert research.enqueue(research.task_id,automatic=True) is None
    research.clock=lambda:(datetime.now(timezone.utc)+timedelta(seconds=1602)).isoformat()
    assert research.enqueue(research.task_id,automatic=True)!=job


def test_unexecuted_snapshot_can_coalesce_without_duplicate_spend(research):
    ids=seed(research);changed(research,ids[0])
    old=research.enqueue(research.task_id,automatic=True)
    # Identical facts, newer detail ID: replace only an unexecuted frozen input.
    save_detail(research,ids[0]);assert research.execute_next() is False
    new=research.enqueue(research.task_id,automatic=True)
    assert new and new!=old
    research.execute_next()
    assert research.overview(research.task_id)['coverage']['evaluated']==3
