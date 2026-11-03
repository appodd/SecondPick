"""Protocol and local decision regressions. No model behavior is simulated as fact."""
import copy
import json
from pathlib import Path

import pytest

from shopping_agent.assessment import ResearchResult, input_refs
from shopping_agent.codex_runtime import AnswerResult, CodexRequest
from shopping_agent.evidence_research import decision_impacts
from shopping_agent.match_semantics import MATCH_SEMANTICS
from test_project_research import research, ingest
from test_evidence_research import seed, changed, supported_improvement


def one(status, source='seller_claim', refs=None, description='型号符合', conclusion='conditional'):
    return ResearchResult.model_validate(dict(criteria=[dict(criterion_id='model',description=description,priority='hard',source_refs=['task_goal'])],
        assessments=[dict(listing_id=1879,conclusion=conclusion,summary='初步判断，交易风险仍需核实',judgments=[dict(
            criterion_id='model',status=status,source_type=source,evidence_refs=refs if refs is not None else ['detail:1879:saved'],
            reason='仅据保存材料判断此具体条件，不代表独立核验')])]))


@pytest.mark.parametrize('description', ['Switch 2 Pro 手柄', '成色好', 'MacBook Pro 内存至少16GB'])
def test_seller_supported_met_can_remain_conditional(description):
    result=one('MET',description=description)
    assert result.assessments[0].conclusion=='conditional'
    assert '初步匹配，不代表独立核验' in MATCH_SEMANTICS


@pytest.mark.parametrize('status,source,refs,conclusion', [
    ('UNKNOWN','missing',[],'insufficient_evidence'),
    ('CONFLICT','seller_claim',['card:1879:old','detail:1879:new'],'insufficient_evidence'),
    ('NOT_MET','platform_display',['card:1879:price'],'not_met'),
])
def test_real_missing_conflicting_and_failed_conditions_remain_distinct(status,source,refs,conclusion):
    assert one(status,source,refs,conclusion=conclusion).assessments[0].judgments[0].status==status


def test_verification_requirements_and_images_are_explicit_in_shared_instructions():
    # Instruction checks cannot prove a future real model will comply.
    for text in ['检测报告、原始购买凭证','卖家承诺不能使证明要求成为 MET', '仅图片 URL 不代表看过图片',
                 '重复引用不是独立佐证','不擅自将它们扩展为用户未设定的硬条件','多个 MET 不等于推荐购买']:
        assert text in MATCH_SEMANTICS
    assert one('UNKNOWN','missing',[],description='必须提供原始购买凭证',conclusion='insufficient_evidence')


def test_project_initial_incremental_and_followup_share_saved_instructions(research):
    ids=[ingest(research) for _ in range(3)]
    first=research.enqueue(research.task_id);research.execute_next()
    ingest(research)
    incremental=research.enqueue(research.task_id);research.execute_next()
    followup=research.enqueue(research.task_id,ids=ids,_followup=True)
    assert first and incremental and followup
    with research.db() as conn:
        requests=[json.loads(row[0]) for row in conn.execute('SELECT request_json FROM studies')]
    assert len(requests)==3
    assert all(MATCH_SEMANTICS in req['messages'][0]['content'] for req in requests)


def test_repeat_nomination_or_conclusion_label_alone_does_not_integrate(research):
    ids=seed(research);changed(research,ids[0])
    def label_only(req,**kwargs):
        from test_research_followup import structured
        out=structured(req)
        for a in out.research.assessments:a.conclusion='conditional'
        out.candidate_ids=list(req.allowed_listing_ids)
        return out
    research.runtime.run=label_only
    research.enqueue(research.task_id,automatic=True);research.execute_next()
    assert research.overview(research.task_id)['integration_work']['state']=='none'


def test_real_sourced_match_improvement_is_traceable_and_waits_while_paused(research):
    ids=seed(research);changed(research,ids[0],'Seller explicitly declares 16GB memory')
    research.runtime.run=supported_improvement
    research.enqueue(research.task_id,automatic=True);research.execute_next()
    research.control(research.task_id,'pause')
    work=research.overview(research.task_id)['integration_work']
    assert work['state']=='pending' and '暂停' in work['reason']
    assert work['updates'][0]['decision_impacts'][0]['evidence_refs']
    assert research.execute_next() is False


