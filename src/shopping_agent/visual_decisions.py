"""Deterministic visual freshness/planning. No network, credentials, queue loop or DDL."""
from dataclasses import dataclass
import hashlib
import json
import math
import re
from pathlib import Path
import time

from shopping_agent.image_safety import ImageLimits, checked_url
from shopping_agent.vision import encode, sha, provider_for


@dataclass(frozen=True)
class Limits:
    max_images: int = 3
    max_total_bytes: int = 8 * 1024 * 1024
    max_item_attempts: int = 2
    max_history: int = 100

    def __post_init__(self):
        if not (1 <= self.max_images <= 3 and 1 <= self.max_total_bytes <= 8*1024*1024
                and 1 <= self.max_item_attempts <= 2 and 1 <= self.max_history <= 200):
            raise ValueError('visual_limits_out_of_bounds')


def profile(research, settings=None):
    if settings is not None:return settings
    reader=getattr(research,'visual_settings_reader',None)
    if reader is not None:
        try:return reader()  # Non-secret model configuration, not an execution or key supplier.
        except (ValueError,OSError):return None
    return getattr(getattr(research, 'visual_executor', None), 'settings', None)


def analysis_basis(provider, model, purpose):
    from shopping_agent import project_visual as pv
    return dict(protocol=pv.PROTOCOL, instructions_sha256=sha(pv.analysis_instructions().encode()),
                schema_sha256=sha(encode(pv.analysis_schema())), provider=provider, model=model,
                purpose=' '.join(purpose.split()))


def goal_signature(goal):
    return sha(encode({k:goal[k] for k in ('goal','budget','hard_json','soft_json')}))


def analysis_stamp(approval, goal):
    basis=analysis_basis(approval.provider,approval.model,approval.analysis_purpose)
    return dict(version=1, basis=basis, signature=sha(encode(basis)),
                goal_revision=goal['revision'], goal_signature=goal_signature(goal),
                item_signature=approval.item_signature)


def attempt_key(approval, images, stamp):
    return 'project-visual-c2:'+sha(encode([approval.task_id,approval.listing_id,approval.goal_revision,
        approval.item_signature,stamp['signature'],sorted({i['sha256'] for i in images})]))


def inventory(research, task, listing):
    """Current local bytes only. Duplicate media/URLs do not create extra pixel samples."""
    from shopping_agent import project_visual as pv
    if listing not in {c['listing_id'] for c in research.cards(task)}:raise ValueError('image_outside_project')
    with research.source_db() as conn:
        rows=conn.execute("SELECT id,local_path,source_url FROM media_assets WHERE listing_id=? AND media_type='product_image_url' ORDER BY id LIMIT 21",(listing,)).fetchall()
    images=[];problems=[]
    for row in rows[:20]:
        state='invalid'
        try:
            if not row['local_path']:
                state='unknown';raise ValueError('url_only')
            p=Path(row['local_path'])
            checked_url(row['source_url'],ImageLimits())
            if p.is_symlink() or not p.resolve().is_relative_to(research.config.media_dir.resolve()):raise ValueError('image_path_outside_store')
            if not p.is_file():
                state='unknown';raise ValueError('local_file_missing')
            if p.stat().st_size>ImageLimits().max_bytes:raise ValueError('image_resource_limit')
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            images.extend(pv.entries(research,task,listing,[pv.ImagePermission(media_id=row['id'],sha256=digest)]))
        except (ValueError,OSError) as exc:
            # No exception text, paths or provider data in public diagnostics.
            problems.append(dict(media_id=row['id'],state=state,reason='image_validation_failed' if state=='invalid' else 'image_content_unavailable'))
    unique={}
    for image in images:unique.setdefault(image['sha256'],image)
    return dict(images=images, unique=list(unique.values()), problems=problems,
                duplicates=len(images)-len(unique), truncated=len(rows)>20)


