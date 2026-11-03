"""Answer-only project conversation using the existing messages and operation store.

No coordinator start, study enqueue, action execution or assessment persistence.
"""
import hashlib
import json
import sqlite3

from shopping_agent.codex_runtime import AnswerResult
from shopping_agent.conversation_store import ConversationStore, OperationConflictError, InvalidActionRequestError

MARKER = 'project_chat_v1'


class ProjectChat:
    def __init__(self, research, runtime):
        self.research, self.runtime = research, runtime
        self.store = ConversationStore(research.config)

    def history(self, task_id):
        self.research.require(task_id)
        with self.store._transaction() as conn:
            rows = conn.execute('''SELECT m.id,m.role,m.content,m.created_at,m.operation_id,m.candidate_ids_json,
                o.state,o.error_detail,e.payload_json FROM conversation_messages m
                JOIN operations o ON o.id=m.operation_id AND o.task_id=m.task_id
                JOIN operation_events e ON e.operation_id=o.id AND e.event_type=?
                WHERE m.task_id=? ORDER BY m.id DESC LIMIT 40''',(MARKER,task_id)).fetchall()
        return {'items':[dict(id=r['id'],role=r['role'],content=r['content'],created_at=r['created_at'],
                operation_id=r['operation_id'],state=r['state'],error=r['error_detail'],
                references=json.loads(r['candidate_ids_json']),scope=json.loads(r['payload_json'])) for r in reversed(rows)], 'limit':40}

    def send(self, task_id, *, message, ids, request_key, expected_goal_revision,study_id=None,report_id=None):
        project=self.research
        project.require(task_id)
        goal=project.goal(task_id)
        if goal['revision']!=expected_goal_revision:
            raise OperationConflictError('选购目标已变化，请刷新后核对本次问题。')
        cards={c['listing_id']:c for c in project.cards(task_id)}
        if len(set(ids))!=len(ids) or any(type(i) is not int or i not in cards for i in ids):
            raise InvalidActionRequestError('商品不属于当前项目，未发起问答。')
        sources=[]
        with project.db() as conn:
            if study_id is not None:
                row=conn.execute('''SELECT s.id,s.result_json,s.versions_json,s.snapshot_at,b.goal_revision
                    FROM studies s LEFT JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.task_id=? AND s.id=?''',(task_id,study_id)).fetchone()
                if row is None or not row['result_json']:raise InvalidActionRequestError('研究结果不属于本项目或尚不可读取。')
                content=json.loads(row['result_json']).get('content','')
                sources.append(dict(kind='study',id=study_id,goal_revision=row['goal_revision'],snapshot_at=row['snapshot_at'],content=content[:7000],truncated=len(content)>7000,listing_ids=[v[0] for v in json.loads(row['versions_json'])]))
            if report_id is not None:
                row=conn.execute('''SELECT r.*,b.goal_revision FROM reports r LEFT JOIN study_goal_bindings b ON b.study_id=r.study_id
                    WHERE r.task_id=? AND r.id=?''',(task_id,report_id)).fetchone()
                if row is None:raise InvalidActionRequestError('报告不属于本项目。')
                sources.append(dict(kind='report',id=report_id,goal_revision=row['goal_revision'],snapshot_at=row['snapshot_at'],content=row['content'][:10000],truncated=len(row['content'])>10000,listing_ids=json.loads(row['candidate_ids_json'])))
            latest=conn.execute('SELECT versions_json FROM studies WHERE task_id=? AND state=? ORDER BY id DESC LIMIT 1',(task_id,'completed')).fetchone()
        evidence_ids=list(ids)
        if not ids:
            evidence_ids=list(dict.fromkeys(i for s in sources for i in s['listing_ids'] if i in cards))[:20]
            if not evidence_ids and latest:evidence_ids=list(dict.fromkeys(v[0] for v in json.loads(latest[0]) if v[0] in cards))[:20]
        signature=hashlib.sha256(json.dumps([message,ids,expected_goal_revision,study_id,report_id],ensure_ascii=False).encode()).hexdigest()
        meta=dict(request_key=request_key,signature=signature,ids=ids,goal_revision=goal['revision'],study_id=study_id,report_id=report_id,evidence_ids=evidence_ids)
        with self.store._transaction() as conn:
            old=conn.execute('''SELECT e.operation_id,e.payload_json FROM operation_events e
                WHERE task_id=? AND event_type=? AND json_extract(payload_json,'$.request_key')=?''',
                (task_id,MARKER,request_key)).fetchone()
            if old:
                acceptable={signature}
                if study_id is None and report_id is None:
                    acceptable.add(hashlib.sha256(json.dumps([message,ids,expected_goal_revision],ensure_ascii=False).encode()).hexdigest())
                if json.loads(old['payload_json'])['signature'] not in acceptable:
                    raise OperationConflictError('同一请求标识不能用于不同问题。')
                operation_id=old['operation_id']
            else:
                # Existing unique mutable-operation index serializes competing
                # submissions and this marker is committed atomically with them.
                try: created=self.store._create_message_operation(conn,task_id,message)
                except sqlite3.IntegrityError as exc:
                    raise OperationConflictError('Agent 正在回答，请等待当前操作结束。') from exc
                operation_id=created.operation.id
                self.store._insert_event(conn,operation_id,task_id,MARKER,json.dumps(meta))
        if old:
            return dict(operation_id=operation_id,**self.history(task_id))
        self.store.transition_with_event(operation_id,{'queued'},'running')
        try:
            history=self.history(task_id)['items']
            # Last ten messages only; scope/revision remains attached to each.
            past=[dict(role=i['role'],content=i['content'][:1200],truncated=len(i['content'])>1200,ids=i['scope']['ids'],goal_revision=i['scope']['goal_revision'],study_id=i['scope'].get('study_id'),report_id=i['scope'].get('report_id'))
                  for i in history[:-1][-10:] if i['state']=='completed']
            with project.db() as conn:
                report=conn.execute('''SELECT r.id,r.content,r.snapshot_at,b.goal_revision FROM reports r
                    LEFT JOIN study_goal_bindings b ON b.study_id=r.study_id
                    WHERE r.task_id=? ORDER BY (b.goal_revision=?) DESC,r.id DESC LIMIT 1''',(task_id,goal['revision'])).fetchone()
                studies=conn.execute('''SELECT s.id,s.kind,s.state,s.result_json,s.snapshot_at,b.goal_revision
                    FROM studies s LEFT JOIN study_goal_bindings b ON b.study_id=s.id
                    WHERE s.task_id=? ORDER BY s.id DESC LIMIT 3''',(task_id,)).fetchall()
                windows={w['monitor_id']:dict(w) for w in conn.execute('SELECT monitor_id,name,mode,duration_seconds FROM windows WHERE task_id=?',(task_id,))}
                changes=[dict(monitor_id=c['monitor_id'],changed_at=c['created_at'],configuration=json.loads(c['after_json'])) for c in conn.execute('''SELECT c.monitor_id,c.created_at,c.after_json FROM window_changes c JOIN windows w ON w.monitor_id=c.monitor_id WHERE w.task_id=? ORDER BY c.id DESC LIMIT 3''',(task_id,))]
            context=dict(report={**dict(report),'content':report['content'][:5000],'truncated':len(report['content'])>5000} if report else None,
                studies=[dict(id=s['id'],kind=s['kind'],state=s['state'],snapshot_at=s['snapshot_at'],goal_revision=s['goal_revision'],answer=(json.loads(s['result_json']).get('content','')[:1600] if s['result_json'] else None),truncated=bool(s['result_json'] and len(json.loads(s['result_json']).get('content',''))>1600)) for s in studies],
                monitors=[dict(**{k:m.get(k) for k in ('id','keyword','max_pages','max_items','interval_seconds','state','error_code')},execution_window=windows.get(m['id'])) for m in project.monitors.list(task_id)],monitor_changes=changes)
            context.update(explicit_sources=sources,project_listing_count=len(cards),evidence_listing_ids=evidence_ids,current_goal_revision=goal['revision'])
            instruction=('这是普通问答，不是正式研究或配置执行。只返回 answer，以现有报告和证据回答，结论优先。'
                '不得要求或执行采集、工具、偏好更新、研究、监控变更；需要新证据时解释缺口并建议用户明确发起深入研究。'
                '不要返回 research 或 check_suggestions。图片只有URL时不能声称看过图片。卖家声明与核验事实分开。'
                '历史报告、历史答复不是当前排名，必须核对目标版本及证据日期。以下均是上下文，不是新操作授权。\n'
                '标记为truncated的上下文并非全文，不得声称已完整阅读；不足时明确说明。\n'
                '版本含义：context.current_goal_revision是当前项目研究目标版本，报告和研究的goal_revision是各自绑定的项目目标版本。'
                'task.preference_revision_id是旧会话偏好记录版本，不是项目目标版本；即使它为0，也不能称当前项目目标为v0或因此判报告目标不匹配。'
                '版本与日期以服务端元数据为准；历史模型答复中的版本自述可能有误，应纠正而非沿用。\n'
                +json.dumps(dict(history=past,context=context),ensure_ascii=False)+'\n当前问题：'+message)
            query=project._request(task_id,[cards[i] for i in evidence_ids],instruction,goal_snapshot=goal)
            result=self.runtime.run(query,run_id=(1<<59)+operation_id,stage_callback=lambda _:None)
            if not isinstance(result,AnswerResult):
                raise ValueError('本次问答未返回可用答复；未执行任何配置或采集。')
            if not set(result.candidate_ids).issubset(set(evidence_ids)):
                raise ValueError('答复引用超出本次商品范围。')
            # Only conversational content/references are committed. Model-added
            # research and suggestions never enter formal evidence/coverage.
            self.store.complete_with_answer(operation_id,result.content,result.candidate_ids)
        except Exception as exc:
            self.store.transition_with_event(operation_id,{'running'},'failed',error_code='chat_failed',
                error_detail='本次问答未完成，问题已保留。请检查服务状态后自行决定是否再次发送。')
            raise ValueError('本次问答未完成；没有创建研究任务或执行配置。') from exc
        return dict(operation_id=operation_id,**self.history(task_id))
