"""P1 acceptance: isolated SQLite, saved research, Mock browser; no CLI/network."""
import asyncio
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_project_research import research, ingest
from shopping_agent.codex_runtime import AnswerResult
from shopping_agent.browser_jobs import BrowserJobStore, BrowserJobCoordinator, BrowserJobError
from shopping_agent.db import connect, add_listing_snapshot, add_detail_snapshot, initialize
from shopping_agent.project_investigations import ProjectInvestigations, facts, held_tasks


def seed(p, count=4, structured=False):
    ids = [ingest(p, title='NS2 Pro controller', price='300') for _ in range(count)]
    p.runtime.run = lambda request, **kw: AnswerResult(type='answer', content='Saved fixture research', candidate_ids=ids,
        check_suggestions=[dict(listing_id=i, question='请核实是否维修、是否漂移并提供实拍', reason='卖家自述不足') for i in ids])
    p.enqueue(p.task_id, ids=ids)
    p.execute_next()
    p.runtime.run = lambda *a, **kw: pytest.fail('P1 must not call the model')
    return ids


def first(p):
    return ProjectInvestigations(p).list(p.task_id)['items'][-1]


def approve_job(p, item=None):
    manager = ProjectInvestigations(p)
    item = item or first(p)
    manager.decide(p.task_id, item['id'], 'approve')
    store = BrowserJobStore(p.config)
    store.set_auth('verified')
    job = store.create_collection(p.task_id,item['request_id'],'',1,investigation_id=item['id'])
    return store, job


def save_detail(p, listing, description='Seller discloses repaired buttons'):
    with p.source_db() as conn:
        row = conn.execute('SELECT * FROM listing_snapshots WHERE listing_id=? ORDER BY id DESC LIMIT 1',(listing,)).fetchone()
        add_listing_snapshot(conn,listing,row['run_id'],title=row['title'],price_text=row['price_text'], description=description)
        missing = p.config.database_path.parent/'not-retained-fixture.txt'
        add_detail_snapshot(conn,listing,row['run_id'],f'https://www.goofish.com/item?id={listing}', 'Detail fixture',
            missing,missing,missing,missing,missing,0,0,False,attributes_json='{"model":"NS2 Pro"}',attributes_source='xianyu_api')


def test_planning_is_bounded_explainable_and_independent_of_ai_coverage(research):
    ids = seed(research)
    manager = ProjectInvestigations(research)
    data = manager.propose(research.task_id)
    assert len(data['items']) == 3
    assert all('历史研究提名' in i['plan']['reason'] and i['plan']['source_study_ids'] for i in data['items'])
    assert all(i['plan']['manual_questions'] and i['kind']=='detail' for i in data['items'])
    # A genuinely valid structured assessment is not a collection veto.
    from test_research_followup import structured
    research.runtime.run=structured
    research.enqueue(research.task_id,ids=ids[:1])
    research.execute_next()
    assert research.overview(research.task_id)['coverage']['evaluated']==1
    assert len(manager.propose(research.task_id)['items']) == 3
    uninteresting = ingest(research, title='unresearched item', price='200')
    _, choices, skipped = manager.candidates(research.task_id)
    assert uninteresting in [i['listing_id'] for i in skipped]
    with research.source_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM browser_jobs').fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM operations WHERE state!='completed'").fetchone()[0] == 0


def test_pending_rejected_and_legacy_paths_cannot_execute(research):
    seed(research)
    item = first(research)
    store = BrowserJobStore(research.config)
    with pytest.raises(BrowserJobError):
        store.create_collection(research.task_id,item['request_id'],'',1,investigation_id=item['id'])
    manager = ProjectInvestigations(research)
    manager.decide(research.task_id,item['id'],'approve')
    with pytest.raises(BrowserJobError):
        store.create_collection(research.task_id,item['request_id'],'',1)
    manager.decide(research.task_id,item['id'],'cancel')
    with pytest.raises(BrowserJobError):
        store.create_collection(research.task_id,item['request_id'],'',1,investigation_id=item['id'])
    with research.source_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM browser_jobs').fetchone()[0] == 0


