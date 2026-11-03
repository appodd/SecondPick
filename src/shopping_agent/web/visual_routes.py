"""C1.1 read/preview/confirm only. No provider, credentials, queue or execution endpoint."""
import hashlib
import json
import secrets
import threading
import time
from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from shopping_agent import project_visual as pv
from shopping_agent.vision import encode, provider_for


class PreviewInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    media_ids:list[int]=Field(min_length=1,max_length=3)
    purpose:str=Field(min_length=1,max_length=500)

class ConfirmInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    approval_id:str=Field(min_length=20,max_length=100)
    scope_sha256:str=Field(pattern='^[0-9a-f]{64}$')
    confirmed:StrictBool


def card(research,task,listing):
    found=next((c for c in research.cards(task) if c['listing_id']==listing),None)
    if found is None:raise ValueError('商品不属于当前项目')
    return found


def local_images(research,task,listing):
    from shopping_agent.visual_decisions import inventory
    value=inventory(research,task,listing)
    return value['images'],len(value['problems'])


def evidence_view(research,task,listing,study_filter=None,*,inv=None,audit=None):
    from shopping_agent import visual_decisions as vd
    inv=inv or vd.inventory(research,task,listing)
    audit=audit or vd.catalog(research,task,listing,inv=inv)
    marks={m['observation_id']:m for m in audit['observations'] if m['observation_id']}
    images,missing=inv['images'],len(inv['problems'])
    valid={(i['media_id'],i['sha256']):i for i in images}
    observations=[];rejected=0;failures=[];runs=[];seen=set()
    with research.db() as conn:
        rows=conn.execute("SELECT s.id,s.state,s.request_json,x.context_json,b.goal_revision FROM studies s JOIN study_evidence_context x ON x.study_id=s.id JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.task_id=? AND s.kind='visual' ORDER BY s.id DESC LIMIT 50",(task,)).fetchall()
        consumers=conn.execute("SELECT id,result_json FROM studies WHERE task_id=? AND kind!='visual' AND state='completed' ORDER BY id DESC LIMIT 100",(task,)).fetchall()
    references={}
    for row in consumers:
        try:
            result=json.loads(row['result_json'] or '{}')
            for a in (result.get('research') or {}).get('assessments',[]):
                if a['listing_id']!=listing:continue
                for j in a['judgments']:
                    for ref in j['evidence_refs']:
                        references.setdefault(ref,[]).append({'study_id':row['id'],'criterion_id':j['criterion_id'],'status':j['status']})
        except (ValueError,KeyError,TypeError):continue
    current_goal=research.goal(task)['revision']
    for row in rows:
        if study_filter is not None and row['id']!=study_filter:continue
        try:
            ctx=json.loads(row['context_json'])['visual'];approval=pv.VisualApproval.model_validate(ctx['approval'])
            if approval.task_id!=task or approval.listing_id!=listing:continue
            runs.append(row['id'])
            if row['state']!='completed':
                failures.append({'study_id':row['id'],'state':row['state'],'reason':'视觉阶段未完成；原文字研究仍可使用。','error_code':ctx.get('failure_code','unavailable')});continue
            receipt=ctx['receipt']
            frozen=json.loads(row['request_json'])['review_context']['visual_inputs']
            if frozen['task_id']!=task or frozen['study_id']!=row['id'] or frozen['goal_revision']!=row['goal_revision']:raise ValueError()
            if receipt.get('mode')=='mock' and not getattr(getattr(research,'visual_executor',None),'mock_transport',None):
                rejected+=1;continue
            for group,items in [('accepted',ctx['result']['observations']),('withheld',ctx['result']['withheld'])]:
                for item in items:
                    try:
                        if item.get('id') in seen:continue
                        image=item['image'];source=valid[(image['media_id'],image['sha256'])]
                        pv.Observation.model_validate({k:item[k] for k in pv.Observation.model_fields})
                        if not any(i['media_id']==image['media_id'] and i['sha256']==image['sha256'] and i['listing_id']==listing and i['evidence_id']==image['evidence_id'] for i in frozen['images']):raise ValueError()
                        if item.get('origin')!='pixels' or item.get('independently_verified') is not False:raise ValueError()
                        bundle=dict(item,task_id=task,goal_revision=row['goal_revision'],producer_study_id=row['id'],
                            receipt=receipt,receipt_sha256=pv.sha(pv.encode(receipt)))
                        refs=pv.visual_refs({'task':{'id':task},'allowed_listing_ids':[listing],
                            'review_context':{'visual_evidence':{'version':1,'task_id':task,'goal_revision':row['goal_revision'],'observations':[bundle]}}})
                        if not refs or image['evidence_id']!=source['evidence_id']:raise ValueError()
                        freshness=marks.get(item['id'],{'state':'unknown','reasons':['metadata_unavailable']})
                        if freshness['state']=='invalid':raise ValueError()
                        fresh=ctx.get('current_usable') and row['goal_revision']==current_goal and research.signature(card(research,task,listing))==ctx['item_signature']
                        needs_review=bool(freshness['reasons']) and set(freshness['reasons'])<={'requires_human_review','human_review_deferred','human_review_rejected'}
                        fresh=bool(fresh and (freshness['state']=='fresh' or needs_review))
                        observations.append({'id':item['id'],'listing_id':listing,'study_id':row['id'],'run_id':str(image['run_id']),
                            'media_id':image['media_id'],'sha256':image['sha256'],'source_url':source['source_url'],
                            'visible_content':item['visible_content'],'limited_inference':item['limited_inference'],
                            'uncertainty':item['uncertainty'],'status':item['status'],'provider':approval.provider,'model':approval.model,
                            'review_state':'historical' if not fresh else 'not_accepted' if item.get('review',{}).get('user_accepted') is False else 'pending_review' if group=='withheld' and not item.get('review',{}).get('user_accepted') else 'accepted',
                            'references':references.get(item['id'],[]),'independently_verified':False,'mode':receipt['mode']})
                        observations[-1].update(freshness=freshness['state'],freshness_reasons=freshness['reasons'])
                        # Read-only semantics from the already validated observation, never new conclusions.
                        observations[-1].update(subject=item['subject'],affects_criteria=item['affects_criteria'],
                            origin='pixels',source_type='image_observation',review_reason=item.get('review',{}).get('reason',''))
                        from shopping_agent.visual_reviews import effective
                        annotation=ctx.get('human_reviews',{}).get(item['id'])
                        final=effective(item,annotation)
                        observations[-1].update(original_visible_content=item['visible_content'],original_limited_inference=item['limited_inference'],
                            original_uncertainty=item['uncertainty'],visible_content=final['visible_content'],limited_inference=final['limited_inference'],
                            uncertainty=final['uncertainty'],human_review_action=(annotation or {}).get('action'),
                            review_revision=(annotation or {}).get('revision',0),review_history=[r for r in ctx.get('human_review_history',[]) if r['observation_id']==item['id']],
                            review_reason=(annotation or {}).get('reason',''),
                            review_state='historical' if not fresh else 'not_accepted' if (annotation or {}).get('action')=='reject' else 'pending_review' if not annotation and not item.get('review',{}).get('user_accepted') or (annotation or {}).get('action')=='defer' else 'accepted')
                        seen.add(item['id'])
                    except (ValueError,KeyError,TypeError):rejected+=1
        except (ValueError,KeyError,TypeError):rejected+=1
    return {'task_id':task,'listing_id':listing,'goal_revision':current_goal,'observations':observations,'study_ids':runs,
        'images':[{'media_id':i['media_id'],'sha256':i['sha256'],'width':i['width'],'height':i['height'],'source_url':i['source_url']} for i in images],
        'unavailable_images':missing,'rejected_observations':rejected,'failures':failures,
        'state':'image_observation' if observations else 'image_available_uninspected' if images else 'no_valid_local_image',
        'dependency_signature':audit['dependency_signature'],'accepted_observation_ids':[b['id'] for b in audit['bundles']],
        'execution_enabled':False,'notice':'AI 图片观察不是独立核验。确认范围不会执行分析或创建研究任务。'}


