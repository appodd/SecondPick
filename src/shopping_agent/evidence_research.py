"""P2 decisions over saved evidence and the existing studies queue, never a loop.

One additive metadata table freezes decision context; studies remain the only
attempt/queue authority. No browser or model calls are made by this module.
"""
import hashlib
import json
import re
from datetime import datetime

from shopping_agent.candidate_context import build_candidate_evidence
from shopping_agent.assessment import ResearchResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS study_evidence_context (
 study_id INTEGER PRIMARY KEY, context_json TEXT NOT NULL);
"""


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def facts(value):
    """Text/attributes are unverified evidence; image URLs never imply vision."""
    monitor = (value.get('monitor_evidence') or {}).get('fields') or {}
    detail = value.get('detail') or {}
    supplement = monitor.get('monitor_detail') or {}
    seller = dict(value.get('seller_fields') or {})
    profile=(value.get('external_source') or {}).get('seller_profile') or {}
    public=monitor.get('seller_public') or {}
    for key,aliases in [('seller_credit_level',('卖家芝麻信用','芝麻信用')),('seller_good_rate',('作为卖家的好评率','好评率')),('seller_realname_verified',('实名认证',))]:
        if seller.get(key) is None:
            seller[key]=next((source[a] for source in (public,profile) for a in aliases if source.get(a) is not None),None)
    rate=seller.get('seller_good_rate')
    if isinstance(rate,str) and re.fullmatch(r'\d+(?:\.\d+)?%',rate.strip()):
        seller['seller_good_rate']=float(rate.strip()[:-1])
    def text(v):
        return ' '.join(str(v or '').split())
    description = detail.get('description') or supplement.get('商品描述') or value.get('search_description') or ''
    return dict(title=text(value.get('title')), price=value.get('price_value'),
        description=text(description), attributes=detail.get('attributes') or supplement.get('商品属性') or {},
        condition=text(value.get('search_condition')),
        statements=[dict(kind=s.get('kind'),text=s.get('statement_text')) for s in value.get('user_statements',[])],
        seller={k:v for k,v in seller.items() if k in {'seller_credit_level','seller_good_rate','seller_realname_verified'} and v is not None})


def assessment(result, listing):
    try:
        return next((a.model_dump() for a in ResearchResult.model_validate(result.get('research')).assessments if a.listing_id==listing), None)
    except (ValueError,TypeError):
        return None


def frozen_evidence(request, listing):
    for item in request.get('evidence',[]):
        if item.get('listing_id')==listing:
            return json.loads(item.get('data',{}).get('evidence_json') or '{}')
    for item in request.get('candidates',[]):
        if item.get('listing_id')==listing:
            return json.loads(item.get('data',{}).get('evidence_json') or '{}')
    return {}


def changes(old, new, budget):
    changed = [k for k in new if old.get(k)!=new[k]]
    # The API sometimes shortens a search-card title; the full description is
    # independent evidence, not a new model/version inferred from truncation.
    if 'title' in changed and old.get('title') and new['title'] and (old['title'].startswith(new['title']) or new['title'].startswith(old['title'])):
        changed.remove('title')
    before, after = old.get('price'),new.get('price')
    crossed = budget is not None and isinstance(before,(int,float)) and isinstance(after,(int,float)) and (before>budget)!=(after>budget)
    meaningful = set(changed)-{'price'}
    labels = dict(title='型号或标题实质变化',description='商品描述或交易说明变化',attributes='商品属性变化',condition='成色声明变化',seller='平台公开风险字段变化',statements='用户补充证据变化')
    reasons = [labels[k] for k in changed if k in labels]
    if crossed:
        reasons.append('挂牌价跨越当前预算硬条件')
    elif 'price' in changed:
        reasons.append('挂牌价变化；尚无跨越硬条件的证据')
    price_gap=not isinstance(before,(int,float)) and isinstance(after,(int,float)) and after>0
    if price_gap:
        reasons.append('原来缺失的有效挂牌价得到补充')
    return dict(fields=changed, important=bool(meaningful or crossed or price_gap), budget_crossed=crossed,
        reason='；'.join(reasons) or '仅时间、图片链接或记录版本变化，没有新增可用于文本判断的事实',
        before={k:old.get(k) for k in changed}, after={k:new[k] for k in changed})


def plan(research, task, goal, policy, cards):
    revision=goal['revision']; index={c['listing_id']:c for c in cards}
    baselines={}; nominees=set(); active={}; attempts={}; contexts={}; reviewed={}
    with research.db() as conn:
        favorites={r[0] for r in conn.execute('SELECT listing_id FROM favorites WHERE task_id=?',(task,))}
        versions={(r['listing_id'],r['signature']):dict(r) for r in conn.execute('SELECT * FROM versions WHERE task_id=?',(task,))}
        report=conn.execute('SELECT r.* FROM reports r JOIN study_goal_bindings b ON b.study_id=r.study_id WHERE r.task_id=? AND b.goal_revision=? ORDER BY r.id DESC LIMIT 1',(task,revision)).fetchone()
        top=set(json.loads(report['candidate_ids_json'])) if report else set()
        for r in conn.execute('SELECT * FROM study_evidence_context'):
            contexts[r['study_id']]=json.loads(r['context_json'])
        for row in conn.execute('SELECT s.*,b.goal_revision FROM studies s LEFT JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.task_id=? ORDER BY s.id',(task,)):
            if row['kind']=='visual' or row['kind'].startswith('seller:'):
                continue
            result=json.loads(row['result_json'] or '{}'); request=json.loads(row['request_json'])
            pairs=json.loads(row['versions_json'])
            if row['state']=='completed':
                nominees.update(result.get('candidate_ids',[]))
            if row['goal_revision']!=revision:
                continue
            if row['state'] in {'queued','running'}:
                for listing,sig in pairs:
                    active[(listing,sig)]=dict(study_id=row['id'],state=row['state'])
            ctx=contexts.get(row['id'],{})
            for item in ctx.get('items',[]):
                if ctx.get('purpose')=='reassessment' and row['state']!='superseded':
                    attempts[(item['listing_id'],item['effective_key'])]=dict(study_id=row['id'],state=row['state'])
            if row['state']=='completed':
                for listing,sig in pairs:
                    a=assessment(result,listing)
                    prior=baselines.get(listing)
                    if prior is None or a is not None or prior['assessment'] is None:
                        baselines[listing]=dict(study_id=row['id'],signature=sig,assessment=a,
                            facts=facts(frozen_evidence(request,listing)),goal_revision=revision,snapshot_at=row['snapshot_at'])
                    if a:
                        reviewed[(listing,sig)]=row['id']
    changed=[c for c in cards if c['listing_id'] in baselines and baselines[c['listing_id']]['signature']!=research.signature(c)]
    evidence=build_candidate_evidence(research.config,task_id=task,listing_ids=[c['listing_id'] for c in changed])['candidates'] if changed else []
    current={e['listing_id']:facts(e) for e in evidence}
    items=[]; ready=[]
    for card in changed:
        listing=card['listing_id']; sig=research.signature(card); prior=baselines[listing]; saved=current[listing]
        delta=changes(prior['facts'],saved,goal['budget']); key=digest(saved)
        line=listing in top or listing in nominees or listing in favorites or prior['assessment'] is not None
        attempted=attempts.get((listing,key)); running=active.get((listing,sig))
        state='priority' if line or delta['budget_crossed'] else 'merge'
        reason=delta['reason']
        if not delta['important']:
            state='not_needed';reason+='；不单独调用模型'
        elif goal['budget'] is not None and isinstance(saved['price'],(int,float)) and saved['price']>goal['budget'] and not delta['budget_crossed']:
            state='not_needed';reason+='；挂牌仍明确超过预算且未跨越该硬条件，暂不自动复评'
        elif not saved['title'] or saved['price'] is None:
            state='needs_evidence';reason+='；缺少可用标题或挂牌价'
        elif not line and not delta['budget_crossed']:
            state='merge';reason+='；暂无明确候选线索，不自动研究全部变化商品'
        elif (listing,sig) in reviewed:
            state='completed';reason='当前目标和证据已有有效逐项判断'
        elif running:
            state=running['state'];reason='已有相同目标、证据的研究正在执行或排队'
        elif attempted:
            state='failed' if attempted['state']=='failed' else 'attempted';reason='同目标、同有效事实已尝试；失败或未形成有效结果时不自动重试，可查看原任务'
        else:
            ready.append((0 if delta['budget_crossed'] else 1 if listing in top else 2 if listing in favorites else 3,listing))
        version=versions.get((listing,sig),{})
        first_pending=min((v['observed_at'] for (i,s),v in versions.items() if i==listing and s!=prior['signature'] and (v['observed_at']>=prior['snapshot_at'] or v['state']=='queued')),default=version.get('observed_at',research.clock()))
        items.append(dict(listing_id=listing,state=state,reason=reason,signature=sig,effective_key=key,
            delta=delta,previous=prior,current_facts=saved,observed_at=first_pending,
            study_id=(running or attempted or {}).get('study_id'),report_candidate=listing in top))
    limit=max(1,min(3,policy['batch_size'])); selected=[i for _,i in sorted(ready)][:limit]
    waited=any((datetime.fromisoformat(research.clock())-datetime.fromisoformat(i['observed_at'])).total_seconds()>=policy['max_wait_seconds'] for i in items if i['listing_id'] in selected)
    with research.source_db() as conn:
        from shopping_agent.project_investigations import held_tasks
        busy=task in held_tasks(conn,include_review=False)
    with research.db() as conn:
        any_active=conn.execute("SELECT 1 FROM studies WHERE task_id=? AND state IN ('queued','running')",(task,)).fetchone() is not None
        last=conn.execute("SELECT s.finished_at FROM studies s JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.task_id=? AND b.goal_revision=? AND b.proof='automatic_evidence' AND s.kind='reassessment' AND s.finished_at IS NOT NULL AND s.state IN ('completed','failed') ORDER BY s.id DESC LIMIT 1",(task,revision)).fetchone()
        cooling=bool(last) and (datetime.fromisoformat(research.clock())-datetime.fromisoformat(last['finished_at'])).total_seconds()<policy['max_wait_seconds']
        failed=conn.execute("SELECT 1 FROM studies s JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.task_id=? AND b.goal_revision=? AND s.kind IN ('initial','incremental') AND s.state='failed'",(task,revision)).fetchone() is not None
    gate=('completed' if policy['completed'] else 'paused' if policy['paused'] else 'unauthorized' if not policy['auto_research'] else
          'investigation' if busy else 'active' if any_active else 'failed' if failed else 'waiting' if selected and (cooling or len(ready)<limit and not waited) else 'ready' if selected else 'idle')
    reason=dict(completed='项目已结束',paused='研究已暂停；保留新证据，不启动模型',unauthorized='未授权自动研究',investigation='调查尚未执行完毕，等待原任务',active='已有研究任务，合并等待',failed='常规研究失败，须先处理原任务',waiting='等待既有批次门槛或最长等待时间',ready='有重要新证据，可有限复评',idle='目前没有需要自动复评的证据变化')[gate]
    if gate=='waiting' and cooling:
        reason='上一有限复评刚结束，按既有等待窗口合并后续变化，不集中清空历史积压'
    return dict(goal_revision=revision,items=items,listing_ids=selected,batch_limit=limit,gate=gate,reason=reason,automatic_ready=gate=='ready')


def request_key(task,revision,items,purpose='reassessment',base_report=None):
    # The queue key distinguishes never-executed superseded snapshots. Separate
    # per-item effective_key checks still forbid repeating a spent AI attempt.
    return f'evidence-{purpose}:{task}:{revision}:'+digest(dict(items=sorted((i['listing_id'],i['effective_key'],i.get('signature')) for i in items),base_report=base_report))


def separate_followup(work, evidence_work):
    """One owner per revisit: do not advertise the same item in two queues."""
    ids={i['listing_id'] for i in evidence_work['items']}
    for item in work['items']:
        if item['listing_id'] in ids and item['state'] not in {'evaluated','queued','running'}:
            work['counts'][item['state']]-=1
            work['counts']['no_priority']+=1
            item.update(state='no_priority',reason='新证据变化由有限复评独立判断，不重复安排历史补研')
    work['listing_ids']=[i for i in work['listing_ids'] if i not in ids]
    if not work['listing_ids'] and work['gate'] in {'ready','waiting'}:
        work.update(gate='idle',reason='变化商品已交由新证据复评判断；没有排队不代表没有研究价值',automatic_ready=False)
    return work


def decision_impacts(item, new, snapshot):
    """Require changed facts AND a sourced, decision-relevant match change.