def test_mock_backend_saves_evidence_and_never_starts_legacy_or_project_ai(research):
    seed(research)
    item = first(research)
    before = research.overview(research.task_id)
    store, job = approve_job(research,item)
    class Backend:
        async def run(self, j, s, config):
            save_detail(research,item['listing_id'])
            return dict(run_ids=[],listing_count=1)
    class Legacy:
        def start(self,*args):
            pytest.fail('P1 cannot launch legacy analysis')
    co = BrowserJobCoordinator(store,Backend(),Legacy())
    co.start(job['id'])
    for _ in range(100):
        if store.get(job['id'])['state'] not in {'queued','running'}:
            break
        __import__('time').sleep(.02)
    co.shutdown()
    item = next(i for i in ProjectInvestigations(research).list(research.task_id)['items'] if i['id']==item['id'])
    assert item['state']=='new_evidence' and item['outcome']['detail_snapshot_ids']
    assert item['job_id']==job['id'] and item['outcome']['manually_reassessed'] is False
    with pytest.raises(BrowserJobError):
        store.analyze(job['id'])
    with research.source_db() as conn:
        assert research.task_id in held_tasks(conn)
    assert research.enqueue(research.task_id,automatic=True) is None
    after = research.overview(research.task_id)
    assert len(after['studies'])==len(before['studies']) and after['report']==before['report']
    c = next(c for c in research.cards(research.task_id) if c['listing_id']==item['listing_id'])
    request = research._request(research.task_id,[c],'manual future input')
    assert 'repaired buttons' in request.model_dump_json()


def test_only_explicit_current_structured_research_can_release_p1_hold(research):
    from test_research_followup import structured
    seed(research)
    item=first(research)
    store,job=approve_job(research,item)
    save_detail(research,item['listing_id'])
    store.finish(job['id'],'completed',dict(run_ids=[],listing_count=1))
    assert research.enqueue(research.task_id,automatic=True) is None
    research.runtime.run=structured  # Controlled model double, never CLI.
    research.enqueue(research.task_id,ids=[item['listing_id']],question='用户明确要求按当前证据研究')
    research.execute_next()
    with research.source_db() as conn:
        assert research.task_id not in held_tasks(conn)


def test_same_request_is_atomic_and_restart_does_not_retry(research):
    seed(research)
    item=first(research)
    manager=ProjectInvestigations(research)
    manager.decide(research.task_id,item['id'],'approve')
    store=BrowserJobStore(research.config)
    with ThreadPoolExecutor(2) as pool:
        jobs=list(pool.map(lambda _:store.create_collection(research.task_id,item['request_id'],'',1,investigation_id=item['id']),range(2)))
    assert jobs[0]['id']==jobs[1]['id']
    store.recover_interrupted()
    assert store.get(jobs[0]['id'])['state']=='interrupted'
    assert store.create_collection(research.task_id,item['request_id'],'',1,investigation_id=item['id'])['id']==jobs[0]['id']
    assert sum(i['state']=='pending' for i in manager.propose(research.task_id)['items'])==3
    with research.source_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM browser_jobs').fetchone()[0]==1


@pytest.mark.parametrize('code',['login_required','access_blocked','verification_closed','browser_busy','detail_unavailable'])
def test_failure_categories_no_automatic_retry(research,code):
    seed(research)
    store,job=approve_job(research)
    store.finish(job['id'],'failed',error_code=code,error_detail='fixture failure')
    manager=ProjectInvestigations(research)
    item=next(i for i in manager.list(research.task_id)['items'] if i['job_id']==job['id'])
    assert item['state'] in {'failed','needs_attention'} and not item['outcome']['new_evidence']
    manager.propose(research.task_id)
    with research.source_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM browser_jobs').fetchone()[0]==1