class ApprovalDesk:
    """Process-local, bounded, single-use preview. Restart invalidates all approvals."""
    def __init__(self,clock=time.time):self.clock=clock;self.lock=threading.RLock();self.pending={};self.confirmed={}

    def scope(self,research,settings,task,listing,body):
        from shopping_agent import visual_decisions as vd
        config=settings.read();provider_for(config.provider)
        if not config.enabled:raise ValueError('视觉配置已禁用')
        if config.model not in provider_for(config.provider).models:raise ValueError('模型没有视觉能力声明')
        policy=research.policy(task)
        if policy['paused'] or policy['completed']:raise ValueError('项目研究已暂停或完成')
        if not body.purpose.strip() or len(set(body.media_ids))!=len(body.media_ids):raise ValueError('请选择不同图片并填写用途')
        values,_=local_images(research,task,listing);lookup={i['media_id']:i for i in values}
        if any(i not in lookup for i in body.media_ids):raise ValueError('图片不可用、未获准或不属于当前商品')
        chosen=[lookup[i] for i in body.media_ids]
        if sum(i['bytes'] for i in chosen)>8*1024*1024:raise ValueError('图片总量超限')
        scope={'task_id':task,'listing_id':listing,'goal_revision':research.goal(task)['revision'],
            'item_signature':research.signature(card(research,task,listing)),
            'purpose':body.purpose.strip(),'provider':config.provider,'model':config.model,
            'timeout_seconds':config.timeout_seconds,'max_output_tokens':config.max_output_tokens,
            'analysis_signature':vd.sha(encode(vd.analysis_basis(config.provider,config.model,body.purpose))),
            'images':[{k:i[k] for k in ('media_id','sha256','evidence_id','source_url','bytes','width','height')} for i in chosen],
            'study_id':None,'execution_enabled':False}
        if getattr(config, 'profile_id', None):
            scope.update(profile_id=config.profile_id, profile_revision=config.profile_revision)
        approval=pv.VisualApproval(id='preview-only',task_id=task,listing_id=listing,goal_revision=scope['goal_revision'],
            item_signature=scope['item_signature'],images=[pv.ImagePermission(media_id=i['media_id'],sha256=i['sha256']) for i in chosen],
            provider=config.provider,model=config.model,approved=True,upload_authorized=True,downstream_text_authorized=True,
            budget_accepted=True,expires_at=time.time()+300,timeout_seconds=config.timeout_seconds,max_output_tokens=config.max_output_tokens,
            analysis_purpose=body.purpose)
        request=pv.prepare_request(research,approval,research.goal(task),card(research,task,listing))
        request=pv.freeze(request,chosen,1,scope['goal_revision'])
        request=request.model_copy(update={'review_context':dict(request.review_context,source_namespace=f'project:{task}')})
        frozen=pv.freeze_input(request,research.config.media_dir,(1<<60)+1,f'project:{task}',scope['goal_revision'],with_images=True)
        payload=pv.build_payload(request,frozen,approval)
        scope.update(request_sha256=pv.sha(encode(payload)),text_input=json.loads(payload['input'][0]['content'][0]['text']),
            instructions=payload['instructions'],schema_sha256=pv.sha(encode(payload['text']['format'])),
            instructions_sha256=pv.sha(payload['instructions'].encode()))
        # Local estimate only: no pricing/account requests; image accounting is a snapshot assumption.
        nonimage=dict(payload,input=[dict(role='user',content=[payload['input'][0]['content'][0]])])
        allowance=max(32000,2*len(encode(nonimage)))
        scope['cost_estimate']={'usd':round((allowance+1024*len(chosen))*.30/1e6+config.max_output_tokens*1.20/1e6,6),
            'price_snapshot':'2026-10-25','text_token_allowance':allowance,'account_hard_cap':False,
            'notice':'本地价格快照估算；非账户扣费上限，超时也可能计费。'}
        return scope

    def preview(self,research,settings,task,listing,body):
        scope=self.scope(research,settings,task,listing,body)
        with self.lock:
            self.pending={k:v for k,v in self.pending.items() if v['expires_at']>self.clock()}
            self.confirmed={k:v for k,v in self.confirmed.items() if v['expires_at']>self.clock()}
            if len(self.pending)>=128:raise ValueError('待确认范围过多，请稍后重试')
            ident=secrets.token_urlsafe(32);entry={'scope':scope,'scope_sha256':pv.sha(pv.encode(scope)),
                'expires_at':self.clock()+300,'used':False}
            self.pending[ident]=entry
        return dict(entry,approval_id=ident)

    def confirm(self,research,settings,task,listing,body):
        with self.lock:
            entry=self.pending.get(body.approval_id)
            if not entry or entry['used'] or entry['expires_at']<=self.clock():raise ValueError('审批缺失、过期或已使用')
            if not body.confirmed:raise ValueError('需要明确确认范围')
            entry['used']=True  # Failed final validation consumes the scope; no silent repair/replay.
            scope=entry['scope']
            if (scope['task_id'],scope['listing_id'])!=(task,listing) or entry['scope_sha256']!=body.scope_sha256:raise ValueError('审批范围不匹配')
            current=self.scope(research,settings,task,listing,PreviewInput(media_ids=[i['media_id'] for i in scope['images']],purpose=scope['purpose']))
            if pv.sha(pv.encode(current))!=entry['scope_sha256']:raise ValueError('目标、配置或图片版本已变化')
            if len(self.confirmed)>=128:raise ValueError('已确认范围过多，请等待过期后重新审查')
            ticket=secrets.token_urlsafe(32)
            self.confirmed[ticket]={'scope':scope,'scope_sha256':entry['scope_sha256'],'expires_at':entry['expires_at'],'execution_used':False}
            return {'state':'approved_not_executed','execution_enabled':False,'study_id':None,
                'execution_ticket':ticket,
                'scope_sha256':entry['scope_sha256'],'notice':'范围已确认，尚未执行；没有创建研究任务。'}


