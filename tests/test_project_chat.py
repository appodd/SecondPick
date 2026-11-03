import json,sqlite3,socket,subprocess,threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from shopping_agent.config import AppConfig
from shopping_agent.db import connect,create_search_run,attach_run_to_task,upsert_listing,add_listing_snapshot
from shopping_agent.codex_runtime import CodexRuntime,AnswerResult
from shopping_agent.monitoring import MonitorStore
from shopping_agent.project_research import ProjectResearch
from shopping_agent.project_chat import ProjectChat
from shopping_agent.conversation_store import OperationConflictError,InvalidActionRequestError

H=Path(__file__).resolve().parents[1]
class Runtime:
    def __init__(self):self.calls=[];self.failure=False;self.action=False
    def build_request(self,**kw):return CodexRuntime(H/'ai-workspace').build_request(**kw)
    def run(self,request,**kw):
        self.calls.append(request)
        if self.failure:raise RuntimeError('fake-sensitive-value-never-persist')
        if self.action:return object()
        return AnswerResult(type='answer',content='仅文字对照：商品 #1 的功能尚待核实。',candidate_ids=[1],
            check_suggestions=[dict(listing_id=1,question='功能正常吗？',reason='文字未说明')])

@pytest.fixture(scope='module')
def chat_seed(tmp_path_factory):
    """Generate public synthetic evidence; never depend on ignored workspace databases."""
    directory=tmp_path_factory.mktemp('project-chat-seed')
    cfg=AppConfig(database_path=directory/'shopping.sqlite',media_dir=directory/'media')
    runtime=Runtime();research=ProjectResearch(cfg,runtime,MonitorStore(cfg))
    research.create('测试手柄','购买功能正常的手柄',400,[],[],2,False,auto_cover_cache=False)
    with connect(cfg.database_path) as c:
        run=create_search_run(c,'手柄','')
        attach_run_to_task(c,1,run)
        for n in (1,2):
            listing=upsert_listing(c,'xianyu',f'https://www.goofish.com/item?id={n}')
            add_listing_snapshot(c,listing,run,title=f'测试手柄 {n}',price_text='300')
    research.save_goal(1,goal='购买原装正品且功能正常的手柄',budget=400,hard=[],soft=[],expected_revision=1,request_key='fixture-goal',confirmed=True)
    runtime.run=lambda *a,**k:AnswerResult(type='answer',content='卖家声明原装正品，功能仍需核实。',candidate_ids=[1])
    for n in (1,2):
        research.enqueue(1,ids=[1,2],question='比较文字证据',request_key=f'fixture-study-{n}')
        assert research.execute_next()
    with research.db() as c:c.execute('UPDATE projects SET paused=1 WHERE task_id=1')
    return directory