def guard_attempts(conn, approval, images, stamp, limits=None):
    """Called inside the existing enqueue transaction; no second queue or claim table."""
    limits=limits or Limits()
    key=attempt_key(approval,images,stamp)
    prior=conn.execute('SELECT id FROM studies WHERE request_key=?',(key,)).fetchone()
    if prior:return prior[0]
    rows=conn.execute("SELECT s.id,x.context_json FROM studies s JOIN study_goal_bindings b ON b.study_id=s.id LEFT JOIN study_evidence_context x ON x.study_id=s.id WHERE s.task_id=? AND s.kind='visual' AND b.goal_revision=? ORDER BY s.id DESC LIMIT ?",
                      (approval.task_id,approval.goal_revision,limits.max_history+1)).fetchall()
    if len(rows)>limits.max_history:raise ValueError('visual_history_limit_requires_manual_review')
    hashes={i['sha256'] for i in images};count=0
    for row in rows:
        try:
            visual=json.loads(row['context_json'])['visual'];old=visual['approval']
            if old['listing_id']!=approval.listing_id:continue
            count+=1
            overlap=hashes & {i['sha256'] for i in visual['images']}
            if not overlap:continue
            if not visual.get('analysis'):raise ValueError('legacy_visual_attempt_requires_manual_review')
            if visual['analysis']['signature']==stamp['signature']:
                raise ValueError('overlapping_visual_pixels_already_attempted')
        except (KeyError,TypeError,json.JSONDecodeError):
            raise ValueError('visual_attempt_history_unverifiable') from None
    if count>=limits.max_item_attempts:raise ValueError('visual_item_attempt_limit')
    return None


def freshness(row, visual, item, group, *, task, listing, goal, card_signature, inv, settings, purpose):
    """Validate provenance before evaluating semantic freshness. Never trusts model freshness."""
    from shopping_agent import project_visual as pv
    result=dict(study_id=row['id'],observation_id=item.get('id'),state='unknown',reasons=[],usable=False)
    def finish(state,*reasons):return dict(result,state=state,reasons=list(reasons))
    try:
        approval=pv.stored_approval(visual)
        image=item['image'];receipt=visual['receipt']
        frozen=json.loads(row['request_json'])['review_context']['visual_inputs']
        if (row['task_id']!=task or row['binding_task']!=task or visual['study_id']!=row['id']
                or approval.task_id!=task or approval.listing_id!=listing
                or approval.goal_revision!=row['goal_revision'] or frozen['goal_revision']!=row['goal_revision']
                or frozen['task_id']!=task or frozen['study_id']!=row['id']):
            return finish('invalid','wrong_scope_binding')
        pv.Observation.model_validate({k:item[k] for k in pv.Observation.model_fields})
        match=re.fullmatch(r'visual:(\d+):(\d+):([1-3]):([0-9a-f]{16})',item['id'])
        original={k:item[k] for k in pv.Observation.model_fields}
        if not match or (int(match[1]),int(match[2]),match[4])!=(listing,row['id'],sha(encode(original))[:16]):
            return finish('invalid','observation_content_or_identity_changed')
        if item['source_type']!='image_observation' or item['origin']!='pixels' or item['independently_verified'] is not False:
            return finish('invalid','not_a_pixel_observation')
        if not any(e['listing_id']==listing and e['media_id']==image['media_id'] and e['sha256']==image['sha256'] and e['evidence_id']==image['evidence_id'] for e in frozen['images']):
            return finish('invalid','not_in_frozen_attachments')
        receipt_scope={k:receipt[k] for k in ('success','http_status','client_submissions','actual_inputs','request_body_sha256','response_id','mode')}
        bundle=dict(item,task_id=task,goal_revision=row['goal_revision'],producer_study_id=row['id'],
                    producer=approval.provider,model=approval.model,
                    receipt=receipt_scope,receipt_sha256=sha(encode(receipt_scope)))
        pv.visual_refs({'task':{'id':task},'allowed_listing_ids':[listing], 'review_context':{'visual_evidence':{
            'version':1,'task_id':task,'goal_revision':row['goal_revision'],'observations':[bundle]}}})
        if row['state']!='completed':return finish('invalid','execution_not_completed')
        originals=[e for e in inv['images'] if e['media_id']==image['media_id']]
        if originals and not any(e['sha256']==image['sha256'] for e in originals):return finish('stale','image_content_changed')
        if not originals:
            problem=next((p for p in inv['problems'] if p['media_id']==image['media_id']),None)
            return finish((problem or {}).get('state','unknown'),'original_image_unavailable')
        override=visual.get('observation_reviews',{}).get(item['id'],{})
        if override.get('state') in {'invalid','revoked'} or item.get('review',{}).get('user_accepted') is False:
            return finish('invalid','observation_rejected_or_revoked')
        if override.get('state')=='questioned':return finish('stale','observation_questioned')
        stamp=visual.get('analysis')
        if not stamp or not settings:return finish('unknown','analysis_version_unrecorded' if not stamp else 'current_model_unknown')
        if stamp.get('version')!=1:return finish('unknown','analysis_version_unsupported')
        if stamp['signature']!=sha(encode(stamp['basis'])):
            return finish('invalid','invalid_analysis_stamp')
        if (stamp.get('goal_revision')!=row['goal_revision'] or stamp['basis'].get('provider')!=approval.provider
                or stamp['basis'].get('model')!=approval.model or stamp['basis'].get('purpose')!=' '.join(approval.analysis_purpose.split())
                or receipt.get('model')!=approval.model):return finish('invalid','analysis_scope_mismatch')
        expected=analysis_basis(settings.provider,settings.model,purpose)
        if stamp['signature']!=sha(encode(expected)):
            changed=[k for k in expected if stamp['basis'].get(k)!=expected[k]]
            return finish('stale',*['analysis_'+k+'_changed' for k in changed])
        if row['goal_revision']!=goal['revision'] or stamp.get('goal_signature')!=goal_signature(goal):return finish('stale','goal_changed')
        if (stamp.get('item_signature')!=visual['item_signature'] or approval.item_signature!=visual['item_signature']):return finish('invalid','invalid_item_binding')
        if visual['item_signature']!=card_signature:return finish('stale','item_evidence_changed')
        if not visual.get('current_usable'):return finish('stale','producer_not_current')
        annotation=visual.get('human_reviews',{}).get(item['id'])
        if annotation:
            if annotation.get('original_sha256')!=sha(encode(original)):return finish('invalid','human_review_original_mismatch')
            if annotation['action']=='reject':return finish('stale','human_review_rejected')
            if annotation['action']=='defer':return finish('stale','human_review_deferred')
            if annotation['action'] not in {'accept','correct'}:return finish('invalid','invalid_human_review')
            from shopping_agent.visual_reviews import effective
            bundle.update(effective(item,annotation))
            bundle['human_review']=annotation
        elif item.get('review',{}).get('user_accepted') is not True:
            return finish('stale','requires_human_review')
        if item['status']!='visible':return finish('fresh','valid_uncertainty_not_positive_evidence')
        if not item['visible_content'].strip():return finish('invalid','empty_observation')
        return dict(result,state='fresh',reasons=['same_pixels_goal_and_analysis'],usable=True,bundle=bundle,
                    sha256=image['sha256'],media_id=image['media_id'])
    except KeyError:return finish('unknown','incomplete_observation_metadata')
    except (ValueError,TypeError,AttributeError):return finish('invalid','observation_validation_failed')