Nomination is a request to compare, not a purchase recommendation. UNKNOWN
alone cannot distinguish missing information from a stricter writing standard.
Keep such updates visible, without automatically spending a report call.
"""
    from shopping_agent.assessment import input_refs_from_snapshot
    delta = item['delta']
    if not delta.get('important'):
        return []
    old = (item.get('previous') or {}).get('assessment')
    if not old:
        return []  # First item assessment is not a demonstrated change of advice.
    previous = {j['criterion_id']: j for j in old['judgments']}
    hard = {c['criterion_id'] for c in snapshot.get('current_criteria',[]) if c.get('priority')=='hard'}
    refs = input_refs_from_snapshot(snapshot)
    impacts = []
    for judgment in new['judgments']:
        prior = previous.get(judgment['criterion_id'])
        if not prior or prior['status'] == judgment['status'] or judgment['status'] == 'UNKNOWN':
            continue
        # A changed excerpt must actually contain the changed facts, rather than
        # a citation only to an unchanged search card / prior model opinion.
        bound = []
        for ref in judgment['evidence_refs']:
            excerpt = refs.get(ref)
            if not excerpt or excerpt.get('listing_id') != item['listing_id']:
                continue
            payload = json.loads(excerpt.get('data', {}).get('evidence_json') or '{}')
            current = facts(payload)
            statement=dict(kind=payload.get('kind'),text=payload.get('statement_text'))
            new_statement=('statements' in delta['fields'] and statement.get('text')
                and statement in delta['after'].get('statements',[]) and statement not in delta['before'].get('statements',[]))
            if new_statement or any(delta['after'].get(field) not in (None,'',{},[])
                   and current.get(field) == delta['after'].get(field) and current.get(field) != delta['before'].get(field)
                   for field in delta['fields']):
                bound.append(ref)
        if not bound:
            continue
        negative = judgment['status'] in {'NOT_MET', 'CONFLICT'} and (
            judgment['criterion_id'] in hard or old['conclusion'] != new['conclusion'])
        improved = judgment['status'] == 'MET' and old['conclusion'] != new['conclusion'] and new['conclusion'] in {'conditional', 'consider'}
        if negative or improved:
            impacts.append(dict(criterion_id=judgment['criterion_id'], before=prior['status'], after=judgment['status'],
                reason=judgment['reason'], evidence_refs=bound, changed_fields=delta['fields']))
    return impacts


def integration(research, task, goal, cards):
    """A bounded report integration plan, with no invented model conclusion."""
    from shopping_agent import project_goals as goals
    index={c['listing_id']:c for c in cards}; latest={}
    with research.db() as conn:
        report=goals.report_for(conn,task,goal['revision'])
        if report is None:
            return dict(state='none',reason='暂无当前目标报告',listing_ids=[])
        top=set(json.loads(report['candidate_ids_json']))
        for row in conn.execute("SELECT s.*,x.context_json FROM studies s JOIN study_evidence_context x ON x.study_id=s.id JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.task_id=? AND b.goal_revision=? AND s.state='completed' ORDER BY s.id",(task,goal['revision'])):
            ctx=json.loads(row['context_json'])
            if ctx.get('purpose')!='reassessment' or row['id']<=report['study_id']:
                continue
            result=json.loads(row['result_json'] or '{}')
            for i in ctx['items']:
                listing=i['listing_id']; a=assessment(result,listing)
                if a and listing in index and i['signature']==research.signature(index[listing]):
                    latest[listing]=dict(item=i,assessment=a,study_id=row['id'],nominated=listing in result.get('candidate_ids',[]),
                        decision_impacts=decision_impacts(i,a,json.loads(row['request_json'])))
        important=[]
        for listing,entry in latest.items():
            new=entry['assessment']
            if entry['decision_impacts'] and (listing in top or entry['nominated'] or new['conclusion'] in {'consider','not_met'}):
                important.append(listing)
        if not important:
            return dict(state='none',reason='尚无满足自动整合口径的实质变化依据；保留逐项更新，不因重复提名或 UNKNOWN 口径变化重写报告',listing_ids=[],updates=list(latest.values()))
        scope=sorted(top|set(important))
        unavailable=len(scope)<2 or len(scope)>min(20,research.policy(task)['batch_size']) or not set(scope)<=set(index)
        if not unavailable:
            key=request_key(task,goal['revision'],[dict(listing_id=i,effective_key=research.signature(index[i])) for i in scope],'integration',report['id'])
            prior=conn.execute('SELECT id,state,error FROM studies WHERE task_id=? AND request_key=?',(task,key)).fetchone()
            if prior and prior['state']!='superseded':
                return dict(state={'queued':'scheduled','running':'running','failed':'failed','completed':'completed'}.get(prior['state'],'pending'),
                    reason=prior['error'] or '重要变化整合已进入既有研究记录，不重复创建',listing_ids=scope,important_ids=important,study_id=prior['id'],updates=list(latest.values()))
        policy=research.policy(task)
        blocked=bool(policy['paused'] or not policy['auto_research'] or policy['completed'])
        return dict(state='pending' if unavailable or blocked else 'ready',reason='重要变化待整合；研究调度已暂停、未授权或项目已结束，尚未执行' if blocked else '重要商品判断变化，报告待整合' if unavailable else '重要判断变化，按既有队列合并整合当前候选与原报告',
            listing_ids=scope,important_ids=important,base_report_id=report['id'],base_content=report['content'],updates=list(latest.values()))
