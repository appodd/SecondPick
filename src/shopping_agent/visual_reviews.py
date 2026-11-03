"""Explicit human annotations in existing context JSON. Never changes producer output or invokes models."""
import json
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,StrictBool
from shopping_agent import project_visual as pv,visual_decisions as vd

class ReviewInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    observation_id:str=Field(min_length=1,max_length=200)
    action:Literal['accept','correct','defer','reject']
    reason:str=Field(min_length=1,max_length=1000)
    expected_revision:int=Field(ge=0)
    visible_content:str|None=Field(default=None,max_length=1500)
    limited_inference:str|None=Field(default=None,max_length=1000)
    uncertainty:str|None=Field(default=None,min_length=1,max_length=1000)

def effective(item,annotation):
    value=dict(item)
    if annotation:
        value.update(annotation.get('correction') or {})
        value['review']={'user_accepted':annotation['action'] in {'accept','correct'},'reason':annotation['reason'],
            'revision':annotation['revision'],'at':annotation['at'],'action':annotation['action']}
        value['original_observation']={k:item[k] for k in pv.Observation.model_fields}
    return value

def review(research,task,listing,study,body):
    if not body.reason.strip():raise ValueError('review_reason_required')
    audit=vd.catalog(research,task,listing)
    mark=next((m for m in audit['observations'] if m.get('observation_id')==body.observation_id and m['study_id']==study),None)
    allowed={'requires_human_review','human_review_deferred','human_review_rejected'}
    if not mark or mark['state'] in {'invalid','unknown'} or (mark['state']=='stale' and not set(mark['reasons'])<=allowed):
        raise ValueError('review_source_stale_or_invalid')
    with research.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT s.task_id,s.state,x.context_json,b.goal_revision FROM studies s JOIN study_evidence_context x ON x.study_id=s.id JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.id=? AND s.kind='visual'",(study,)).fetchone()
        if not row or row['task_id']!=task or row['state']!='completed':raise ValueError('review_wrong_scope')
        if row['goal_revision']!=c.execute('SELECT MAX(revision) FROM project_goal_revisions WHERE task_id=?',(task,)).fetchone()[0]:raise ValueError('review_goal_changed')
        ctx=json.loads(row['context_json']);v=ctx['visual']
        if v['approval']['listing_id']!=listing:raise ValueError('review_wrong_listing')
        pv.entries(research,task,listing,pv.stored_approval(v).images)
        if research.signature(next(i for i in research.cards(task) if i['listing_id']==listing))!=v['item_signature']:
            raise ValueError('review_item_changed')
        item=next((o for group in ('observations','withheld') for o in v['result'][group] if o.get('id')==body.observation_id),None)
        if not item:raise ValueError('review_observation_missing')
        previous=v.setdefault('human_reviews',{}).get(body.observation_id,{})
        if previous.get('revision',0)!=body.expected_revision:raise ValueError('review_revision_conflict')
        if body.action in {'accept','correct'} and (item['origin']!='pixels' or item['subject'] in {'function','authenticity','repair'}):
            raise ValueError('images_cannot_verify_internal_claim')
        correction={}
        if body.action=='correct':
            if body.visible_content is None or body.limited_inference is None or body.uncertainty is None:raise ValueError('complete_correction_required')
            correction={k:getattr(body,k) for k in ('visible_content','limited_inference','uncertainty')}
            pv.Observation.model_validate(dict({k:item[k] for k in pv.Observation.model_fields},**correction))
        elif any(getattr(body,k) is not None for k in ('visible_content','limited_inference','uncertainty')):raise ValueError('correction_fields_require_correct_action')
        annotation={'action':body.action,'reason':body.reason.strip(),'revision':body.expected_revision+1,'correction':correction,
            'at':research.clock(),'original_sha256':pv.sha(pv.encode({k:item[k] for k in pv.Observation.model_fields}))}
        v['human_reviews'][body.observation_id]=annotation
        v.setdefault('human_review_history',[]).append(dict(annotation,observation_id=body.observation_id))
        if len(v['human_review_history'])>200:raise ValueError('review_history_limit')
        c.execute('UPDATE study_evidence_context SET context_json=? WHERE study_id=?',(json.dumps(ctx,ensure_ascii=False),study))
    return {'state':'reviewed','action':body.action,'revision':annotation['revision'],'research_started':False,'independently_verified':False}

class FollowupInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    confirmed:StrictBool
    expected_goal_revision:int=Field(ge=1)
    observation_ids:list[str]=Field(min_length=1,max_length=3)
    dependency_signature:str=Field(pattern='^[0-9a-f]{64}$')
    request_key:str=Field(min_length=8,max_length=64)

def followup(research,task,listing,body):
    if body.confirmed is not True:raise ValueError('explicit_followup_required')
    audit=vd.catalog(research,task,listing)
    if audit['goal']['revision']!=body.expected_goal_revision or audit['dependency_signature']!=body.dependency_signature:
        raise ValueError('approved_visual_evidence_changed')
    if set(body.observation_ids)!={b['id'] for b in audit['bundles']} or len(set(body.observation_ids))!=len(body.observation_ids):
        raise ValueError('only_current_human_accepted_visual_evidence')
    study=research.enqueue(task,ids=[listing],question='使用本商品经人工认可的逐图视觉辅助证据，保留限制；不得视为独立核验。',
        request_key=body.request_key,expected_goal_revision=body.expected_goal_revision,use_visual=True,_visual_signature=body.dependency_signature)
    return {'id':study,'state':'queued','visual_execution':False,'report_integration':False}