@pytest.fixture
def env(tmp_path,monkeypatch,chat_seed):
    def deny(*a,**k):raise AssertionError('Real network/process forbidden in offline tests')
    monkeypatch.setattr(socket.socket,'connect',deny);monkeypatch.setattr(subprocess,'Popen',deny)
    for name in ('shopping.sqlite','shopping.secondpick.sqlite'):
        with sqlite3.connect((chat_seed/name).resolve().as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(tmp_path/name) as dst:src.backup(dst)
    cfg=AppConfig(database_path=tmp_path/'shopping.sqlite',media_dir=tmp_path/'media')
    runtime=Runtime();research=ProjectResearch(cfg,runtime,MonitorStore(cfg));chat=ProjectChat(research,runtime)
    return research,chat,runtime

def send(env,key='request-test-001',**kw):
    research,chat,_=env
    return chat.send(1,message='这件商品还缺哪些证据？',ids=[1],request_key=key,expected_goal_revision=research.goal(1)['revision'],**kw)

def counts(research):
    result={}
    for path,tables in [(research.path,['studies','reports','versions','favorites']), (research.config.database_path,['assessments','action_requests','candidate_checks','check_suggestions','task_preference_revisions'])]:
        with sqlite3.connect(path) as c:
            existing={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in tables:
                if table in existing:result[table]=c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    return result

def test_chat_works_while_research_paused_without_formal_writes(env):
    before=counts(env[0]);result=send(env)
    assert len(result['items'])==2 and result['items'][-1]['role']=='assistant'
    assert counts(env[0])==before and len(env[2].calls)==1

def test_same_key_replays_without_model(env):
    first=send(env);second=send(env)
    assert first['operation_id']==second['operation_id'] and len(env[2].calls)==1

def test_key_cannot_change_question_or_scope(env):
    send(env)
    with pytest.raises(OperationConflictError):env[1].send(1,message='其他问题',ids=[1],request_key='request-test-001',expected_goal_revision=env[0].goal(1)['revision'])
    assert len(env[2].calls)==1

@pytest.mark.parametrize('ids',[[999999],[1,1]])
def test_invalid_scope_refused_before_call(env,ids):
    with pytest.raises(InvalidActionRequestError):env[1].send(1,message='问题',ids=ids,request_key='wrong-scope-001',expected_goal_revision=env[0].goal(1)['revision'])
    assert not env[2].calls and not env[1].history(1)['items']

def test_stale_goal_refused_before_call(env):
    with pytest.raises(OperationConflictError):env[1].send(1,message='问题',ids=[1],request_key='stale-goal-001',expected_goal_revision=9999)
    assert not env[2].calls

def test_history_is_persistent_and_context_is_server_owned(env):
    send(env);send(env,key='request-test-002')
    assert len(ProjectChat(env[0],env[2]).history(1)['items'])==4
    content=env[2].calls[-1].messages[0].content
    assert '仅文字对照' in content and 'goal_revision' in content

def test_failed_output_retains_safe_failure_without_retry(env):
    env[2].failure=True;before=counts(env[0])
    with pytest.raises(ValueError):send(env)
    item=env[1].history(1)['items'][0]
    assert item['state']=='failed' and 'fake-sensitive' not in item['error']
    assert len(env[2].calls)==1 and counts(env[0])==before

def test_non_answer_never_creates_action(env):
    env[2].action=True;before=counts(env[0])
    with pytest.raises(ValueError):send(env)
    assert counts(env[0])==before and env[1].history(1)['items'][0]['state']=='failed'

def test_parallel_same_key_does_not_double_submit(env):
    runtime=env[2];original=runtime.run;entered=threading.Event();release=threading.Event()
    def run(*a,**kw):entered.set();assert release.wait(5);return original(*a,**kw)
    runtime.run=run
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(send,env);assert entered.wait(5)
        replay=send(env);assert replay['items'][-1]['state']=='running'
        release.set();first.result()
    assert len(runtime.calls)==1

def test_different_project_cannot_read_thread(env):
    send(env)
    project=env[0].create(title='独立项目',goal='仅此项目',budget=100,hard=[],soft=[],minimum=20,auto_research=False,auto_cover_cache=False,request_key='project-test-two')
    assert env[1].history(project['id'])['items']==[]
    with pytest.raises(InvalidActionRequestError):env[1].send(project['id'],message='问题',ids=[1],request_key='cross-project-001',expected_goal_revision=1)

def test_wrong_response_reference_rejected(env):
    env[2].run=lambda *a,**k:AnswerResult(type='answer',content='错误引用',candidate_ids=[2])
    with pytest.raises(ValueError):send(env)
    assert len(env[1].history(1)['items'])==1

def test_all_non_conversation_business_tables_and_schema_unchanged(env):
    def snapshot():
        result={}
        for label,file in [('main',env[0].config.database_path),('research',env[0].path)]:
            with sqlite3.connect(file) as c:
                result[label+':schema']=c.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
                tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                for table in tables:
                    if label=='main' and table in {'conversation_messages','operations','operation_events','research_tasks','sqlite_sequence'}:continue
                    result[label+':'+table]=c.execute('SELECT * FROM "'+table+'"').fetchall()
        return result
    before=snapshot();send(env);assert snapshot()==before

def test_explicit_study_is_loaded_by_server_and_bound_to_turn(env):
    result=send(env,study_id=2)
    assert result['items'][-1]['scope']['study_id']==2
    assert 'explicit_sources' in env[2].calls[-1].messages[0].content
    assert '原装正品' in env[2].calls[-1].messages[0].content
    assert '"current_goal_revision": 2' in env[2].calls[-1].messages[0].content
    assert 'preference_revision_id是旧会话偏好记录版本' in env[2].calls[-1].messages[0].content

def test_project_question_needs_no_manual_selection(env):
    r=env[1].send(1,message='整个项目下一步呢？',ids=[],request_key='project-wide-question',expected_goal_revision=env[0].goal(1)['revision'])
    assert r['items'][-1]['scope']['ids']==[] and set(env[2].calls[-1].allowed_listing_ids)=={1,2}

def test_missing_report_rejected_before_any_model_or_message(env):
    with pytest.raises(InvalidActionRequestError):send(env,report_id=999999)
    assert not env[2].calls and not env[1].history(1)['items']

def test_cross_project_study_source_is_rejected(env):
    p=env[0].create(title='另一个项目',goal='二手键盘',budget=100,hard=[],soft=[],minimum=20,auto_research=False,auto_cover_cache=False,request_key='project-source-test')
    with pytest.raises(InvalidActionRequestError):env[1].send(p['id'],message='解释研究',ids=[],request_key='foreign-study-source',expected_goal_revision=1,study_id=2)
    assert not env[2].calls and not env[1].history(p['id'])['items']

def test_same_request_key_cannot_change_its_source(env):
    send(env)
    with pytest.raises(OperationConflictError):send(env,study_id=2)
    assert len(env[2].calls)==1

def test_selected_historical_report_is_included_even_when_a_newer_report_exists(env):
    with env[0].db() as c:
        c.execute("INSERT INTO reports(task_id,study_id,content,candidate_ids_json,snapshot_at,created_at,limited) VALUES(1,2,'selected historical report marker','[1]','2026-10-27','2026-10-27',1)")
        ident=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO studies(task_id,kind,state,request_json,versions_json,snapshot_at,created_at,finished_at,result_json,error,request_key) SELECT task_id,kind,state,request_json,versions_json,snapshot_at,created_at,finished_at,result_json,error,request_key||'_newer_fixture' FROM studies WHERE id=2")
        newer=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO study_goal_bindings SELECT ?,task_id,goal_revision,proof FROM study_goal_bindings WHERE study_id=2',(newer,))
        c.execute("INSERT INTO reports(task_id,study_id,content,candidate_ids_json,snapshot_at,created_at,limited) VALUES(1,?,'newer report marker','[2]','2026-10-28','2026-10-28',1)",(newer,))
    result=send(env,report_id=ident)
    assert result['items'][-1]['scope']['report_id']==ident
    prompt=env[2].calls[-1].messages[0].content
    assert 'selected historical report marker' in prompt and 'newer report marker' in prompt

def test_foreign_report_is_not_accepted_as_project_background(env):
    with env[0].db() as c:
        c.execute("INSERT INTO reports(task_id,study_id,content,candidate_ids_json,snapshot_at,created_at,limited) VALUES(1,2,'project A private marker','[1]','2026-10-27','2026-10-27',1)")
        ident=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    p=env[0].create(title='另一个项目',goal='键盘',budget=100,hard=[],soft=[],minimum=20,auto_research=False,auto_cover_cache=False,request_key='foreign-report-project')
    with pytest.raises(InvalidActionRequestError):env[1].send(p['id'],message='解释报告',ids=[],request_key='foreign-report-question',expected_goal_revision=1,report_id=ident)
    assert not env[2].calls and not env[1].history(p['id'])['items']
