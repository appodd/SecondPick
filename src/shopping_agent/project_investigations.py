"""P1 local planning + existing approval/browser execution. No model/network calls.

One additive source-DB link table; action_requests/browser_jobs remain execution
authorities. A completed local operation anchors the legacy request FK, without
pretending to create an AgentRun or asking the legacy coordinator to run it.
"""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from shopping_agent.browser_jobs import BrowserJobError
from shopping_agent.browser_collection import safe_listing_url
from shopping_agent.candidate_context import _load_scoped_candidates, _load_scoped_details, _serialize_evidence_candidate
from shopping_agent.db import utc_now_iso

MANUAL = re.compile(r'维修|拆修|拆过|漂移|电池|健康|真实性|原装|正品|封口|封装|凭证|实拍|视频|测试|购买记录|验机|功能正常')
SELLER = re.compile(r'卖家主页|卖家信用|评价|其他商品|卖家公开|卖家资料')


def exists(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_investigations'").fetchone() is not None


def linked(conn, request_id):
    return conn.execute('SELECT * FROM project_investigations WHERE request_id=?', (request_id,)).fetchone() if exists(conn) else None


def facts(conn, task, listing):
    runs = [r[0] for r in conn.execute('SELECT run_id FROM task_runs WHERE task_id=?', (task,))]
    cards, rows = _load_scoped_candidates(conn, runs)
    card = next((c for c in cards if c['listing_id'] == listing), None)
    if card is None or rows[listing]['platform'] != 'xianyu' or not safe_listing_url(card['url']):
        raise BrowserJobError('invalid_scope', '商品不属于此项目或不是有效闲鱼商品。', 400)
    ids = parse_qs(urlsplit(card['url']).query).get('id', [])
    if len(ids) != 1 or not ids[0].isascii() or not ids[0].isdigit():
        raise BrowserJobError('invalid_scope', '闲鱼商品链接缺少合法且唯一的商品 ID。', 400)
    detail = _load_scoped_details(conn, runs).get(listing)
    evidence = _serialize_evidence_candidate(conn, card, rows[listing], detail, runs, 0, task)
    saved = card.get('monitor_evidence', {}).get('fields', {})
    supplement = saved.get('monitor_detail', {})
    native = evidence.get('detail') or {}
    description = native.get('description') or supplement.get('商品描述') or card.get('search_description') or ''
    if description.strip() == card['title'].strip():
        description = ''
    images = {r[0] for r in conn.execute("SELECT source_url FROM media_assets WHERE listing_id=? AND media_type='product_image_url'", (listing,)) if r[0]}
    images.update(supplement.get('商品图片列表', []))
    if supplement.get('商品主图链接'):
        images.add(supplement['商品主图链接'])
    seller = {k: v for k,v in evidence['seller_fields'].items() if k.startswith('seller_') and v is not None}
    profile = {}
    if runs:
        for row in conn.execute('''SELECT mi.seller_json FROM monitor_import_records mi JOIN listing_snapshots ls
            ON ls.id=mi.snapshot_id JOIN task_runs tr ON tr.run_id=ls.run_id
            WHERE tr.task_id=? AND ls.listing_id=? ORDER BY mi.snapshot_id''', (task,listing)):
            profile.update(json.loads(row['seller_json'] or '{}'))
    value = dict(title=card['title'], asking_price=card.get('price_value'), description=' '.join(description.split()),
                 attributes={**supplement.get('商品属性', {}), **native.get('attributes', {})}, images=sorted(images),
                 seller_fields=seller, seller_public=saved.get('seller_public', {}),
                 seller_profile=profile)
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest(), value, card


def held_tasks(conn, *, include_review=True):
    """P1 is not authorization for P2, including races with existing auto runs."""
    if not exists(conn):
        return set()
    held = set()
    for row in conn.execute('''SELECT i.*,b.state AS job_state FROM project_investigations i
        LEFT JOIN browser_jobs b ON b.request_id=i.request_id'''):
        outcome = json.loads(row['outcome_json'])
        if ((row['decision'] == 'approved' and (row['job_state'] is None or row['job_state'] in {'queued','running'}))
                or include_review and outcome.get('requires_manual_review', outcome.get('new_evidence')) and not (outcome.get('manually_reassessed') or outcome.get('reassessed'))):
            held.add(row['task_id'])
    return held


def current_revision(path, task):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        row = conn.execute('SELECT MAX(revision) FROM project_goal_revisions WHERE task_id=?', (task,)).fetchone()
        return row[0]


def validate_execution(conn, config, row, investigation_id):
    if investigation_id != row['id'] or row['decision'] != 'approved' or row['kind'] != 'detail':
        raise BrowserJobError('investigation_approval_required', '请在当前项目内确认这条具体调查。')
    if current_revision(config.database_path.with_suffix('.secondpick.sqlite'), row['task_id']) != row['goal_revision']:
        raise BrowserJobError('goal_changed', '选购目标已变化，请取消旧建议并重新整理。')
    key, _, _ = facts(conn, row['task_id'], row['listing_id'])
    if key != row['evidence_key']:
        raise BrowserJobError('evidence_changed', '已有证据已变化，请重新审阅调查范围。')
    with closing(sqlite3.connect(config.database_path.with_suffix('.secondpick.sqlite').resolve().as_uri()+'?mode=ro', uri=True)) as studies:
        if studies.execute("SELECT 1 FROM studies WHERE task_id=? AND state IN ('queued','running')", (row['task_id'],)).fetchone():
            raise BrowserJobError('research_busy', '项目已有研究任务，请等待完成；不会抢占或停止研究。')


def finish_investigation(conn, job):
    row = linked(conn, job['request_id'])
    if row is None:
        return False
    plan = json.loads(row['plan_json'])
    try:
        after, saved, _ = facts(conn, row['task_id'], row['listing_id'])
    except (BrowserJobError,ValueError,TypeError,OSError):
        conn.execute('UPDATE project_investigations SET outcome_json=? WHERE id=?',
                     (json.dumps(dict(evidence_comparison_unavailable=True, requires_manual_review=True)), row['id']))
        return True
    details = [r[0] for r in conn.execute('SELECT id FROM detail_snapshots WHERE listing_id=? AND id>? ORDER BY id',
                                         (row['listing_id'], plan['detail_max_id']))]
    def added(old, new):
        if isinstance(new, dict):
            return any(added(old.get(k) if isinstance(old,dict) else None, value) for k,value in new.items())
        if isinstance(new, list):
            return any(value not in (old or []) for value in new)
        return new not in (None,'') and new != old
    new_facts = added(plan.get('saved_facts', {}), saved)
    conn.execute('UPDATE project_investigations SET outcome_json=? WHERE id=?',
                 (json.dumps(dict(new_evidence=new_facts, evidence_key=after,
                                  requires_manual_review=new_facts or bool(details),
                                  detail_snapshot_ids=details, manually_reassessed=False)), row['id']))
    return True


def acknowledge_manual(research, study, result):
    """Only an explicitly requested, successful current-evidence assessment
    releases the P1 hold. This never creates a study or publishes a report.
    """
    if study['binding_proof'] != 'confirmed_snapshot' or not result.research:
        return
    revision = research.goal(study['task_id'])['revision']
    with research.db() as conn:
        bound = conn.execute('SELECT goal_revision FROM study_goal_bindings WHERE study_id=?', (study['id'],)).fetchone()
    if not bound or bound[0] != revision:
        return
    cards = {c['listing_id']: c for c in research.cards(study['task_id'])}
    frozen = dict(json.loads(study['versions_json']))
    assessed = {a.listing_id for a in result.research.assessments}
    with research.source_db() as conn:
        for row in conn.execute('SELECT * FROM project_investigations WHERE task_id=?', (study['task_id'],)):
            listing = row['listing_id']
            outcome = json.loads(row['outcome_json'])
            if (listing in assessed and listing in cards
                    and frozen.get(listing) == research.signature(cards[listing]) and outcome.get('requires_manual_review')):
                outcome.update(manually_reassessed=True, manual_study_id=study['id'])
                conn.execute('UPDATE project_investigations SET outcome_json=? WHERE id=?', (json.dumps(outcome),row['id']))


class ProjectInvestigations:
    def __init__(self, research):
        self.research = research
        self.config = research.config

    def candidates(self, task, ids=None):
        goal = self.research.goal(task)
        if self.research.policy(task)['completed']:
            raise BrowserJobError('project_completed','项目已结束，不创建新调查。')
        cards = self.research.cards(task)
        index = {c['listing_id']: c for c in cards}
        if ids is not None and (not ids or len(ids)>3 or not set(ids)<=set(index)):
            raise BrowserJobError('invalid_scope', '请选择本项目的 1–3 件已有商品。', 400)
        nominees, questions, studies, rejected, risks, unknowns = set(), {}, {}, set(), set(), {}
        with self.research.db() as conn:
            favorites = {r[0] for r in conn.execute('SELECT listing_id FROM favorites WHERE task_id=?', (task,))}
            for row in conn.execute('''SELECT s.*,b.goal_revision FROM studies s LEFT JOIN study_goal_bindings b
                    ON b.study_id=s.id WHERE s.task_id=? AND s.state='completed' ORDER BY s.id''', (task,)):
                output = json.loads(row['result_json'] or '{}')
                nominated = output.get('candidate_ids', [])
                nominees.update(nominated)
                for listing in nominated:
                    studies.setdefault(listing, set()).add(row['id'])
                for q in output.get('check_suggestions', []):
                    listing = q.get('listing_id')
                    questions.setdefault(listing, []).append(str(q.get('question', ''))[:600])
                    if re.search(r'价格异常|异常低价|描述矛盾|证据冲突|说法冲突',str(q.get('reason',''))):
                        risks.add(listing)
                    studies.setdefault(listing, set()).add(row['id'])
                pairs = dict(json.loads(row['versions_json']))
                criteria = {c['criterion_id']:c['description'] for c in (output.get('research') or {}).get('criteria',[])}
                for a in (output.get('research') or {}).get('assessments', []):
                    listing = a['listing_id']
                    studies.setdefault(listing, set()).add(row['id'])
                    if listing not in index or row['goal_revision'] != goal['revision'] or pairs.get(listing) != self.research.signature(index[listing]):
                        continue
                    if a.get('conclusion') == 'not_met':
                        rejected.add(listing)
                    for j in a.get('judgments', []):
                        if j.get('status') in {'UNKNOWN', 'CONFLICT'}:
                            unknowns.setdefault(listing, []).append(str(j.get('reason', ''))[:500])
                            if not questions.get(listing):
                                condition = criteria.get(j.get('criterion_id'),'当前未核实条件')[:120]
                                questions.setdefault(listing, []).append(f'能否提供能核实「{condition}」的实物资料或检测说明？')
                            if j.get('status') == 'CONFLICT':
                                risks.add(listing)
        chosen, skipped = [], []
        with self.research.source_db() as conn:
            for listing, card in index.items():
                reasons = []
                if ids and listing in ids:
                    reasons.append('用户明确指定')
                if listing in favorites:
                    reasons.append('用户收藏')
                if listing in nominees:
                    reasons.append('历史研究提名（不代表当前推荐）')
                if questions.get(listing):
                    reasons.append('已有研究指出关键未知项或冲突')
                if listing in risks:
                    reasons.append('已有研究提出需核对的风险或冲突线索（未独立核实）')
                if ids is not None and listing not in ids:
                    continue
                if not reasons or (not ids and (listing in rejected or goal['budget'] is not None and card.get('price_value') is not None and card['price_value'] > goal['budget'])):
                    skipped.append(dict(listing_id=listing, reason='无明确调查价值线索，或已有明确硬条件不符；不自动调查'))
                    continue
                try:
                    key, saved, _ = facts(conn, task, listing)
                except BrowserJobError:
                    if ids is not None:
                        raise
                    skipped.append(dict(listing_id=listing, reason='当前平台或链接不支持安全详情执行'))
                    continue
                gaps = [label for field, label in [('description','完整商品描述与公开交易说明'), ('attributes','商品属性与版本'), ('images','商品图片链接')]
                        if not saved[field]]
                qs = list(dict.fromkeys(q for q in questions.get(listing, []) if q))[:8]
                seller = [q for q in qs if SELLER.search(q) and not MANUAL.search(q)]
                manual = [q for q in qs if q not in seller]
                kind = 'detail' if gaps and card['detail_status'] != 'captured' else 'manual' if manual else 'seller_public' if seller else None
                if kind is None:
                    skipped.append(dict(listing_id=listing, reason='已有详情访问证据；平台未给出的字段保持未知，不重复打开同一详情'))
                    continue
                attempted = conn.execute('''SELECT i.id FROM project_investigations i JOIN browser_jobs b ON b.request_id=i.request_id
                    WHERE i.task_id=? AND i.listing_id=? AND i.kind=? AND i.evidence_key=? LIMIT 1''', (task,listing,kind,key)).fetchone()
                if attempted:
                    skipped.append(dict(listing_id=listing, reason=f'同一证据需求已有执行记录 #{attempted[0]}；不自动重试'))
                    continue
                plan = dict(title=card['title'], objective='补充已保存商品的公开详情证据' if kind=='detail' else '保留待核实问题',
                    reason='；'.join(reasons), evidence_gaps=gaps, expected_information=gaps,
                    existing_unknowns=list(dict.fromkeys(unknowns.get(listing,[])))[:8],
                    capability='现有 BrowserJob 商品详情采集' if kind=='detail' else '暂不支持卖家主页执行' if kind=='seller_public' else '需要询问卖家或人工核实',
                    manual_questions=manual, seller_public_questions=seller, source_study_ids=sorted(studies.get(listing, set())),
                    goal_snapshot=dict(goal=goal['goal'], revision=goal['revision'],budget=goal['budget'],
                        hard=json.loads(goal['hard_json']),soft=json.loads(goal['soft_json'])), requires_confirmation=kind=='detail', saved_facts=saved,
                    detail_max_id=conn.execute('SELECT COALESCE(MAX(id),0) FROM detail_snapshots WHERE listing_id=?', (listing,)).fetchone()[0])
                score = (1000 if ids and listing in ids else 0) + (100 if listing in nominees else 0) + (40 if listing in favorites else 0) + (50 if listing in risks else 0) + len(gaps)*5
                plan.update(priority_score=score, expected_information_gain='补充缺失公开字段；真实性及机况仍需人工核实')
                chosen.append((-score, listing,kind,key,plan))
        return goal, sorted(chosen, key=lambda x:(x[0],x[1])), skipped

    def propose(self, task, ids=None):
        goal, choices, skipped = self.candidates(task, ids)
        with self.research.source_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            # At most three open listing plans, not three new plans on each refresh.
            open_ids = {r[0] for r in conn.execute("""SELECT i.listing_id FROM project_investigations i LEFT JOIN browser_jobs b
                ON b.request_id=i.request_id WHERE i.task_id=? AND i.decision IN ('pending','approved')
                AND (b.id IS NULL OR b.state IN ('queued','running'))
                AND COALESCE(json_extract(i.plan_json,'$.visual_investigation'),0) != 1""", (task,))}
            for _, listing, kind, key, plan in choices:
                if conn.execute('SELECT 1 FROM project_investigations WHERE task_id=? AND listing_id=? AND kind=? AND goal_revision=? AND evidence_key=?', (task,listing,kind,goal['revision'],key)).fetchone():
                    skipped.append(dict(listing_id=listing, reason='已有同目标、同证据的调查记录；复用原记录，不重新请求'))
                    continue
                if len(open_ids)>=3 or listing in open_ids:
                    skipped.append(dict(listing_id=listing, reason='已达到 3 件待处理上限，或本商品已有待处理建议；本次未新增'))
                    continue
                now = utc_now_iso()
                request = None
                if kind == 'detail':
                    message = conn.execute("INSERT INTO conversation_messages(task_id,role,content,created_at) VALUES(?,'system',?,?)",
                        (task, '调查计划由已保存研究整理，未调用模型：'+plan['objective'], now))
                    operation = conn.execute("INSERT INTO operations(task_id,user_message_id,kind,state,created_at,started_at,completed_at) VALUES(?,?,'codex_message','completed',?,?,?)", (task,message.lastrowid,now,now,now))
                    request = conn.execute("INSERT INTO action_requests(operation_id,task_id,summary,risk,listing_ids_json,actions_json,state,created_at) VALUES(?,?,?,?,?,?,'pending',?)",
                        (operation.lastrowid,task,plan['objective'],'额外访问该商品详情；平台信息及卖家自述不是独立核验。',json.dumps([listing]),'["detail"]',now)).lastrowid
                conn.execute('INSERT INTO project_investigations(task_id,listing_id,goal_revision,kind,evidence_key,plan_json,request_id,created_at) VALUES(?,?,?,?,?,?,?,?)',
                    (task,listing,goal['revision'],kind,key,json.dumps(plan,ensure_ascii=False),request,now))
                open_ids.add(listing)
        return self.list(task, skipped)

    def list(self, task, skipped=None, listing=None):
        self.research.require(task)
        revision = self.research.goal(task)['revision']
        items = []
        with self.research.source_db() as conn:
            for row in conn.execute('''SELECT i.*,b.id AS job_id,b.state AS job_state,b.stage,b.error_code FROM project_investigations i
                LEFT JOIN browser_jobs b ON b.request_id=i.request_id WHERE i.task_id=? AND (? IS NULL OR i.listing_id=?)
                ORDER BY (b.state IN ('queued','running') OR (b.id IS NULL AND i.decision IN ('pending','approved'))) DESC,i.id DESC LIMIT 100''', (task,listing,listing)):
                item = dict(row)
                item['plan'] = json.loads(item.pop('plan_json'))
                if item['plan'].get('visual_investigation') is True:
                    continue  # P5 uses this manual-plan ledger, not the BrowserJob approval UI.
                item['outcome'] = json.loads(item.pop('outcome_json'))
                state = item['decision']
                if state != 'cancelled' and item['job_state']:
                    state = item['job_state']
                    if state == 'completed':
                        state = 'new_evidence' if item['outcome'].get('new_evidence') else 'no_new_evidence'
                    elif state == 'running' and item['stage'] == 'waiting_verification':
                        state = 'needs_attention'
                    elif state == 'failed' and item['error_code'] in {'login_required','access_blocked','verification_closed','browser_busy'}:
                        state = 'needs_attention'
                if item['outcome'].get('evidence_comparison_unavailable'):
                    state = 'needs_attention'
                if not item['job_id'] and state != 'cancelled' and item['kind'] != 'detail':
                    state = 'manual' if item['kind']=='manual' else 'unsupported'
                item['state'], item['outdated'] = state, item['goal_revision'] != revision
                items.append(item)
            hold = task in held_tasks(conn, include_review=False)
        return dict(items=items, skipped=skipped or [], automatic_research_held=hold, max_listings=3)

    def decide(self, task, ident, action):
        revision = self.research.goal(task)['revision']
        with self.research.source_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM project_investigations WHERE id=? AND task_id=?', (ident,task)).fetchone()
            if row is None:
                raise BrowserJobError('not_found','调查不属于此项目。',404)
            if action == 'approve':
                if row['kind'] != 'detail' or row['decision']=='cancelled' or revision!=row['goal_revision']:
                    raise BrowserJobError('invalid_approval','此建议不可执行或目标已变化，请重新整理。')
                key, _, _ = facts(conn, task, row['listing_id'])
                if key != row['evidence_key']:
                    raise BrowserJobError('evidence_changed','证据已更新，请取消旧建议并重新整理。')
                conn.execute("UPDATE project_investigations SET decision='approved' WHERE id=?", (ident,))
                conn.execute("UPDATE action_requests SET state='approved',decided_at=? WHERE id=?", (utc_now_iso(),row['request_id']))
            else:
                job = conn.execute('SELECT state FROM browser_jobs WHERE request_id=?', (row['request_id'],)).fetchone()
                if job:
                    raise BrowserJobError('execution_exists','已有执行记录；进行中的任务请使用取消执行。')
                conn.execute("UPDATE project_investigations SET decision='cancelled' WHERE id=?", (ident,))
                if row['request_id']:
                    conn.execute("UPDATE action_requests SET state='rejected',decided_at=? WHERE id=?", (utc_now_iso(),row['request_id']))
        return self.list(task)