def catalog(research,task,listing,settings=None,*,purpose=None,inv=None,limits=None):
    from shopping_agent import project_visual as pv
    limits=limits or getattr(research,'visual_limits',Limits());requested_purpose=purpose;purpose=purpose or pv.DEFAULT_PURPOSE
    settings=profile(research,settings);inv=inv or inventory(research,task,listing)
    card=next(c for c in research.cards(task) if c['listing_id']==listing);goal=research.goal(task)
    with research.db() as conn:
        rows=conn.execute("SELECT s.*,b.task_id AS binding_task,b.goal_revision,x.context_json FROM studies s LEFT JOIN study_goal_bindings b ON b.study_id=s.id LEFT JOIN study_evidence_context x ON x.study_id=s.id WHERE s.task_id=? AND s.kind='visual' ORDER BY s.id DESC LIMIT ?",(task,limits.max_history+1)).fetchall()
    observations=[];attempts=[];seen=set();count=0
    for row in rows[:limits.max_history]:
        try:
            visual=json.loads(row['context_json'])['visual']
            if visual['approval']['listing_id']!=listing:continue
            count+=int(row['goal_revision']==goal['revision'])
            stamp=visual.get('analysis') or {}
            if not isinstance(stamp,dict):raise ValueError('invalid_analysis_metadata')
            attempts.append(dict(study_id=row['id'],state=row['state'],goal_revision=row['goal_revision'],
                signature=stamp.get('signature'),item_signature=visual.get('item_signature'),
                hashes=sorted({i['sha256'] for i in visual['images']})))
            if row['state']!='completed' or not any((visual.get('result') or {}).get(k) for k in ('observations','withheld')):
                observations.append(dict(study_id=row['id'],observation_id=None,
                    state='invalid' if row['state']=='failed' else 'unknown',usable=False,
                    reasons=['execution_failed' if row['state']=='failed' else 'no_completed_observations']))
            for group in ('observations','withheld'):
                for item in (visual.get('result') or {}).get(group,[]):
                    if not isinstance(item,dict):
                        observations.append(dict(study_id=row['id'],observation_id=None,state='invalid',usable=False,reasons=['invalid_observation_shape']));continue
                    if item.get('id') in seen and item.get('id'):continue
                    mark=freshness(row,visual,item,group,task=task,listing=listing,goal=goal,
                        card_signature=research.signature(card),inv=inv,settings=settings,purpose=requested_purpose or pv.stored_approval(visual).analysis_purpose)
                    if mark['state']=='fresh' and visual.get('receipt',{}).get('mode')=='mock' and not getattr(getattr(research,'visual_executor',None),'mock_transport',None):
                        mark=dict(mark,state='unknown',usable=False,reasons=['mock_not_real_evidence']);mark.pop('bundle',None)
                    observations.append(mark)
                    if item.get('id'):seen.add(item['id'])
        except (ValueError,KeyError,TypeError,AttributeError):
            observations.append(dict(study_id=row['id'],observation_id=None,state='unknown',usable=False,reasons=['incomplete_study_metadata']))
    usable=[];pixels=set()
    for mark in observations:
        if mark['usable'] and mark['sha256'] not in pixels:
            usable.append(mark['bundle']);pixels.add(mark['sha256'])
    dependency=sha(encode(sorted((b['id'],sha(encode(b))) for b in usable)))
    return dict(observations=observations,bundles=usable,attempts=attempts,item_attempts=count,
                truncated=len(rows)>limits.max_history,inventory=inv,goal=goal,card=card,
                dependency_signature=dependency,settings=settings,purpose=purpose)


