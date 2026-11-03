"""Structured adjustment drafts use runtime doubles and isolated SQLite only."""
import json
import pytest
from fastapi.testclient import TestClient
from shopping_agent.codex_runtime import AnswerResult, CodexRuntime
from shopping_agent.db import connect
from shopping_agent.web.app import create_app


class Runtime(CodexRuntime):
    def __init__(self):
        self.requests=[]
        self.payload=dict(title='MacBook Pro',goal='选购 MacBook Pro M2，预算6000元，存储256GB以上，上海自提优先。',budget=6000,hard=['MacBook Pro','芯片至少为 M2','存储256GB以上'],soft=['上海自提优先'])

    def run(self, request, **kwargs):
        self.requests.append(request)
        return AnswerResult(type='answer',content=json.dumps(self.payload),candidate_ids=[])


@pytest.fixture
def client(tmp_path):
    config=tmp_path/'config.toml'
    config.write_text(f'database_path="{(tmp_path/"app.sqlite").as_posix()}"\n',encoding='utf8')
    app=create_app(config,tmp_path/'settings.json');runtime=Runtime();app.state.codex_runtime=runtime
    with TestClient(app,base_url='http://127.0.0.1') as value:
        yield value,runtime,app


def current():
    return dict(goal='选购 MacBook Pro M1，存储256GB以上，上海自提优先。',budget=None,hard=['MacBook Pro','芯片至少为 M1','存储256GB以上'],soft=['上海自提优先'])


def test_intent_and_full_current_conditions_are_separate_and_never_saved(client):
    http,runtime,app=client
    response=http.post('/api/project-goal-drafts',json=dict(goal='改成M2，预算6000元，其他不变',current=current()))
    assert response.status_code==200,response.text
    draft=response.json()
    assert draft['goal']==runtime.payload['goal']
    assert draft['goal']!='改成M2，预算6000元，其他不变'
    assert draft['budget']==6000 and draft['soft']==['上海自提优先']
    assert '芯片至少为 M1' not in draft['hard']
    assert runtime.requests[0].task.original_goal=='改成M2，预算6000元，其他不变'
    with connect(app.state.project_research.config.database_path) as db:
        assert db.execute('SELECT COUNT(*) FROM research_tasks').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM monitors').fetchone()[0]==0


def test_new_project_parser_still_preserves_the_original_user_description(client):
    http,runtime,_=client
    response=http.post('/api/project-goal-drafts',json=dict(goal='买MacBook Pro M2，上海优先'))
    assert response.status_code==200
    assert response.json()['goal']=='买MacBook Pro M2，上海优先'


@pytest.mark.parametrize('bad_goal',[None,'','当前选购条件（JSON）：internal prompt'])
def test_invalid_or_instruction_shaped_full_goals_are_rejected(client,bad_goal):
    http,runtime,_=client;runtime.payload['goal']=bad_goal
    assert http.post('/api/project-goal-drafts',json=dict(goal='改成M2',current=current())).status_code==502


def test_new_region_is_not_invented_and_explicit_region_removal_is_respected(client):
    http,runtime,_=client
    runtime.payload['goal']='MacBook Pro M2，上海优先'
    assert http.post('/api/project-goal-drafts',json=dict(goal='改成M2',current=dict(goal='MacBook Pro M1',budget=None,hard=[],soft=[]))).status_code==502
    runtime.payload['goal']='MacBook Pro M2，不限地区'
    response=http.post('/api/project-goal-drafts',json=dict(goal='改成M2，取消地区限制',current=current()))
    assert response.status_code==200,response.text
    assert response.json()['soft']==[]


def test_incomplete_draft_does_not_silently_clear_existing_conditions(client):
    http,runtime,_=client
    del runtime.payload['hard']
    response=http.post('/api/project-goal-drafts',json=dict(goal='预算改6000',current=current()))
    assert response.status_code==502