def test_no_new_facts_and_fresh_detail_not_repeated(research):
    seed(research)
    item=first(research)
    store,job=approve_job(research,item)
    store.finish(job['id'],'completed',dict(run_ids=[],listing_count=0),continue_research=True)
    rows=ProjectInvestigations(research).propose(research.task_id)['items']
    item=next(i for i in rows if i['job_id']==job['id'])
    assert item['state']=='no_new_evidence'
    with research.source_db() as conn:
        assert research.task_id not in held_tasks(conn)
    save_detail(research,item['listing_id'])
    _,choices,skipped=ProjectInvestigations(research).candidates(research.task_id)
    assert not any(c[1]==item['listing_id'] and c[2]=='detail' for c in choices)


def test_scope_goal_version_and_changed_evidence_guard(research):
    seed(research)
    manager=ProjectInvestigations(research)
    item=first(research)
    with pytest.raises(BrowserJobError):
        manager.propose(research.task_id, [999999])
    manager.decide(research.task_id,item['id'],'approve')
    with research.db() as conn:
        goal=dict(conn.execute('SELECT * FROM project_goal_revisions WHERE task_id=?', (research.task_id,)).fetchone())
    research.save_goal(research.task_id,goal='New controller budget',budget=500,hard=[],soft=[],expected_revision=goal['revision'],request_key='changed-goal-for-p1',confirmed=True)
    with pytest.raises(BrowserJobError):
        BrowserJobStore(research.config).create_collection(research.task_id,item['request_id'],'',1,investigation_id=item['id'])


def test_busy_browser_retains_approval_without_fake_queue(research):
    seed(research)
    item=first(research)
    manager=ProjectInvestigations(research)
    manager.decide(research.task_id,item['id'],'approve')
    store=BrowserJobStore(research.config)
    login=store.create_login()
    with pytest.raises(BrowserJobError,match='浏览器'):
        store.create_collection(research.task_id,item['request_id'],'',1,investigation_id=item['id'])
    assert next(i for i in manager.list(research.task_id)['items'] if i['id']==item['id'])['state']=='approved'
    assert store.latest_for_request(research.task_id,item['request_id']) is None


def test_goal_changes_after_job_creation_fail_before_browser_claim(research):
    seed(research)
    store,job=approve_job(research)
    goal=research.goal(research.task_id)
    research.save_goal(research.task_id,goal='Changed requirements',budget=600,hard=[],soft=[],
                       expected_revision=goal['revision'],request_key='p1-change-before-claim',confirmed=True)
    assert store.claim(job['id']) is False
    assert store.get(job['id'])['error_code']=='goal_changed'


def test_cancellation_uses_existing_browser_shutdown_without_analysis(research):
    import threading,time
    seed(research)
    store,job=approve_job(research)
    started=threading.Event()
    class Backend:
        async def run(self,*args):
            started.set()
            await asyncio.sleep(30)
    co=BrowserJobCoordinator(store,Backend())
    co.start(job['id'])
    assert started.wait(3)
    co.cancel(job['id']);co.shutdown()
    assert store.get(job['id'])['state']=='cancelled'
    assert store.get(job['id'])['analysis_operation_id'] is None


def test_manual_and_unsupported_seller_demands_are_not_detail_jobs(research):
    ids=seed(research)
    # Clear only isolated plan metadata to exercise the classification anew.
    with research.source_db() as conn:
        conn.execute('DELETE FROM project_investigations')
    for listing in ids:
        save_detail(research,listing)
    data=ProjectInvestigations(research).propose(research.task_id)
    assert data['items'] and all(i['kind']=='manual' and i['request_id'] is None for i in data['items'])
    with research.db() as conn:
        row=conn.execute('SELECT id,result_json FROM studies LIMIT 1').fetchone()
        result=json.loads(row['result_json'])
        result['check_suggestions']=[dict(listing_id=ids[-1], question='查看卖家主页信用和其他商品', reason='缺少公开资料')]
        conn.execute('UPDATE studies SET result_json=? WHERE id=?',(json.dumps(result,ensure_ascii=False),row['id']))
    with research.source_db() as conn:
        conn.execute('DELETE FROM project_investigations')
    data=ProjectInvestigations(research).propose(research.task_id)
    assert any(i['kind']=='seller_public' and i['state']=='unsupported' for i in data['items'])


