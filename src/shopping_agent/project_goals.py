"""Additive goal metadata. Original tasks, requests and evidence remain immutable."""
import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS project_goal_revisions (
 task_id INTEGER NOT NULL, revision INTEGER NOT NULL, goal TEXT NOT NULL,
 budget REAL, hard_json TEXT NOT NULL, soft_json TEXT NOT NULL,
 legacy_revision_id INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
 request_key TEXT, PRIMARY KEY(task_id,revision), UNIQUE(task_id,request_key));
CREATE TABLE IF NOT EXISTS study_goal_bindings (
 study_id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, goal_revision INTEGER,
 proof TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS study_goal_task ON study_goal_bindings(task_id,goal_revision);
"""

class GoalConflict(ValueError):
    pass

def current(conn, task_id):
    return conn.execute('SELECT * FROM project_goal_revisions WHERE task_id=? ORDER BY revision DESC LIMIT 1', (task_id,)).fetchone()

def prompt_goal(goal, *, legacy=False):
    text = goal['goal'] + '\n硬条件: ' + goal['hard_json'] + '\n偏好: ' + goal['soft_json']
    return text if legacy else text + '\n预算上限（元，挂牌价）: ' + ('未设置' if goal['budget'] is None else str(goal['budget']))

def report_for(conn, task_id, revision):
    # Old databases/reports have no P2 metadata and retain their prior semantics.
    guarded=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='study_evidence_context'").fetchone()
    guard=" AND NOT EXISTS (SELECT 1 FROM study_evidence_context x WHERE x.study_id=r.study_id AND json_extract(x.context_json,'$.publication')='historical')" if guarded else ''
    return conn.execute('SELECT r.*,b.goal_revision FROM reports r JOIN study_goal_bindings b ON b.study_id=r.study_id WHERE r.task_id=? AND b.goal_revision=?'+guard+' ORDER BY r.id DESC LIMIT 1', (task_id,revision)).fetchone()

def bootstrap(conn, task, policy, clock):
    row = current(conn, task['id'])
    if row is None:
        conn.execute('INSERT INTO project_goal_revisions(task_id,revision,goal,budget,hard_json,soft_json,created_at) VALUES(?,1,?,?,?,?,?)',
                     (task['id'],task['goal'],policy['budget'],policy['hard_json'],policy['soft_json'],clock()))
    baseline = conn.execute('SELECT * FROM project_goal_revisions WHERE task_id=? AND revision=1', (task['id'],)).fetchone()
    # Never infer old goals from timestamps. Bind only a matching frozen request.
    for study in conn.execute('SELECT s.id,s.request_json FROM studies s LEFT JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.task_id=? AND b.study_id IS NULL', (task['id'],)).fetchall():
        try:
            frozen_goal = json.loads(study['request_json'])['task']['effective_goal']
            proven = frozen_goal == prompt_goal(baseline) or (baseline['budget'] is None and frozen_goal == prompt_goal(baseline,legacy=True))
        except (KeyError, TypeError, ValueError):
            proven = False
        conn.execute('INSERT INTO study_goal_bindings VALUES(?,?,?,?)', (study['id'],task['id'],1 if proven else None,'frozen_request' if proven else 'unverified_legacy'))
    return dict(current(conn, task['id']))
