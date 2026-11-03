"""Bounded goal-change planning over saved evidence; no worker or model calls.

The queue's unique request key is the durable calibration intention. One automatic
batch per goal, no automatic retries, and no promotion of old AI verdicts.
"""
import json
import math
import re
from datetime import datetime

from shopping_agent import project_goals as goals


def request_key(task_id, revision):
    return f'goal-calibration:{task_id}:{revision}'


def retire_queued(conn, task_id, revision, clock):
    conn.execute("""UPDATE studies SET state='superseded',finished_at=?,
        error='目标已更新，此自动研究尚未执行，已跳过；快照保留。'
        WHERE state='queued' AND id IN
        (SELECT study_id FROM study_goal_bindings WHERE task_id=?
         AND proof IN ('automatic_calibration','automatic_followup','automatic_evidence') AND goal_revision<>?)""",
        (clock(),task_id,revision))


def material(goal):
    return (goal['goal'].strip(),goal['budget'],frozenset(json.loads(goal['hard_json'])))


def plan(conn, task_id, goal, policy, cards, signature, clock):
    def result(state, reason, selected=(), study_id=None):
        return dict(state=state,reason=reason,listing_ids=list(selected),study_id=study_id)

    if goals.report_for(conn,task_id,goal['revision']):
        return result('current','当前目标的研究报告已就绪；后续按既有增量机制继续。')
    if goal['revision']==1:
        return result('not_applicable','首个目标继续使用原有样本门槛与增量调度。')
    job = conn.execute('SELECT id,state,error,versions_json FROM studies WHERE task_id=? AND request_key=?',
                       (task_id,request_key(task_id,goal['revision']))).fetchone()
    if job:
        state = {'queued':'scheduled','running':'running','failed':'unavailable','completed':'unavailable'}.get(job['state'],'waiting')
        reason = job['error'] or ('校准研究已安排，尚未执行。' if state=='scheduled' else '正在复用保存证据研究当前目标。' if state=='running' else '校准未产生当前报告，请检查研究记录；不会自动重复调用。')
        if job['state']=='queued' and (policy['paused'] or policy['completed'] or not policy['auto_research']):
            state='unavailable'
            reason='校准批次已保留，但项目已结束。' if policy['completed'] else '校准批次已保留，但研究调度已暂停。' if policy['paused'] else '校准批次已保留，但自动研究未授权。'
        return result(state,reason,[v[0] for v in json.loads(job['versions_json'])],job['id'])
    if policy['completed']:
        return result('unavailable','项目已结束，不自动安排校准。')
    if policy['paused']:
        return result('unavailable','自动研究已暂停；恢复调度后再判断是否需要校准。')
    if not policy['auto_research']:
        return result('unavailable','尚未授权自动研究，可手动研究有限样本。')
    # Compare to the last report's proven goal, rather than the immediately prior
    # edit: a soft edit must not hide an unprocessed earlier hard-condition edit.
    base = conn.execute('''SELECT g.* FROM reports r JOIN study_goal_bindings b ON b.study_id=r.study_id
        JOIN project_goal_revisions g ON g.task_id=r.task_id AND g.revision=b.goal_revision
        WHERE r.task_id=? ORDER BY r.id DESC LIMIT 1''',(task_id,)).fetchone()
    base = base or conn.execute('SELECT * FROM project_goal_revisions WHERE task_id=? AND revision=1',(task_id,)).fetchone()
    if material(base)==material(goal):
        if not conn.execute('SELECT 1 FROM reports WHERE task_id=? LIMIT 1',(task_id,)).fetchone():
            return result('not_applicable','尚无历史报告，仅软偏好变化；继续按原首轮样本门槛与等待规则研究。')
        return result('not_needed','仅软偏好或条件顺序变化，暂不自动消耗 AI；旧报告仍为历史参考，可手动更新结论。')
    if conn.execute("SELECT 1 FROM studies s JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.task_id=? AND b.goal_revision=? AND s.kind IN ('initial','incremental') AND s.state='failed'",(task_id,goal['revision'])).fetchone():
        return result('unavailable','当前目标已有失败研究，请处理或重试原快照，不自动重复调用。')
    if conn.execute("SELECT 1 FROM studies WHERE task_id=? AND state IN ('queued','running')",(task_id,)).fetchone():
        return result('waiting','本项目已有研究任务，等待其结束后重新核对最新目标。')
    if (datetime.fromisoformat(clock())-datetime.fromisoformat(goal['created_at'])).total_seconds()<5:
        return result('waiting','新目标已保存，短暂合并连续修改后再判断校准范围。')
    prior = conn.execute('SELECT candidate_ids_json FROM reports WHERE task_id=? ORDER BY id DESC LIMIT 1',(task_id,)).fetchone()
    recommended = set(json.loads(prior[0])) if prior else set()
    favorites = {r[0] for r in conn.execute('SELECT listing_id FROM favorites WHERE task_id=?',(task_id,))}
    # Reuse completed research as context, but never count it as this goal's coverage.
    researched, unresolved = set(), set()
    for row in conn.execute("SELECT versions_json,result_json FROM studies WHERE task_id=? AND state='completed'",(task_id,)):
        versions = dict(json.loads(row[0]))
        researched.update(versions.items())
        research = (json.loads(row[1] or '{}').get('research') or {})
        hard = {c['criterion_id'] for c in research.get('criteria',[]) if c.get('priority')=='hard'}
        for item in research.get('assessments',[]):
            if any(j.get('criterion_id') in hard and j.get('status')=='UNKNOWN' for j in item.get('judgments',[])):
                unresolved.add((item['listing_id'],versions.get(item['listing_id'])))
    selected = []
    for card in cards:
        price = card.get('price_value')
        usable = isinstance(price,(int,float)) and math.isfinite(price) and price>0 and not re.search(r'起|定金|订金|首付|每[月天]|/(?:月|天)|\d\s*[-~～至]\s*\d',card.get('price_text') or '')
        if usable and goal['budget'] is not None and price>goal['budget']:
            continue
        # Priority only, never an exclusion: uncertain/multiple configurations and
        # seller title claims are not independently verified RAM facts.
        minima = [int(m[1]) for text in json.loads(goal['hard_json'])
                  if (m:=re.fullmatch(r'内存\s*(?:至少|不低于|≥|>=)\s*(\d+)\s*(?:GB|G)',text,re.I))]
        ram = re.findall(r'(?<![\d.])(\d+)\s*G(?:B)?(?![a-z]|\s*(?:显存|硬盘|SSD))',card.get('title',''),re.I)
        low_ram = bool(minima and len(ram)==1 and int(ram[0])<max(minima)
            and not re.search(r'(?:显存|显卡)\s*\d+\s*G|\d+\s*G(?:B)?\s*显存',card.get('title',''),re.I)
            and re.search(r'MacBook|iMac|ThinkPad|笔记本|台式|一体机',card.get('title',''),re.I))
        listing = card['listing_id']
        key = (listing,signature(card))
        rank = (low_ram,0 if listing in recommended else 1 if listing in favorites else 2 if key in unresolved else 3 if key in researched else 4,not usable,listing)
        selected.append((rank,listing))
    selected = [listing for _,listing in sorted(selected)][:max(1,min(20,policy['batch_size']))]
    if not selected:
        return result('unavailable','保存数据中没有可安排的校准样本；未调用 AI，缺失信息不视为不合格。')
    return result('waiting','硬条件、预算或目标正文变化，已有结论未覆盖；将复用保存证据安排一个有限批次。',selected)