def test_api_confirmation_scope_and_idempotent_execution(research,tmp_path):
    from fastapi.testclient import TestClient
    from shopping_agent.web.app import create_app
    seed(research)
    research.control(research.task_id,'pause')
    item=first(research)
    config=tmp_path/'web.toml'
    config.write_text('database_path="'+research.config.database_path.as_posix()+'"\n',encoding='utf-8')
    class Backend:
        async def run(self,job,store,config):
            return dict(run_ids=[],listing_count=0)
    app=create_app(config,tmp_path/'settings.json')
    app.state.codex_runtime=research.runtime
    app.state.browser_backend=Backend()
    root=f'/api/projects/{research.task_id}/investigations'
    with TestClient(app,base_url='http://127.0.0.1') as client:
        app.state.browser_store.set_auth('verified')
        assert client.post(root+f"/{item['id']}/approve",json={'confirmed':False}).status_code==422
        assert client.post(root+f"/{item['id']}/execute",json={'confirmed':True,'url':'https://evil.test'}).status_code==422
        assert client.post(root+f"/{item['id']}/execute",json={'confirmed':True}).status_code==409
        assert client.post(root+f"/{item['id']}/approve",json={'confirmed':True}).status_code==200
        from shopping_agent.web.dependencies import get_config
        app.dependency_overrides[get_config]=lambda: research.config.model_copy(update={'allow_login':False})
        assert client.post(root+f"/{item['id']}/execute",json={'confirmed':True}).status_code==409
        with research.source_db() as conn:
            assert conn.execute('SELECT COUNT(*) FROM browser_jobs').fetchone()[0]==0
        app.dependency_overrides.pop(get_config)
        assert client.post(root+f"/{item['id']}/execute",json={'confirmed':True}).status_code==200
        assert client.post(root+f"/{item['id']}/execute",json={'confirmed':True}).status_code==200
    with research.source_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM browser_jobs').fetchone()[0]==1
        assert conn.execute("SELECT COUNT(*) FROM operations WHERE state IN ('queued','running')").fetchone()[0]==0


