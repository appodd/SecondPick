"""Isolated integration tests; seeded listings and model double are not live acceptance."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from shopping_agent.config import AppConfig
from shopping_agent.codex_runtime import CodexRuntime, AnswerResult
from shopping_agent.db import connect, create_search_run, attach_run_to_task, upsert_listing, add_listing_snapshot
from shopping_agent.monitoring import MonitorStore
from shopping_agent.project_research import ProjectResearch
from shopping_agent.web.app import create_app


class Runtime(CodexRuntime):
    def __init__(self):
        self.fail = False
        self.callback = None
        self.requests = []

    def run(self, request, *, run_id, **kwargs):
        assert run_id > 0
        self.requests.append(request.model_dump_json())
        if self.callback:
            self.callback()
        if self.fail:
            raise RuntimeError('model unavailable')
        return AnswerResult(type='answer', content='测试模型结果：报价仅为挂牌观察；电池和维修未知。', candidate_ids=sorted(request.allowed_listing_ids)[:3])

    def cancel(self, run_id):
        pass


@pytest.fixture
def research(tmp_path):
    config = AppConfig(database_path=tmp_path/'test.sqlite')
    monitors = MonitorStore(config)
    value = ProjectResearch(config, Runtime(), monitors)
    value.task_id = value.create('电脑','买电脑',7000,['内存至少16GB'],['优先个人闲置'],2,True)['id']
    return value


def ingest(research, *, price='5000', title='MacBook M3 16GB', url=None):
    with connect(research.config.database_path) as conn:
        run = create_search_run(conn, '电脑', '上海')
        attach_run_to_task(conn, research.task_id, run)
        listing = upsert_listing(conn,'xianyu',url or f'https://www.goofish.com/item?id={run}')
        add_listing_snapshot(conn,listing,run,title=title,price_text=price)
    return listing


def test_empty_project_does_not_create_chat_or_collect(research):
    result=research.overview(research.task_id)
    assert result['total']==0 and result['report'] is None
    assert result['phase']=='collecting_baseline'
    with connect(research.config.database_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM operations').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM monitors').fetchone()[0]==0


def test_region_metadata_and_frozen_research_requests_do_not_inherit_system_city(research):
    task = research.task_id
    assert research.require(task)['city'] == ''
    with research.source_db() as conn:
        conn.execute("UPDATE research_tasks SET city='上海' WHERE id=?", (task,))
    original_policy = research.policy(task)
    overview = research.overview(task)
    assert overview['region_preference']['mode'] == 'none'
    assert overview['region_preference']['legacy_unverified'] is True
    assert research.require(task)['city'] == '上海'
    request = research._request(task, [], '研究已有商品').model_dump_json()
    assert '不设置地区偏好' in request
    assert research.policy(task) == original_policy
    with research.source_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM monitors').fetchone()[0] == 0
    for goal, mode in [('买手柄，上海优先', 'preferred'), ('买手柄，只考虑上海自提', 'restricted')]:
        created = research.create('手柄', goal, None, [], [], 2, False)['id']
        assert research.overview(created)['region_preference']['mode'] == mode
        assert ('软偏好' if mode == 'preferred' else '硬条件') in research._request(created, [], '研究').model_dump_json()


def test_initial_concurrency_and_ingestion_during_frozen_run(research):
    first=ingest(research)
    assert research.enqueue(research.task_id, automatic=True) is None
    second=ingest(research)
    with ThreadPoolExecutor(2) as pool:
        ids=list(pool.map(lambda _:research.enqueue(research.task_id,automatic=True),range(2)))
    assert ids[0]==ids[1]
    with research.db() as conn:
        frozen=conn.execute('SELECT request_json FROM studies').fetchone()[0]
    third=[]
    research.runtime.callback=lambda: third.append(ingest(research))
    assert research.execute_next()
    with research.db() as conn:
        assert conn.execute('SELECT request_json FROM studies WHERE id=?',(ids[0],)).fetchone()[0]==frozen
    result=research.overview(research.task_id)
    assert result['total']==3 and result['coverage']['summarized']==2 and result['coverage']['evaluated']==0 and result['pending']==1
    assert set(result['studies'][0]['listing_ids'])=={first,second}
    assert sum(result['coverage'].values())==3
    research.runtime.callback=None
    assert research.enqueue(research.task_id,ids=third,request_key='selection-123')
    assert research.execute_next()
    assert research.overview(research.task_id)['studies'][0]['listing_ids']==third


def test_failure_retry_keeps_snapshot_and_favorites(research):
    first=ingest(research)
    research.favorite(research.task_id,first,True)
    study=research.enqueue(research.task_id,request_key='initial-123')
    research.runtime.fail=True
    research.execute_next()
    assert research.overview(research.task_id)['report'] is None
    ingest(research)
    research.retry(research.task_id,study)
    research.runtime.fail=False
    research.execute_next()
    result=research.overview(research.task_id)
    assert result['favorites']==[first]
    assert result['studies'][0]['listing_ids']==[first]
    assert result['pending']==1


def test_rule_unknown_and_cross_project_boundaries(research):
    expensive=ingest(research,price='8000')
    unknown=ingest(research,price=None)
    result=research.overview(research.task_id)
    assert result['coverage']['rule_excluded']==1
    assert result['coverage']['needs_information']==1
    assert result['eligible']==0
    other=research.create('其他','相机',None,[],[],2,False)['id']
    with pytest.raises(ValueError):
        research.enqueue(other,ids=[expensive])
    with pytest.raises(ValueError):
        research.favorite(other,unknown,True)


def test_read_cursor_is_persistent_and_monotonic(research):
    ingest(research)
    research.enqueue(research.task_id)
    research.execute_next()
    before=research.overview(research.task_id)
    report=before['report']['id']
    assert before['changes']
    research.mark_read(research.task_id,report)
    reopened=ProjectResearch(research.config,research.runtime,research.monitors)
    assert reopened.overview(research.task_id)['changes']==[]
    other=reopened.create('另一个','相机',None,[],[],2,False)['id']
    with pytest.raises(ValueError):
        reopened.mark_read(other,report)


def test_timed_window_deadline_stops_dispatch_and_rerun_reuses_monitor(research):
    start=datetime(2026,10,21,tzinfo=timezone.utc)
    research.clock=lambda:start.isoformat()
    research.monitors.clock=lambda:start
    research.monitors.window_guard=research.settle_windows
    created=research.create_window(research.task_id,'限时电脑','timed',60,dict(keyword='MacBook',max_pages=1,max_items=5,interval_seconds=60,collect_seller_profiles=False))
    monitor_id=created['monitor_id']
    research.clock=lambda:(start+timedelta(seconds=61)).isoformat()
    research.monitors.clock=lambda:start+timedelta(seconds=61)
    assert research.monitors.claim_due() is None
    window=research.windows(research.task_id)['items'][0]
    assert window['runs'][0]['state']=='expired'
    assert window['runs'][0]['deadline_at']==(start+timedelta(seconds=60)).isoformat()
    research.rerun_window(research.task_id,monitor_id)
    assert len(research.windows(research.task_id)['items'][0]['runs'])==2
    assert len(research.monitors.list(research.task_id))==1


def test_exhausted_paused_once_can_rerun_without_losing_history(research):
    listing = ingest(research)
    scope = dict(keyword='MacBook',max_pages=1,max_items=5,interval_seconds=60,collect_seller_profiles=False)
    mid = research.create_window(research.task_id,'once','once',None,scope)['monitor_id']
    with research.source_db() as conn:
        conn.execute("UPDATE monitors SET state='paused',rounds=max_rounds,error_code='cancelled' WHERE id=?", (mid,))
    research.settle_windows()
    old = research.windows(research.task_id)['items'][0]['runs'][0]
    research.rerun_window(research.task_id,mid)
    window = research.windows(research.task_id)['items'][0]
    assert len(window['runs']) == 2
    assert window['runs'][0]['state'] == 'running'
    assert window['runs'][0]['config']['max_items'] == 5
    assert window['runs'][1]['id'] == old['id']
    assert window['runs'][1]['state'] == 'stopped'
    assert window['runs'][1]['error'] == 'cancelled'
    assert window['monitor']['max_rounds'] == window['monitor']['rounds'] + 1
    assert len(research.monitors.list(research.task_id)) == 1
    with research.source_db() as conn:
        assert conn.execute('SELECT id FROM listings WHERE id=?',(listing,)).fetchone()
    with pytest.raises(ValueError):
        research.rerun_window(research.task_id,mid)


@pytest.mark.parametrize('state,rounds,desired', [('paused',0,None),('running',1,None),('paused',1,'paused')])
def test_once_rerun_rejects_unfinished_or_exiting_scope(research,state,rounds,desired):
    mid = research.create_window(research.task_id,'once','once',None,dict(keyword='MacBook',max_pages=1,max_items=5,interval_seconds=60,collect_seller_profiles=False))['monitor_id']
    with research.source_db() as conn:
        conn.execute('UPDATE monitors SET state=?,rounds=?,desired_state=? WHERE id=?',(state,rounds,desired,mid))
    with pytest.raises(ValueError):
        research.rerun_window(research.task_id,mid)
    with research.db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM window_runs WHERE monitor_id=?',(mid,)).fetchone()[0] == 1


def test_goal_history_keeps_previous_versions_and_is_project_scoped(research):
    old = research.goal(research.task_id)
    research.save_goal(research.task_id,goal='MacBook Pro M2',budget=6000,hard=['32GB'],soft=['上海优先'],expected_revision=old['revision'],request_key='history-test',confirmed=True)
    history = research.goal_history(research.task_id)
    assert [r['revision'] for r in history['items']] == [2,1]
    assert history['items'][0]['hard'] == ['32GB']
    assert history['items'][1]['goal'] == old['goal']
    assert history['has_more'] is False
    assert research.goal_history(research.task_id) == history
    other = research.create('other','相机',None,[],[],2,False)['id']
    assert len(research.goal_history(other)['items']) == 1
    with pytest.raises(ValueError):
        research.goal_history(999999)


def test_pause_research_does_not_pause_collection(research):
    created=research.create_window(research.task_id,'单次','once',60,dict(keyword='MacBook',max_pages=1,max_items=5,interval_seconds=60,collect_seller_profiles=False))
    research.control(research.task_id,'pause')
    assert research.monitors.list(research.task_id)[0]['state']=='waiting'
    research.control(research.task_id,'complete_pause')
    assert research.monitors.list(research.task_id)[0]['state']=='paused'


def test_project_routes_use_real_store_and_require_confirmation(tmp_path):
    config=tmp_path/'config.toml'
    config.write_text(f'database_path="{(tmp_path/"app.sqlite").as_posix()}"\n',encoding='utf-8')
    app=create_app(config,tmp_path/'settings.json')
    app.state.codex_runtime=Runtime()
    with TestClient(app,base_url='http://127.0.0.1') as client:
        created=client.post('/api/projects',json=dict(title='相机',goal='买相机',hard=[],soft=[]))
        assert created.status_code==201
        task_id=created.json()['id']
        empty=client.get(f'/api/projects/{task_id}/overview')
        assert empty.status_code==200 and empty.json()['cards']==[]
        history=client.get(f'/api/projects/{task_id}/goal/history')
        assert history.status_code==200 and history.json()['items'][0]['goal']=='买相机'
        assert history.json()['has_more'] is False
        invalid=client.post(f'/api/projects/{task_id}/monitors',json=dict(name='相机',keyword='索尼',mode='timed',confirmed=1))
        assert invalid.status_code==422
        assert client.post(f'/api/projects/{task_id}/studies',json={'ids':[999],'request_key':'scope-test'}).status_code==400
        assert client.get('/api/projects/999/overview').status_code==404


def test_project_and_window_creation_idempotency_and_distinct_modes(research):
    args=('相机','买相机',None,[],[],2,False)
    first=research.create(*args,request_key='project-creation-123')
    assert research.create(*args,request_key='project-creation-123')==first
    scope=dict(keyword='MacBook',max_pages=1,max_items=5,interval_seconds=60,collect_seller_profiles=False)
    first=research.create_window(research.task_id,'限时','timed',60,scope,'window-key-123')
    again=research.create_window(research.task_id,'限时','timed',60,scope,'window-key-123')
    ongoing=research.create_window(research.task_id,'长期','ongoing',60,scope,'window-key-456')
    assert first['monitor_id']==again['monitor_id']
    assert first['monitor_id']!=ongoing['monitor_id']


def test_persistent_edit_requires_pause_and_version_and_preserves_history(research):
    scope=dict(keyword='MacBook',max_pages=1,max_items=5,interval_seconds=60,collect_seller_profiles=False)
    created=research.create_window(research.task_id,'限时','timed',60,scope)
    mid=created['monitor_id']
    draft={**scope,'keyword':'MacBook 16GB','name':'内存搜索','mode':'ongoing','duration_seconds':60}
    with pytest.raises(ValueError,match='暂停'):
        research.edit_window(research.task_id,mid,draft,0)
    research.monitors.control(research.task_id,mid,'pause')
    result=research.edit_window(research.task_id,mid,draft,0)
    assert result['started'] is False
    monitor=research.windows(research.task_id)['items'][0]
    assert monitor['monitor']['keyword']=='MacBook 16GB' and monitor['revision']>0
    assert monitor['runs'][0]['state']=='stopped'
    with pytest.raises(ValueError,match='已变化'):
        research.edit_window(research.task_id,mid,draft,0)
    research.rerun_window(research.task_id,mid)
    assert len(research.windows(research.task_id)['items'][0]['runs'])==2


def test_repeated_discovery_is_not_new_evidence_but_detail_revision_is(research):
    from shopping_agent.db import add_detail_snapshot
    listing=ingest(research,url='https://www.goofish.com/item?id=one')
    research.enqueue(research.task_id)
    research.execute_next()
    ingest(research,url='https://www.goofish.com/item?id=one')
    assert research.overview(research.task_id)['pending']==0
    consume_summary_followup(research)
    with connect(research.config.database_path) as conn:
        run=conn.execute('SELECT run_id FROM task_runs WHERE task_id=? ORDER BY run_id DESC',(research.task_id,)).fetchone()[0]
        add_detail_snapshot(conn,listing_id=listing,run_id=run,url='https://www.goofish.com/item?id=one',title='新增详情',
            screenshot_path=None,html_path=None,text_path=None,links_path=None,images_path=None,link_count=0,image_count=0,access_blocked=False)
    assert research.overview(research.task_id)['pending']==1


def test_selected_scope_queues_independently_from_existing_run(research):
    first=ingest(research)
    second=ingest(research)
    one=research.enqueue(research.task_id,ids=[first],request_key='first-selection')
    two=research.enqueue(research.task_id,ids=[second],request_key='second-selection')
    assert one!=two
    queued=research.overview(research.task_id)['studies']
    assert queued[0]['listing_ids']==[second] and queued[1]['listing_ids']==[first]
    assert all(s['state']=='queued' for s in queued)


def test_incremental_report_keeps_prior_basis_and_favorites(research):
    first=ingest(research)
    research.enqueue(research.task_id)
    research.execute_next()
    research.favorite(research.task_id,first,True)
    second=ingest(research)
    research.enqueue(research.task_id)
    research.execute_next()
    result=research.overview(research.task_id)
    assert result['pending']==0
    assert result['favorites']==[first]
    assert '此前有效报告' in research.runtime.requests[-1]
    assert {first,second} <= set(result['studies'][0]['listing_ids'])


def test_ai_drafts_are_editable_payloads_without_creation_side_effects(tmp_path):
    config=tmp_path/'config.toml'
    config.write_text(f'database_path="{(tmp_path/"app.sqlite").as_posix()}"\n',encoding='utf-8')
    app=create_app(config,tmp_path/'settings.json')
    runtime=Runtime()
    def run(query,**kwargs):
        if 'name,keyword,mode' in query.messages[-1].content:
            content=dict(name='电脑监控',keyword='MacBook',mode='timed',duration_seconds=1800,interval_seconds=600,max_pages=3,max_items=50,collect_seller_profiles=False)
        else:
            content=dict(title='电脑',goal='预算内找电脑',budget=7000,hard=['16GB'],soft=['个人闲置'])
        return AnswerResult(type='answer',content=json.dumps(content),candidate_ids=[])
    runtime.run=run
    app.state.codex_runtime=runtime
    with TestClient(app,base_url='http://127.0.0.1') as client:
        draft=client.post('/api/project-goal-drafts',json=dict(goal='预算7000，至少16GB，最好个人闲置'))
        assert draft.status_code==200
        assert client.get('/api/tasks').json()['total_count']==0
        created=client.post('/api/projects',json=draft.json())
        assert created.status_code==201
        task_id=created.json()['id']
        plan=client.post(f'/api/projects/{task_id}/monitor-drafts',json=dict(goal='监控MacBook30分钟'))
        assert plan.status_code==200 and plan.json()['duration_seconds']==1800
        assert client.get(f'/api/tasks/{task_id}/monitors').json()['items']==[]


def test_ongoing_window_continues_while_legacy_quota_is_unchanged(research):
    scope=dict(keyword='MacBook',max_pages=1,max_items=5,interval_seconds=60,collect_seller_profiles=False)
    created=research.create_window(research.task_id,'长期','ongoing',60,scope)
    mid=created['monitor_id']
    research.monitors.continue_window=research.continue_window
    with connect(research.config.database_path) as conn:
        conn.execute('UPDATE monitors SET max_rounds=1 WHERE id=?',(mid,))
    assert research.monitors.claim_due()['id']==mid
    research.monitors.finish(mid,dict(imported=0,error_code=None))
    monitor=research.monitors.list(research.task_id)[0]
    assert monitor['state']=='waiting' and monitor['rounds']==1
    legacy=research.monitors.create(research.task_id,keyword='Legacy',max_rounds=1,confirmed=True)
    with connect(research.config.database_path) as conn:
        conn.execute("UPDATE monitors SET state='running' WHERE id=?",(legacy['id'],))
    research.monitors.finish(legacy['id'],dict(imported=0,error_code=None))
    assert next(m for m in research.monitors.list(research.task_id) if m['id']==legacy['id'])['state']=='stopped'


def test_seller_study_is_on_demand_shared_and_does_not_publish_project_report(research,tmp_path):
    from shopping_agent.goofish_import import import_goofish_jsonl
    records=[]
    for i in (101,102):
        records.append({'任务名称':'seller-fixture','搜索关键字':'MacBook','爬取时间':'2026-10-21T10:00:00+00:00',
            '商品信息':{'商品ID':str(i),'商品链接':f'https://www.goofish.com/item?id={i}','商品标题':'MacBook Pro M3 16GB','当前售价':'5000'},
            '卖家信息':{'卖家ID':'778899','卖家芝麻信用':'极好','卖家昵称':'同一卖家'}})
    path=tmp_path/'seller-source.jsonl'
    path.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in records)+'\n',encoding='utf-8')
    import_goofish_jsonl(research.config,path=path,task_id=research.task_id,keyword='MacBook',source_task='seller-fixture')
    cards=research.cards(research.task_id)
    first,second=[c['listing_id'] for c in cards]
    assert research.seller(research.task_id,first)['seller_id']=='778899'
    assert research.overview(research.task_id)['studies']==[]
    result={'business_tendency':'unknown','reason':'公开字段不足','risk_clues':[],'unknowns':['维修记录未知']}
    research.runtime.run=lambda request,**kwargs:AnswerResult(type='answer',content=json.dumps(result),candidate_ids=[])
    queued=research.seller(research.task_id,first,study=True)
    assert 'id' in queued
    assert research.execute_next()
    shared=research.seller(research.task_id,second,study=True)
    assert shared['fresh'] is True and shared['result']==result
    assert shared['profile']['卖家芝麻信用']=='极好'
    overview=research.overview(research.task_id)
    assert overview['report'] is None and len(overview['studies'])==1


def test_window_metadata_failure_pauses_saved_native_config(research,monkeypatch):
    from contextlib import contextmanager
    import sqlite3
    original=research.db
    @contextmanager
    def fail_commit():
        with original() as conn:
            yield conn
            if conn.in_transaction:
                raise sqlite3.OperationalError('test sidecar commit failure')
    monkeypatch.setattr(research,'db',fail_commit)
    with pytest.raises(ValueError,match='已请求暂停'):
        research.create_window(research.task_id,'故障测试','once',60,dict(keyword='MacBook',max_pages=1,max_items=5,interval_seconds=60,collect_seller_profiles=False))
    assert research.monitors.list(research.task_id)[0]['state']=='paused'
    with original() as conn:
        assert conn.execute('SELECT COUNT(*) FROM windows').fetchone()[0]==0


def consume_summary_followup(store):
    """New bounded behavior: old nomination may be reviewed once, never full backfill."""
    work = store.overview(store.task_id)['research_work']
    assert work['listing_ids'] and len(work['listing_ids']) <= work['batch_limit']
    # Simulate the existing maximum wait; do not weaken production gates.
    with store.db() as conn:
        conn.execute("UPDATE versions SET observed_at='2020-01-01T00:00:00+00:00' WHERE task_id=?",(store.task_id,))
    job = store.enqueue(store.task_id, automatic=True)
    with store.db() as conn:
        row = conn.execute('SELECT * FROM studies WHERE id=?', (job,)).fetchone()
        assert row['kind'] == 'followup'
        assert {v[0] for v in json.loads(row['versions_json'])} == set(work['listing_ids'])
    store.execute_next()  # Existing summary-only double: explicit incomplete failure.
    assert store.overview(store.task_id)['studies'][0]['state'] == 'failed'
    assert store.enqueue(store.task_id, automatic=True) is None
    return job
