"""D1 explicit single visual action on existing studies. No new scheduler or configuration switch."""
import json
from pydantic import BaseModel,ConfigDict,Field,StrictBool
from shopping_agent import project_visual as pv

class ExecuteInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    execution_ticket:str=Field(min_length=20,max_length=100)
    scope_sha256:str=Field(pattern='^[0-9a-f]{64}$')
    execution_confirmed:StrictBool
    upload_authorized:StrictBool
    downstream_text_authorized:StrictBool
    budget_accepted:StrictBool

def execute(app,desk,task,listing,body):
    if app.state.visual_execution_enabled is not True:raise ValueError('visual_execution_disabled')
    if not all((body.execution_confirmed,body.upload_authorized,body.downstream_text_authorized,body.budget_accepted)):
        raise ValueError('explicit_execution_upload_downstream_and_budget_authorization_required')
    research=app.state.project_research;store=app.state.vision_settings
    # Reserve once before any expensive validation. Failed final checks cannot repair/replay this action.
    with desk.lock:
        entry=desk.confirmed.get(body.execution_ticket)
        if not entry or entry['execution_used'] or entry['expires_at']<=desk.clock():
            raise ValueError('execution_approval_missing_expired_or_used')
        entry['execution_used']=True
        scope=entry['scope']
        if (scope['task_id'],scope['listing_id'])!=(task,listing) or body.scope_sha256!=entry['scope_sha256']:
            raise ValueError('execution_scope_mismatch')
    from shopping_agent.web.visual_routes import PreviewInput
    current=desk.scope(research,store,task,listing,PreviewInput(media_ids=[i['media_id'] for i in scope['images']],purpose=scope['purpose']))
    if pv.sha(pv.encode(current))!=entry['scope_sha256']:raise ValueError('confirmed_scope_changed')
    if len({i['sha256'] for i in scope['images']})!=len(scope['images']):raise ValueError('duplicate_picture_content_in_execution_scope')
    # Source of every binding is the server-issued range; client cannot substitute item/goal/image/model.
    approval=pv.VisualApproval(id='execution:'+pv.sha(body.execution_ticket.encode()),task_id=task,listing_id=listing,
        goal_revision=scope['goal_revision'],item_signature=scope['item_signature'],
        images=[pv.ImagePermission(media_id=i['media_id'],sha256=i['sha256']) for i in scope['images']],
        provider=scope['provider'],model=scope['model'],approved=True,upload_authorized=True,
        downstream_text_authorized=True,budget_accepted=True,expires_at=float(entry['expires_at']),
        timeout_seconds=scope['timeout_seconds'],max_output_tokens=scope['max_output_tokens'],analysis_purpose=scope['purpose'],request_sha256=scope['request_sha256'])
    config=store.read()
    class ScopedExecutor(pv.ProjectVisualExecutor):
        def check(self,grant):
            if app.state.visual_execution_enabled is not True:raise ValueError('visual_execution_disabled')
            if store.read()!=config:raise ValueError('visual_configuration_changed')
            super().check(grant)
    executor=None
    def credential():
        executor.check(approval)
        pv._validate_permission(research,approval)
        # Last local validation before decryption; never inspect or return the credential to a caller.
        pv.entries(research,task,listing,approval.images)
        return store.credential(approval.provider, expected=config)
    executor=ScopedExecutor(config,credential,enabled=True,mock_transport=app.state.visual_execution_transport)
    # Atomically create+claim this exact study. The normal queue cannot race to claim it or run another item.
    study=pv.enqueue(research,approval,executor=executor,start_now=True)
    with research.db() as conn:
        row=conn.execute('SELECT * FROM studies WHERE id=? AND task_id=?',(study,task)).fetchone()
        context=json.loads(conn.execute('SELECT context_json FROM study_evidence_context WHERE study_id=?',(study,)).fetchone()[0])['visual']
    if row['state']!='running' or context['approval']['id']!=approval.id:
        return {'study_id':study,'state':row['state'],'reused_existing':True,'submitted_by_this_action':False,'report_integration':False}
    pv.run_claimed(research,row,executor=executor)
    with research.db() as conn:
        row=conn.execute('SELECT state,error FROM studies WHERE id=?',(study,)).fetchone()
        visual=json.loads(conn.execute('SELECT context_json FROM study_evidence_context WHERE study_id=?',(study,)).fetchone()[0])['visual']
    return {'study_id':study,'state':row['state'],'reused_existing':False,
        'valid_observations':len(visual.get('result',{}).get('observations',[])),
        'withheld_observations':len(visual.get('result',{}).get('withheld',[])),
        'current_usable':visual.get('current_usable',False),'error_code':row['error'],
        'report_integration':False,'notice':'图片观察不是独立核验；本次结束，不重试、不自动文字复评或整合报告。'}