@pytest.mark.skipif(not all((Path(__file__).resolve().parents[1]/'data/artifacts/p2-one-real-1879-20261024'/name).is_file() for name in ['actual-request.json','prepared.json','parsed-result.json']), reason='Private historical acceptance artifacts are not distributed')
def test_1879_saved_real_evidence_mock_preserves_preliminary_matches(tmp_path):
    root=Path(__file__).resolve().parents[1]/'data/artifacts/p2-one-real-1879-20261024'
    request=json.loads((root/'actual-request.json').read_text(encoding='utf-8'))
    decision=json.loads((root/'prepared.json').read_text(encoding='utf-8'))['decision']
    frozen=json.dumps(request,ensure_ascii=False,sort_keys=True)
    assert decision['delta']['before']['price']==338 and decision['delta']['after']['price']==328
    assert decision['delta']['after']['attributes']['成色']=='几乎全新'
    old=copy.deepcopy(decision['previous']['assessment'])
    ref=next(ref for ref in input_refs(CodexRequest.model_validate_json(json.dumps(request))) if ref.startswith('detail:1879:'))
    for j in old['judgments']:
        j['evidence_refs']=[ref]
        if j['criterion_id'] in {'hard_1','soft_1'}:
            assert j['status']=='MET'
            j.update(reason='新增描述和卖家填写属性继续支持型号与成色声明；未查看图片、未独立验真',source_type='seller_claim')
    result=AnswerResult.model_validate(dict(type='answer',content='Mock 口径回归，不是真实模型输出',candidate_ids=[1879],
        research=dict(criteria=request['current_criteria'],assessments=[old])))
    assert {j.criterion_id:j.status for j in result.research.assessments[0].judgments}==dict(goal='UNKNOWN',hard_1='MET',soft_1='MET',soft_2='UNKNOWN')
    assert result.research.assessments[0].conclusion=='conditional'
    assert not decision_impacts(decision,old,request)  # MET→MET, evidence improved; no purchase change.
    historical=json.loads((root/'parsed-result.json').read_text(encoding='utf-8'))
    assert not decision_impacts(decision,historical['research']['assessments'][0],request)  # Old stricter UNKNOWN drift also ignored.
    assert json.dumps(request,ensure_ascii=False,sort_keys=True)==frozen
    (tmp_path/'mock-1879-result.json').write_text(result.model_dump_json(indent=2),encoding='utf-8')


def test_impact_requires_new_facts_in_actual_citation_and_concrete_status_change():
    old=one('MET').assessments[0].model_dump()
    item=dict(listing_id=1879,previous=dict(assessment=old),delta=dict(important=True,fields=['price'],before=dict(price=328),after=dict(price=6000)))
    excerpt=dict(task_id=3,listing_id=1879,data=dict(evidence_json=json.dumps(dict(price_value=6000))))
    snapshot=dict(candidates=[excerpt],evidence=[])
    from shopping_agent.assessment import input_refs_from_snapshot
    ref=next(iter(input_refs_from_snapshot(snapshot)))
    new=one('NOT_MET','platform_display',[ref],conclusion='not_met').assessments[0].model_dump()
    assert decision_impacts(item,new,snapshot)[0]['after']=='NOT_MET'
    new['judgments'][0]['evidence_refs']=['unbound:ref']
    assert not decision_impacts(item,new,snapshot)


def test_specific_new_user_observation_can_support_conflict_without_inventing_independent_verification():
    from shopping_agent.assessment import input_refs_from_snapshot
    statement=dict(id=4,source_message_id=7,kind='user_observation',statement_text='实物标签型号与页面声明不一致')
    snapshot=dict(candidates=[],evidence=[dict(task_id=3,listing_id=1879,data=dict(evidence_json=json.dumps(dict(user_statements=[statement]))))])
    refs=input_refs_from_snapshot(snapshot)
    statement_ref=next(ref for ref in refs if ref.startswith('statement:'))
    detail_ref=next(ref for ref in refs if ref.startswith('detail:'))
    delta=dict(important=True,fields=['statements'],before=dict(statements=[]),after=dict(statements=[dict(kind=statement['kind'],text=statement['statement_text'])]))
    item=dict(listing_id=1879,previous=dict(assessment=one('MET').assessments[0].model_dump()),delta=delta)
    result=one('CONFLICT','user_statement',[statement_ref,detail_ref],conclusion='insufficient_evidence').assessments[0].model_dump()
    assert statement_ref in decision_impacts(item,result,snapshot)[0]['evidence_refs']


def test_soft_condition_difference_without_purchase_change_does_not_require_report_call():
    from shopping_agent.assessment import input_refs_from_snapshot
    snapshot=dict(current_criteria=[dict(criterion_id='appearance',priority='soft')],candidates=[],evidence=[
        dict(task_id=3,listing_id=1879,data=dict(evidence_json=json.dumps(dict(detail=dict(description='轻微划痕')))))])
    refs=list(input_refs_from_snapshot(snapshot))
    previous=dict(conclusion='conditional',judgments=[dict(criterion_id='appearance',status='MET')])
    new=dict(conclusion='conditional',judgments=[dict(criterion_id='appearance',status='NOT_MET',reason='卖家新增轻微划痕说明，仍有条件保留',evidence_refs=refs)])
    item=dict(listing_id=1879,previous=dict(assessment=previous),delta=dict(important=True,fields=['description'],before=dict(description='几乎全新'),after=dict(description='轻微划痕')))
    assert not decision_impacts(item,new,snapshot)