def test_real_ns2_saved_snapshots_are_read_only_copied_and_can_be_planned(tmp_path):
    from shopping_agent.config import AppConfig
    from shopping_agent.monitoring import MonitorStore
    from shopping_agent.project_research import ProjectResearch
    from test_project_research import Runtime
    root=Path(__file__).resolve().parents[1]/'data/secondpick-preview'
    if not (root/'shopping.sqlite').exists():
        pytest.skip('Local saved snapshots unavailable')
    target=tmp_path/'shopping.sqlite'
    for old,new in ((root/'shopping.sqlite',target),(root/'shopping.secondpick.sqlite',target.with_suffix('.secondpick.sqlite'))):
        with closing(sqlite3.connect(old.resolve().as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(new)) as dest:
            source.backup(dest)
    config=AppConfig(database_path=target)
    p=ProjectResearch(config,Runtime(),MonitorStore(config))
    with p.source_db() as conn:
        original_details=conn.execute('SELECT COUNT(*) FROM detail_snapshots').fetchone()[0]
        original_collections=conn.execute("SELECT COUNT(*) FROM browser_jobs WHERE kind='collection'").fetchone()[0]
    with p.db() as conn:
        count=conn.execute('SELECT COUNT(*) FROM studies').fetchone()[0]
    original_cards=p.cards(3)
    assert original_cards
    data=ProjectInvestigations(p).propose(3,[1879,1881,1887])
    assert {i['listing_id'] for i in data['items']}=={1879,1881,1887}
    assert all(i['goal_revision']==1 and i['plan']['source_study_ids'] and i['plan']['manual_questions'] for i in data['items'])
    manager=ProjectInvestigations(p)
    pending=[i for i in data['items'] if i['state']=='pending']
    manager.decide(3,pending[0]['id'],'cancel')
    subsequent=manager.propose(3,[1889])
    assert any(i['listing_id']==1889 and i['state']=='pending' for i in subsequent['items'])
    # The saved formal fixture may already contain the accepted #1879 detail.
    # Preserve it; replacing one pending plan adds exactly one pending plan.
    assert sum(i['state']=='pending' for i in subsequent['items'])==len(pending)
    assert [c['listing_id'] for c in p.cards(3)]==[c['listing_id'] for c in original_cards]
    assert [p.signature(c) for c in p.cards(3)]==[p.signature(c) for c in original_cards]
    with p.source_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM detail_snapshots').fetchone()[0]==original_details
        assert conn.execute("SELECT COUNT(*) FROM browser_jobs WHERE kind='collection'").fetchone()[0]==original_collections
    with p.db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM studies').fetchone()[0]==count


@pytest.mark.parametrize('new_information',[False,True])
def test_real_collection_and_detail_persistence_with_only_browser_response_mocked(research,tmp_path,monkeypatch,new_information):
    from shopping_agent.browser_collection import BrowserCollectionBackend
    from shopping_agent.browser.session import BrowserSession,DetailSnapshot
    ids=seed(research)
    listing=first(research)['listing_id']
    description='Seller states a controller with unknown repair history'
    # A saved card can already contain the same text. A new detail row alone
    # must not be mistaken for new facts.
    with research.source_db() as conn:
        conn.execute('UPDATE listing_snapshots SET description=? WHERE listing_id=?',(description,listing))
        conn.execute('DELETE FROM project_investigations')
    research.config=research.config.model_copy(update=dict(browser_profile_dir=tmp_path/'profile',
        screenshots_dir=tmp_path/'captures',reports_dir=tmp_path/'reports',media_dir=tmp_path/'media',
        safety=research.config.safety.model_copy(update=dict(xianyu_min_delay_ms=0,xianyu_max_delay_ms=0))))
    manager=ProjectInvestigations(research)
    item=manager.propose(research.task_id,[listing])['items'][0]
    store,job=approve_job(research,item)
    captures=[]
    async def capture(self,*,url,output_dir,**kwargs):
        captures.append(url)
        output_dir.mkdir(parents=True,exist_ok=True)
        text=output_dir/'text.txt';text.write_text('Saved offline fixture',encoding='utf-8')
        return DetailSnapshot(url,text,text,text,text,text,'NS2 Pro controller','Saved offline fixture',[],[],False,
            api_detail=dict(item=dict(itemId=url.split('id=')[-1],title='NS2 Pro controller',soldPrice='300',
                desc='Seller now discloses repaired buttons' if new_information else description),seller={}))
    monkeypatch.setattr(BrowserSession,'capture_detail_snapshot',capture)
    assert store.claim(job['id'])
    result=asyncio.run(BrowserCollectionBackend().run(store.get(job['id']),store,research.config))
    store.finish(job['id'],'completed',result,continue_research=True)
    after=next(i for i in manager.list(research.task_id)['items'] if i['id']==item['id'])
    assert after['state']==('new_evidence' if new_information else 'no_new_evidence')
    assert len(captures)==1 and result['listing_count']==1
    assert len(after['outcome']['detail_snapshot_ids'])==1
    assert store.get(job['id'])['analysis_operation_id'] is None
    with research.source_db() as conn:
        assert research.task_id in held_tasks(conn)  # Even identical facts have a new snapshot ID; never start P2.