def mark_observation(research,task,study,observation_id,*,state,reason):
    """Explicit local human annotation; preserves original result and receipt."""
    if state not in {'revoked','invalid','questioned'} or not str(reason).strip():raise ValueError('explicit_visual_annotation_required')
    with research.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute("SELECT x.context_json FROM studies s JOIN study_evidence_context x ON x.study_id=s.id WHERE s.id=? AND s.task_id=? AND s.kind='visual'",(study,task)).fetchone()
        if not row:raise ValueError('visual_annotation_wrong_scope')
        ctx=json.loads(row[0]);visual=ctx['visual']
        if not any(o.get('id')==observation_id for k in ('observations','withheld') for o in visual.get('result',{}).get(k,[])):
            raise ValueError('visual_observation_missing')
        visual.setdefault('observation_reviews',{})[observation_id]={'state':state,'reason':str(reason)[:1000],'at':research.clock()}
        conn.execute('UPDATE study_evidence_context SET context_json=? WHERE study_id=?',(json.dumps(ctx,ensure_ascii=False),study))


def plan(research,task,listing,settings=None,*,explicit_request=False,budget_accepted=False,
         remaining_requests=None,approval=None,now=None,purpose=None,limits=None,audit=None):
    from shopping_agent import project_visual as pv
    from shopping_agent.evidence_research import assessment
    limits=limits or getattr(research,'visual_limits',Limits());audit=audit or catalog(research,task,listing,settings,purpose=purpose,limits=limits)
    inv=audit['inventory'];goal=audit['goal'];card=audit['card'];settings=audit['settings'];purpose=audit['purpose']
    policy=research.policy(task);gates=[];reasons=[];priority=[]
    with research.db() as conn:
        favorite=bool(conn.execute('SELECT 1 FROM favorites WHERE task_id=? AND listing_id=?',(task,listing)).fetchone())
        rows=conn.execute("SELECT s.id,s.state,s.result_json,s.request_json,s.versions_json,b.goal_revision FROM studies s JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.task_id=? AND s.kind!='visual' ORDER BY s.id DESC LIMIT 100",(task,)).fetchall()
    signature=research.signature(card);prior=None;consumed=set();cited=set();in_progress=False;dependents=[]
    marks={m['observation_id']:m for m in audit['observations'] if m['observation_id']}
    for row in rows:
        try:
            if row['goal_revision']!=goal['revision']:continue
            request=json.loads(row['request_json']);result=json.loads(row['result_json'] or '{}')
            if row['state']=='completed' and prior is None and [listing,signature] in json.loads(row['versions_json']):prior=assessment(result,listing)
            refs={o['id'] for o in request.get('review_context',{}).get('visual_evidence',{}).get('observations',[]) if o['listing_id']==listing}
            if row['state']=='completed' and [listing,signature] in json.loads(row['versions_json']) and assessment(result,listing):
                consumed|=refs
                used={ref for j in assessment(result,listing)['judgments'] for ref in j['evidence_refs'] if ref in refs}
                cited|=used
                if used:
                    states={marks.get(ref,{}).get('state','unknown') for ref in used}
                    status=next(s for s in ('invalid','unknown','stale','fresh') if s in states)
                    dependents.append(dict(study_id=row['id'],state=status,observation_ids=sorted(used)))
            if row['state'] in {'queued','running'} and listing in request.get('allowed_listing_ids',[]):in_progress=True
            if row['state']=='completed' and listing in result.get('candidate_ids',[]):priority.append('historical_nomination')
        except (ValueError,KeyError,TypeError):continue
    if favorite:priority.append('favorite')
    if explicit_request:priority.append('explicit_request')
    if prior and prior['conclusion'] in {'consider','conditional'}:priority.append('text_candidate')
    if prior and any(j['status']=='CONFLICT' for j in prior['judgments']):priority.append('structured_conflict')
    usable=audit['bundles'];usable_hashes={b['image']['sha256'] for b in usable}
    old_hashes={h for a in audit['attempts'] for h in a['hashes']}
    new_images=[i for i in inv['unique'] if i['sha256'] not in old_hashes]
    all_attempted={h for a in audit['attempts'] if a['goal_revision']==goal['revision'] and settings and a['signature']==sha(encode(analysis_basis(settings.provider,settings.model,purpose))) for h in a['hashes']}
    candidates=[i for i in inv['unique'] if i['sha256'] not in usable_hashes and i['sha256'] not in all_attempted]
    selected=[];total=0
    for image in candidates:
        if len(selected)>=limits.max_images:break
        if total+image['bytes']>limits.max_total_bytes:continue
        selected.append(image);total+=image['bytes']
    if settings is None:gates.append('current_model_unknown')
    else:
        if not settings.enabled:gates.append('visual_disabled')
        try:
            if not provider_for(settings.provider).supports(settings.model):gates.append('model_not_declared_visual')
        except ValueError:gates.append('provider_unavailable')
        if settings.timeout_seconds>300 or settings.max_output_tokens>3000:gates.append('configured_resource_limit')
    if policy['paused'] or policy['completed']:gates.append('project_paused_or_completed')
    if not budget_accepted:gates.append('budget_not_confirmed')
    if type(remaining_requests) is not int or remaining_requests<1:gates.append('no_local_request_allowance')
    # Range-only C1.1 tickets cannot become upload or execution approval.
    if approval is None:gates.append('execution_approval_missing')
    else:
        try:
            grant=pv.VisualApproval.model_validate(approval)
            if grant.expires_at<=(now if now is not None else time.time()):gates.append('execution_approval_expired')
            if (grant.task_id,grant.listing_id,grant.goal_revision,grant.item_signature)!=(task,listing,goal['revision'],signature):gates.append('execution_approval_scope_changed')
            if settings and (grant.provider!=settings.provider or grant.model!=settings.model or grant.analysis_purpose!=purpose):gates.append('execution_approval_analysis_changed')
            if settings and (grant.timeout_seconds,grant.max_output_tokens)!=(settings.timeout_seconds,settings.max_output_tokens):gates.append('execution_approval_resource_changed')
            if {(i.media_id,i.sha256) for i in grant.images}!={(i['media_id'],i['sha256']) for i in selected}:gates.append('execution_approval_images_changed')
            if len({i.media_id for i in grant.images})!=len(grant.images):gates.append('execution_approval_duplicate_images')
        except ValueError:gates.append('scope_only_or_invalid_execution_approval')
    if audit['truncated'] or inv['truncated']:gates.append('history_or_image_scan_limit')
    if (any('incomplete_study_metadata' in m['reasons'] for m in audit['observations']) or
            any(a['goal_revision']==goal['revision'] and not a['signature'] and set(a['hashes']) & {i['sha256'] for i in selected} for a in audit['attempts'])):
        gates.append('unverifiable_attempt_history')
    if audit['item_attempts']>=limits.max_item_attempts:gates.append('item_attempt_limit')
    if candidates and not selected:gates.append('input_size_limit')
    unresolved=not prior or any(j['status'] in {'UNKNOWN','CONFLICT'} for j in prior['judgments'])
    price=card.get('price_value')
    outside_budget=goal['budget'] is not None and isinstance(price,(int,float)) and math.isfinite(price) and price>goal['budget']
    if in_progress or any(a['state'] in {'queued','running'} for a in audit['attempts']):
        action='in_progress';reasons.append('已有研究或视觉任务，不能重复安排')
    elif usable and not (new_images and priority and (unresolved or explicit_request)):
        action='skip' if {b['id'] for b in usable}<=consumed else 'reuse'
        reasons.append(('新鲜观察已被当前有效文字研究引用' if {b['id'] for b in usable}<=cited else '新鲜观察已提供给当前有效文字研究；不代表全部被引用，不重复安排') if action=='skip' else '复用同图、同目标与同分析版本的有效观察，不重传图片')
    elif not inv['unique']:
        action='skip';reasons.append('没有通过校验且可解码的本地图片；URL 不等于可用像素')
    elif prior and prior['conclusion']=='not_met' and not explicit_request:
        action='skip';reasons.append('现有文字判断已明确不满足条件，缺少继续看图价值')
    elif outside_budget and not explicit_request and 'structured_conflict' not in priority:
        action='skip';reasons.append('现有有效挂牌超出当前预算；没有支持优先看图的异常或用户定向需求')
    elif not priority:
        action='skip';reasons.append('缺少候选、用户指定或可追溯异常线索；新图片本身不等于研究价值')
    elif candidates and not selected:
        action='skip';reasons.append('候选图片超过本次本地输入总量限制，需要缩小范围')
    elif not selected:
        action='manual_review';reasons.append('同条件图片已尝试、失败或尚待复核；不自动重试同图')
    elif not new_images and not explicit_request and 'structured_conflict' not in priority:
        action='manual_review';reasons.append('只有目标、分析口径或文字绑定变化；先确认是否需重新看图，不机械重发同图')
    else:
        action='needs_analysis';reasons.append('有候选/异常线索且存在可补充可见信息的图片；实际增量价值尚需审批确认')
    public_marks=[{k:v for k,v in m.items() if k!='bundle'} for m in audit['observations']]
    return dict(task_id=task,listing_id=listing,goal_revision=goal['revision'],action=action,
        state='blocked' if action=='needs_analysis' and gates else 'planned' if action=='needs_analysis' else action,
        reasons=reasons,priority_reasons=sorted(set(priority)),gates=list(dict.fromkeys(gates)),
        execution_enabled=False,automatic_ready=False,selected_images=[{k:i[k] for k in ('media_id','sha256','bytes','width','height')} for i in selected] if action=='needs_analysis' else [],
        reusable_observation_ids=[b['id'] for b in usable],freshness=public_marks,
        provided_observation_ids=sorted(consumed),cited_observation_ids=sorted(cited),
        dependent_studies=dependents,
        attempt_states=[{k:a[k] for k in ('study_id','state','goal_revision')} for a in audit['attempts']],
        dependency_signature=audit['dependency_signature'],same_content_duplicates=inv['duplicates'],
        new_content_count=len(new_images),image_problems=inv['problems'],
        limits=dict(max_images=limits.max_images,max_total_bytes=limits.max_total_bytes,max_item_attempts_per_goal=limits.max_item_attempts,
                    attempts_for_goal=audit['item_attempts'],timeout_seconds=min(300,settings.timeout_seconds) if settings else 300,max_output_tokens=min(3000,settings.max_output_tokens) if settings else 3000,
                    max_observations=3,response_bytes=1024*1024),
        budget_notice='仅本地请求许可与资源门禁，不是服务商账单硬上限；本层不会提交请求')
