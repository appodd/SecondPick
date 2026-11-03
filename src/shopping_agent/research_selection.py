"""Explainable, bounded follow-up planning over saved evidence; no side effects.

Report membership is exposure only. One follow-up attempt per goal/evidence pair,
recorded by the existing studies queue, survives restart and incomplete answers.
"""
import hashlib
import json
import math
import re
from datetime import datetime, timezone

from shopping_agent.goal_coverage import projection


def plan(conn, task_id, goal, policy, cards, signature, clock=None):
    revision = goal['revision']
    projected = projection(conn, task_id, cards, revision, signature, goal['budget'])
    nominees, attempts, active, task_active = set(), {}, {}, False
    for row in conn.execute('''SELECT s.*,b.goal_revision FROM studies s
            LEFT JOIN study_goal_bindings b ON b.study_id=s.id
            WHERE s.task_id=? ORDER BY s.id''', (task_id,)):
        if row['kind']=='visual':
            task_active = task_active or row['state'] in {'queued','running'}
            continue
        if row['kind'].startswith('seller:'):
            continue
        task_active = task_active or row['state'] in {'queued','running'}
        pairs = [tuple(v) for v in json.loads(row['versions_json'])]
        result = json.loads(row['result_json'] or '{}')
        if row['state'] == 'completed':
            nominees.update(result.get('candidate_ids', []))
        if row['goal_revision'] != revision:
            continue
        if row['state'] in {'queued', 'running'}:
            active.update({pair: row['state'] for pair in pairs})
        if row['kind'] == 'followup' and row['state'] != 'superseded':
            attempts.update({pair: dict(study_id=row['id'], state=row['state']) for pair in pairs})
    favorites = {r[0] for r in conn.execute('SELECT listing_id FROM favorites WHERE task_id=?', (task_id,))}
    counts = dict(evaluated=0, ready=0, needs_evidence=0, no_priority=0,
                  attempted=0, failed=0, queued=0, running=0, rule_excluded=0)
    items, ready = [], []
    for card in cards:
        listing = card['listing_id']
        pair = (listing, signature(card))
        price = card.get('price_value')
        usable = isinstance(price, (int, float)) and math.isfinite(price) and price > 0 and not re.search(
            r'起|定金|订金|首付|每[月天]|/(?:月|天)|\d\s*[-~～至]\s*\d',card.get('price_text') or '')
        reasons = []
        if listing in favorites:
            reasons.append('用户收藏')
        if listing in nominees:
            reasons.append('历史研究曾提名（不是当前推荐结论）')
        state = projected['states'][listing]
        attempt = attempts.get(pair)
        if state == 'evaluated':
            category, reason = 'evaluated', '当前目标、同版证据已有有效逐项判断，不重复研究'
        elif pair in active:
            category, reason = active[pair], '已纳入现有研究任务'
        elif usable and goal['budget'] is not None and price > goal['budget']:
            category, reason = 'rule_excluded', '已保存挂牌价超过当前预算；不自动补研'
        elif attempt:
            category = 'failed' if attempt['state'] == 'failed' else 'attempted'
            reason = ('补研失败，可在原任务手动重试' if category == 'failed' else
                      '同目标、同证据已尝试补研但无有效逐项判断；等待新增证据或人工处理，不自动重试')
        elif reasons and usable and bool(card.get('title', '').strip()):
            category, reason = 'ready', '；'.join(reasons) + '；已有标题与有效挂牌价，可有限核对，未知项必须保留'
            ready.append((0 if listing in favorites else 1, listing))
        else:
            has_detail = card.get('detail_status') in {'captured', 'available', 'completed'}
            category = 'no_priority' if has_detail else 'needs_evidence'
            reason = ('尚无明确补研优先线索，不据此判断没有研究价值' if has_detail else
                      '尚无逐项判断和明确补研线索；需补充关键商品证据或由用户指定范围')
        counts[category] += 1
        items.append(dict(listing_id=listing, state=category, reason=reason,
                          study_id=attempt['study_id'] if attempt else None))
    limit = max(1, min(20, policy['batch_size']))
    selected = [listing for _, listing in sorted(ready)][:limit]
    observed = {(r['listing_id'],r['signature']):r['observed_at'] for r in
                conn.execute('SELECT listing_id,signature,observed_at FROM versions WHERE task_id=?',(task_id,))}
    now = datetime.fromisoformat(clock()) if clock else datetime.now(timezone.utc)
    waited = any((now-datetime.fromisoformat(observed[(c['listing_id'],signature(c))])).total_seconds() >= policy['max_wait_seconds']
                 for c in cards if c['listing_id'] in selected and (c['listing_id'],signature(c)) in observed)
    failed = conn.execute("""SELECT 1 FROM studies s JOIN study_goal_bindings b ON b.study_id=s.id
        WHERE s.task_id=? AND b.goal_revision=? AND s.kind IN ('initial','incremental') AND s.state='failed' LIMIT 1""",
        (task_id,revision)).fetchone() is not None
    gate = ('completed' if policy['completed'] else 'paused' if policy['paused'] else
            'unauthorized' if not policy['auto_research'] else
            'active' if task_active else 'failed' if failed else
            'waiting' if selected and len(ready)<limit and not waited else 'ready' if selected else 'idle')
    reason = dict(completed='项目已结束，不安排研究', paused='研究调度已暂停，不自动启动',
                  unauthorized='未授权自动研究；可手动发起有限研究', active='已有任务，等待现有研究结束',
                  failed='当前目标有失败的常规研究，自动调度受阻；请查看并处理原任务',
                  waiting='已有补研线索，等待原有批次门槛或最长等待时间；仍可手动研究',
                  ready='有明确补研线索，可按现有批次上限安排；不自动研究全部未分析商品',
                  idle='当前没有可自动安排的补研样本；不代表剩余商品没有研究价值')[gate]
    return dict(goal_revision=revision, total=len(cards), unassessed=len(cards)-counts['evaluated'],
                counts=counts, listing_ids=selected, batch_limit=limit, gate=gate, reason=reason,
                items=items, quota='unknown', automatic_ready=gate=='ready')


def request_key(task_id, revision, cards, signature):
    pairs = sorted((c['listing_id'], signature(c)) for c in cards)
    digest = hashlib.sha256(json.dumps(pairs, separators=(',', ':')).encode()).hexdigest()
    return f'research-followup:{task_id}:{revision}:{digest}'