def register_visual_routes(app):
    desk=ApprovalDesk();app.state.visual_approval_desk=desk
    # Operator-controlled in-process seam only; no settings/env/API can enable it.
    app.state.visual_execution_enabled=False
    app.state.visual_execution_transport=None
    def research(request):return request.app.state.project_research
    def local_action(request):
        from shopping_agent.web.app import _same_loopback_origin
        if not _same_loopback_origin(request.headers.get('origin',''),request.url):raise HTTPException(403,'需要来自本机页面的明确操作')

    @app.get('/api/projects/{task}/listings/{listing}/visual-evidence')
    def read(task:int,listing:int,request:Request,study:int|None=None):
        from shopping_agent import visual_decisions as vd
        settings=request.app.state.vision_settings.read()
        inv=vd.inventory(research(request),task,listing)
        audit=vd.catalog(research(request),task,listing,settings,inv=inv)
        result=evidence_view(research(request),task,listing,study,inv=inv,audit=audit)
        result['visual_decision']=vd.plan(research(request),task,listing,settings,audit=audit)
        enabled=settings.enabled;policy=research(request).policy(task)
        result.update(configuration_enabled=enabled,approval_allowed=bool(enabled and not policy['paused'] and not policy['completed'] and result['images']),
            approval_blocked_reason='视觉配置已禁用' if not enabled else '项目研究已暂停或完成' if policy['paused'] or policy['completed'] else '缺少有效本地图片' if not result['images'] else '')
        result['execution_enabled']=request.app.state.visual_execution_enabled is True
        return result

    @app.get('/api/projects/{task}/listings/{listing}/visual-decision')
    def decision(task:int,listing:int,request:Request):
        from shopping_agent.visual_decisions import plan
        return plan(research(request),task,listing,request.app.state.vision_settings.read())

    @app.get('/api/projects/{task}/visual-studies/{study}')
    def read_study(task:int,study:int,request:Request):
        with research(request).db() as conn:
            row=conn.execute("SELECT x.context_json FROM studies s JOIN study_evidence_context x ON x.study_id=s.id WHERE s.id=? AND s.task_id=? AND s.kind='visual'",(study,task)).fetchone()
        if not row:raise HTTPException(404,'没有匹配的视觉运行')
        listing=json.loads(row['context_json'])['visual']['approval']['listing_id']
        return read(task,listing,request,study)

    @app.get('/api/projects/{task}/listings/{listing}/visual-images/{media}')
    def image(task:int,listing:int,media:int,sha256:str,request:Request):
        values=pv.entries(research(request),task,listing,[pv.ImagePermission(media_id=media,sha256=sha256)])
        from pathlib import Path
        data=Path(values[0]['local_path']).read_bytes()
        if pv.sha(data)!=sha256:raise ValueError('图片版本已变化')
        return Response(data,media_type=values[0]['mime'],headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

    @app.post('/api/projects/{task}/listings/{listing}/visual-approval/preview')
    def preview(task:int,listing:int,body:PreviewInput,request:Request):
        local_action(request)
        return desk.preview(research(request),request.app.state.vision_settings,task,listing,body)

    @app.post('/api/projects/{task}/listings/{listing}/visual-approval/confirm')
    def confirm(task:int,listing:int,body:ConfirmInput,request:Request):
        local_action(request)
        return desk.confirm(research(request),request.app.state.vision_settings,task,listing,body)

    from shopping_agent.visual_execution import ExecuteInput, execute
    @app.post('/api/projects/{task}/listings/{listing}/visual-analysis/execute')
    def run_visual(task:int,listing:int,body:ExecuteInput,request:Request):
        local_action(request)
        if request.app.state.visual_execution_enabled is not True:
            raise HTTPException(403,'真实视觉执行开关关闭；范围确认不等于执行授权')
        return execute(request.app,desk,task,listing,body)

    from shopping_agent.visual_reviews import ReviewInput,review,FollowupInput,followup
    @app.post('/api/projects/{task}/listings/{listing}/visual-observations/{study}/review')
    def human_review(task:int,listing:int,study:int,body:ReviewInput,request:Request):
        local_action(request)
        return review(research(request),task,listing,study,body)

    @app.post('/api/projects/{task}/listings/{listing}/visual-evidence/research',status_code=202)
    def manual_followup(task:int,listing:int,body:FollowupInput,request:Request):
        local_action(request)
        return followup(research(request),task,listing,body)
