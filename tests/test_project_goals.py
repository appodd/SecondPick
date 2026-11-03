"""Goal version compatibility tests use temporary databases and a controlled runtime."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_project_research import research, ingest, consume_summary_followup, Runtime
from shopping_agent.project_research import ProjectResearch
from shopping_agent.project_goals import GoalConflict

def change(store, revision=1, goal='MacBook Pro，至少16GB，预算5000，优先M系列', key=None):
    return store.save_goal(store.task_id,goal=goal,budget=5000,hard=['内存至少16GB'],soft=['优先M系列'],
        expected_revision=revision,request_key=key or f'goal-update-{revision}',confirmed=True)

def test_running_old_goal_finishes_as_history_and_cannot_publish_current(research):
    item=ingest(research)
    old=research.enqueue(research.task_id)
    with research.db() as conn:
        frozen=conn.execute('SELECT request_json FROM studies WHERE id=?',(old,)).fetchone()[0]
    research.runtime.callback=lambda:change(research)
    assert research.execute_next()
    view=research.overview(research.task_id)
    assert view['goal_context']['current_revision']==2
    assert view['goal_context']['report_current'] is False
    assert view['goal_context']['calibration']=='pending'
    assert view['report']['goal_revision']==1
    assert view['studies'][0]['state']=='completed'
    assert view['studies'][0]['goal_revision']==1
    with research.db() as conn:
        assert conn.execute('SELECT request_json FROM studies WHERE id=?',(old,)).fetchone()[0]==frozen
        assert conn.execute('SELECT COUNT(*) FROM reports').fetchone()[0]==1
    assert research.enqueue(research.task_id,automatic=True) is None
    research.runtime.callback=None
    new=research.enqueue(research.task_id)
    assert new!=old
    assert research.execute_next()
    view=research.overview(research.task_id)
    assert view['goal_context']['report_current'] and view['report']['goal_revision']==2
    assert view['report']['study_id']==new
    assert len(research.report_history(research.task_id)['items'])==2
    assert '预算5000' in research.runtime.requests[-1]
    assert '预算上限（元，挂牌价）: 5000' in research.runtime.requests[-1]

def test_old_retry_finishing_after_new_report_never_replaces_new_report(research):
    ingest(research)
    old=research.enqueue(research.task_id)
    research.runtime.fail=True; research.execute_next()
    change(research)
    research.runtime.fail=False
    ingest(research)  # Existing unchanged enqueue logic can publish from a newly saved sample.
    new=research.enqueue(research.task_id); research.execute_next()
    new_report=research.overview(research.task_id)['report']['id']
    research.retry(research.task_id,old); research.execute_next()
    view=research.overview(research.task_id)
    assert view['report']['id']==new_report and view['report']['study_id']==new
    assert research.report_history(research.task_id)['items'][0]['is_current_goal'] is False

def test_continuous_updates_and_queued_run_keep_their_goal_snapshots(research):
    ingest(research)
    old=research.enqueue(research.task_id)
    change(research)
    new=research.enqueue(research.task_id,ids=[research.cards(research.task_id)[0]["listing_id"]])
    assert new!=old
    change(research,2,goal='MacBook Pro，预算4500')
    research.execute_next(); research.execute_next()
    view=research.overview(research.task_id)
    assert view['goal_context']['current_revision']==3 and not view['goal_context']['report_current']
    assert {s['goal_revision'] for s in view['studies']}=={1,2}
    assert len(research.runtime.requests)==2
    assert research.enqueue(research.task_id,automatic=True) is None

def test_concurrent_confirmations_idempotency_and_noop(research):
    research.goal(research.task_id)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:change(research),range(2)))
    assert results[0]==results[1]==dict(revision=2,saved=True)
    with pytest.raises(GoalConflict):
        change(research,key='different-old-basis')
    with pytest.raises(GoalConflict):
        change(research,goal='different request payload')
    assert change(research,2,key='no-op-confirm')['revision']==2
    with pytest.raises(ValueError,match='确认'):
        research.save_goal(research.task_id,goal='new',budget=None,hard=[],soft=[],expected_revision=2,request_key='bad-confirm',confirmed=False)

def test_goal_change_during_snapshot_construction_rejects_mixed_input(research,monkeypatch):
    ingest(research)
    original=research._request
    def build(*args,**kwargs):
        result=original(*args,**kwargs)
        change(research)
        return result
    monkeypatch.setattr(research,'_request',build)
    with pytest.raises(GoalConflict,match='快照'):
        research.enqueue(research.task_id)
    assert research.overview(research.task_id)['studies']==[]

def test_restored_old_database_binds_only_matching_request_and_preserves_data(research):
    item=ingest(research); research.favorite(research.task_id,item,True)
    study=research.enqueue(research.task_id); research.execute_next()
    with research.db() as conn:
        conn.execute('DROP TABLE study_goal_bindings')
        conn.execute('DROP TABLE project_goal_revisions')
    reopened=ProjectResearch(research.config,research.runtime,research.monitors)
    view=reopened.overview(research.task_id)
    assert view['goal_context']['current_revision']==1 and view['goal_context']['report_current']
    assert view['favorites']==[item] and view['total']==1
    with reopened.db() as conn:
        frozen=json.loads(conn.execute('SELECT request_json FROM studies WHERE id=?',(study,)).fetchone()[0])
        frozen['task']['effective_goal']='unverifiable historic goal'
        conn.execute('UPDATE studies SET request_json=? WHERE id=?',(json.dumps(frozen),study))
        conn.execute('DELETE FROM study_goal_bindings')
    view=reopened.overview(research.task_id)
    assert not view['goal_context']['report_current'] and view['report']['goal_revision'] is None
    assert reopened.enqueue(research.task_id,automatic=True) is None
    from shopping_agent.project_goals import prompt_goal
    with reopened.db() as conn:
        frozen['task']['effective_goal']=prompt_goal(reopened._stored_policy(research.task_id) | {'goal':reopened.require(research.task_id)['goal']},legacy=True)
        conn.execute('UPDATE studies SET request_json=? WHERE id=?',(json.dumps(frozen),study))
        conn.execute('DELETE FROM study_goal_bindings')
    assert reopened.overview(research.task_id)['report']['goal_revision'] is None  # Legacy text omitted a non-null budget.

def test_restart_preserves_goal_and_original_retry_snapshot(research):
    ingest(research); study=research.enqueue(research.task_id)
    with research.db() as conn:
        frozen=conn.execute('SELECT request_json FROM studies WHERE id=?',(study,)).fetchone()[0]
        conn.execute("UPDATE studies SET state='running' WHERE id=?",(study,))
    change(research)
    reopened=ProjectResearch(research.config,research.runtime,research.monitors)
    # Pause the original worker during recovery, as a real paused project would be.
    reopened.control(research.task_id,'pause'); reopened.start(); reopened.shutdown()
    view=reopened.overview(research.task_id)
    assert view['goal_context']['current_revision']==2 and view['studies'][0]['state']=='failed'
    with reopened.db() as conn:
        assert conn.execute('SELECT request_json FROM studies WHERE id=?',(study,)).fetchone()[0]==frozen
    reopened.retry(research.task_id,study); reopened.control(research.task_id,'resume'); reopened.execute_next()
    assert not reopened.overview(research.task_id)['goal_context']['report_current']

def test_current_goal_coverage_does_not_inherit_old_runs_or_old_budget_exclusions(research):
    cheap=ingest(research,price='4000')
    expensive=ingest(research,price='8000')
    old=research.enqueue(research.task_id)
    change(research)
    view=research.overview(research.task_id)
    assert view['coverage']['under_ai']==0  # Old goal queued is not new goal work.
    assert view['coverage']['rule_excluded']==1
    research.execute_next()
    view=research.overview(research.task_id)
    assert view['coverage']['summarized']==0 and view['coverage_history']['reusable_evidence']==1
    # Increasing budget reconsiders existing saved products, no collection or AI call.
    research.save_goal(research.task_id,goal='预算9000',budget=9000,hard=[],soft=[],expected_revision=2,request_key='increase-budget',confirmed=True)
    view=research.overview(research.task_id)
    assert view['coverage']['rule_excluded']==0 and view['coverage']['waiting']==2
    assert len(research.runtime.requests)==1
    new=research.enqueue(research.task_id)
    research.execute_next()
    assert set(research.overview(research.task_id)['studies'][0]['listing_ids'])=={cheap,expensive}
    consume_summary_followup(research)  # Report membership alone is not item completion.

def test_failed_old_version_does_not_block_current_goal_manual_evaluation(research):
    ingest(research)
    research.enqueue(research.task_id); research.runtime.fail=True; research.execute_next()
    change(research); research.runtime.fail=False
    assert research.overview(research.task_id)['coverage']['blocked']==0
    research.enqueue(research.task_id); research.execute_next()
    assert research.overview(research.task_id)['goal_context']['report_current']

def test_goal_route_requires_confirmation_and_version_and_keeps_original_and_monitors(tmp_path):
    from fastapi.testclient import TestClient
    from shopping_agent.web.app import create_app
    path=tmp_path/'config.toml'
    path.write_text(f'database_path="{(tmp_path/"app.sqlite").as_posix()}"\n',encoding='utf-8')
    app=create_app(path,tmp_path/'settings.json')
    with TestClient(app,base_url='http://127.0.0.1') as client:
        task=client.post('/api/projects',json=dict(title='NS2 Pro手柄',goal='找二手NS2 Pro手柄',hard=[],soft=[])).json()['id']
        payload=dict(goal='原装NS2 Pro手柄',budget=350,hard=['按键正常'],soft=['优先自提'],expected_revision=1,request_key='confirm-controller',confirmed=True)
        assert client.patch(f'/api/projects/{task}/goal',json={**payload,'confirmed':1}).status_code==422
        assert client.patch(f'/api/projects/{task}/goal',json=payload).json()['revision']==2
        assert client.patch(f'/api/projects/{task}/goal',json=payload).json()['revision']==2
        assert client.patch(f'/api/projects/{task}/goal',json={**payload,'request_key':'another-request'}).status_code==409
        assert client.post(f'/api/projects/{task}/studies',json=dict(request_key='study-stale',expected_goal_revision=1)).status_code==409
        view=client.get(f'/api/projects/{task}/overview').json()
        assert view['project']['goal']=='原装NS2 Pro手柄'
        assert view['goal_context']['original_goal']=='找二手NS2 Pro手柄'
        assert view['policy']['hard']==['按键正常'] and view['policy']['auto_research']==0
        assert client.get(f'/api/projects/{task}/reports').json()['items']==[]
        assert client.get(f'/api/tasks/{task}/monitors').json()['items']==[]
        assert client.get(f'/api/projects/{task}/reports?limit=0').status_code==422
        assert client.patch('/api/projects/999999/goal',json=payload).status_code==404

def test_goal_confirmation_keeps_paused_research_and_existing_monitor_unchanged(research):
    item=ingest(research); research.favorite(research.task_id,item,True)
    monitor=research.create_window(research.task_id,'原监控','ongoing',60,dict(keyword='MacBook',max_pages=1,max_items=5,interval_seconds=600,collect_seller_profiles=False))
    before=research.monitors.list(research.task_id)
    research.control(research.task_id,'pause'); change(research)
    view=research.overview(research.task_id)
    assert view['policy']['paused']==1 and view['policy']['auto_research']==1
    assert view['favorites']==[item] and view['total']==1
    assert research.monitors.list(research.task_id)==before
    with pytest.raises(ValueError,match='暂停'):
        research.enqueue(research.task_id,automatic=True)

def test_manual_calibration_does_not_unleash_automatic_research_on_all_old_inventory(research):
    from datetime import datetime, timedelta, timezone
    moment=datetime(2026,10,23,tzinfo=timezone.utc)
    research.clock=lambda:moment.isoformat()
    old={ingest(research,price='4000') for _ in range(25)}
    research.overview(research.task_id)
    research.clock=lambda:(moment+timedelta(seconds=1)).isoformat()
    change(research)
    research.enqueue(research.task_id); research.execute_next()
    view=research.overview(research.task_id)
    assert view['goal_context']['report_current']
    assert view['coverage']['waiting']==5
    consume_summary_followup(research)
    assert len(research.runtime.requests)==2
    # Ten new semantic samples still follow the original incremental threshold.
    research.clock=lambda:(moment+timedelta(seconds=2)).isoformat()
    new={ingest(research,price='4000') for _ in range(10)}
    run=research.enqueue(research.task_id,automatic=True)
    assert run is not None
    request=research.overview(research.task_id)['studies'][0]['listing_ids']
    assert new <= set(request)
    assert len(set(request)-new)<=3  # Only already-current report candidates, no uncalibrated old backlog.

def test_real_per_item_assessments_are_counted_by_goal_and_history_is_not_double_counted(research):
    from shopping_agent.codex_runtime import AnswerResult
    item=ingest(research,price='4000')
    calls=[]
    def run(request,**kwargs):
        calls.append(request)
        return AnswerResult.model_validate(dict(type='answer',content='保存的逐项结论，配置仍有待核实',candidate_ids=[item],research=dict(
            criteria=[dict(criterion_id='memory',description='内存条件',priority='hard',source_refs=['task_goal'],source_message_ids=[])],
            assessments=[dict(listing_id=item,conclusion='insufficient_evidence',summary='缺少配置凭证',judgments=[dict(criterion_id='memory',status='UNKNOWN',source_type='missing',reason='未提供内存凭证',evidence_refs=[])])])) )
    research.runtime.run=run
    research.enqueue(research.task_id); research.execute_next()
    assert research.overview(research.task_id)['coverage']['evaluated']==1
    change(research)
    view=research.overview(research.task_id)
    assert view['coverage']['evaluated']==0 and view['coverage_history']['evaluated']==1
    research.enqueue(research.task_id); research.execute_next()
    view=research.overview(research.task_id)
    assert view['coverage']['evaluated']==1 and view['coverage_history']['evaluated']==1
    assert view['coverage']['summarized']==0 and len(calls)==2
    assert research.enqueue(research.task_id,automatic=True) is None
