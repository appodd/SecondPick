from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS search_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  goal TEXT NOT NULL,
  city TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  goal TEXT NOT NULL,
  city TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  run_id INTEGER NOT NULL,
  role TEXT NOT NULL DEFAULT 'search',
  notes TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(task_id, run_id),
  FOREIGN KEY(task_id) REFERENCES research_tasks(id),
  FOREIGN KEY(run_id) REFERENCES search_runs(id)
);

CREATE TABLE IF NOT EXISTS task_preference_revisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  user_message TEXT NOT NULL,
  effective_goal TEXT NOT NULL,
  added_preferences_json TEXT NOT NULL DEFAULT '[]',
  removed_preferences_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES research_tasks(id)
);

CREATE TABLE IF NOT EXISTS queries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  platform TEXT NOT NULL,
  query_text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES search_runs(id)
);

CREATE TABLE IF NOT EXISTS platform_access_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  operation TEXT NOT NULL,
  target TEXT,
  attempted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_access_events_lookup
  ON platform_access_events(platform, operation, attempted_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS page_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  platform TEXT NOT NULL,
  query_text TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  screenshot_path TEXT,
  html_path TEXT,
  text_path TEXT,
  links_path TEXT,
  link_count INTEGER NOT NULL DEFAULT 0,
  access_blocked INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES search_runs(id)
);

CREATE TABLE IF NOT EXISTS detail_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id INTEGER NOT NULL,
  run_id INTEGER,
  url TEXT NOT NULL,
  title TEXT,
  screenshot_path TEXT,
  html_path TEXT,
  text_path TEXT,
  links_path TEXT,
  images_path TEXT,
  link_count INTEGER NOT NULL DEFAULT 0,
  image_count INTEGER NOT NULL DEFAULT 0,
  access_blocked INTEGER NOT NULL DEFAULT 0,
  attributes_json TEXT NOT NULL DEFAULT '{}',
  attributes_source TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(listing_id) REFERENCES listings(id),
  FOREIGN KEY(run_id) REFERENCES search_runs(id)
);

CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS listing_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id INTEGER NOT NULL,
  run_id INTEGER NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'web_search',
  source_label TEXT NOT NULL DEFAULT '网页搜索',
  title TEXT,
  price_text TEXT,
  location TEXT,
  seller_name TEXT,
  description TEXT,
  search_condition TEXT,
  collected_at TEXT NOT NULL,
  FOREIGN KEY(listing_id) REFERENCES listings(id),
  FOREIGN KEY(run_id) REFERENCES search_runs(id)
);

CREATE TABLE IF NOT EXISTS monitor_import_records (
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  fingerprint TEXT NOT NULL,
  snapshot_id INTEGER NOT NULL UNIQUE REFERENCES listing_snapshots(id),
  source TEXT NOT NULL,
  source_task TEXT,
  observed_at TEXT,
  imported_at TEXT NOT NULL,
  seller_json TEXT NOT NULL DEFAULT '{}',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  evidence_stage TEXT NOT NULL DEFAULT 'product_record',
  source_round_id TEXT,
  PRIMARY KEY(task_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS monitor_stream_checkpoints (
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  stream_key TEXT NOT NULL,
  file_id TEXT NOT NULL,
  byte_offset INTEGER NOT NULL,
  discarding INTEGER NOT NULL DEFAULT 0,
  head_hash TEXT NOT NULL,
  tail_hash TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(task_id, stream_key)
);

CREATE TABLE IF NOT EXISTS monitor_price_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  run_id INTEGER NOT NULL REFERENCES search_runs(id),
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  source_task TEXT NOT NULL,
  round_id TEXT NOT NULL,
  source_run_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  price REAL NOT NULL CHECK(price >= 0),
  price_text TEXT,
  UNIQUE(task_id, source_task, round_id, listing_id)
);
CREATE INDEX IF NOT EXISTS monitor_price_scope ON monitor_price_observations(run_id, listing_id, id);

CREATE TABLE IF NOT EXISTS media_assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  source_url TEXT,
  local_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(listing_id) REFERENCES listings(id)
);

CREATE TABLE IF NOT EXISTS ocr_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  media_asset_id INTEGER NOT NULL,
  ocr_text TEXT NOT NULL,
  detected_specs_json TEXT NOT NULL DEFAULT '{}',
  risk_notes_json TEXT NOT NULL DEFAULT '[]',
  confidence REAL,
  backend TEXT,
  status TEXT NOT NULL DEFAULT 'ok',
  error TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(media_asset_id) REFERENCES media_assets(id)
);

CREATE TABLE IF NOT EXISTS evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id INTEGER NOT NULL,
  run_id INTEGER NOT NULL,
  recommendation TEXT NOT NULL,
  identity_confidence REAL NOT NULL,
  price_score REAL NOT NULL,
  condition_score REAL NOT NULL,
  seller_score REAL NOT NULL,
  transaction_score REAL NOT NULL,
  risks_json TEXT NOT NULL DEFAULT '[]',
  questions_json TEXT NOT NULL DEFAULT '[]',
  suggested_offer_text TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(listing_id) REFERENCES listings(id),
  FOREIGN KEY(run_id) REFERENCES search_runs(id)
);

CREATE TABLE IF NOT EXISTS reference_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  listing_id INTEGER,
  goal TEXT,
  source_type TEXT NOT NULL,
  platform TEXT,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  price_text TEXT,
  price_value INTEGER,
  currency TEXT,
  evidence_level TEXT NOT NULL,
  model_key TEXT,
  spec_summary TEXT,
  comparable_scope TEXT,
  notes TEXT,
  checked_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES search_runs(id),
  FOREIGN KEY(listing_id) REFERENCES listings(id)
);

CREATE TABLE IF NOT EXISTS saved_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER,
  run_id INTEGER,
  listing_id INTEGER,
  title TEXT NOT NULL,
  goal TEXT,
  format TEXT NOT NULL,
  path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES research_tasks(id),
  FOREIGN KEY(run_id) REFERENCES search_runs(id),
  FOREIGN KEY(listing_id) REFERENCES listings(id)
);

CREATE TABLE IF NOT EXISTS seller_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  seller_listing_id INTEGER NOT NULL,
  seller_name TEXT,
  item_id_ext TEXT,
  title TEXT,
  url TEXT,
  source_run_id INTEGER,
  collected_at TEXT NOT NULL,
  FOREIGN KEY(seller_listing_id) REFERENCES listings(id)
);

CREATE TABLE IF NOT EXISTS conversation_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,
  operation_id INTEGER REFERENCES operations(id),
  candidate_ids_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  user_message_id INTEGER NOT NULL REFERENCES conversation_messages(id),
  kind TEXT NOT NULL CHECK(kind = 'codex_message'),
  state TEXT NOT NULL CHECK(state IN (
    'queued', 'running', 'waiting_confirmation', 'completed', 'failed',
    'cancelled', 'interrupted'
  )),
  error_code TEXT,
  error_detail TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS one_mutable_operation_per_task
  ON operations(task_id)
  WHERE state IN ('queued', 'running', 'waiting_confirmation');

CREATE INDEX IF NOT EXISTS idx_conversation_messages_task_page
  ON conversation_messages(task_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_operations_task_state
  ON operations(task_id, state, id DESC);

CREATE TABLE IF NOT EXISTS operation_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  operation_id INTEGER NOT NULL REFERENCES operations(id),
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operation_events_replay
  ON operation_events(operation_id, id);

CREATE TABLE IF NOT EXISTS action_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  operation_id INTEGER NOT NULL UNIQUE REFERENCES operations(id),
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  summary TEXT NOT NULL,
  risk TEXT NOT NULL,
  listing_ids_json TEXT NOT NULL,
  actions_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('pending', 'approved', 'rejected')),
  created_at TEXT NOT NULL,
  decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_action_requests_task_page
  ON action_requests(task_id, id DESC);

CREATE TABLE IF NOT EXISTS browser_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK(kind IN ('login','collection')),
  task_id INTEGER REFERENCES research_tasks(id),
  request_id INTEGER REFERENCES action_requests(id),
  retry_of INTEGER UNIQUE REFERENCES browser_jobs(id),
  query TEXT NOT NULL DEFAULT '',
  max_pages INTEGER NOT NULL DEFAULT 1,
  actions_json TEXT NOT NULL DEFAULT '[]',
  listing_ids_json TEXT NOT NULL DEFAULT '[]',
  state TEXT NOT NULL CHECK(state IN ('queued','running','completed','failed','cancelled','interrupted')),
  stage TEXT NOT NULL DEFAULT 'queued',
  error_code TEXT,
  error_detail TEXT,
  result_json TEXT NOT NULL DEFAULT '{}',
  verify_requested INTEGER NOT NULL DEFAULT 0,
  stop_requested INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_browser_job
  ON browser_jobs((1)) WHERE state IN ('queued','running');
CREATE INDEX IF NOT EXISTS browser_jobs_request ON browser_jobs(request_id, id DESC);
CREATE TABLE IF NOT EXISTS project_investigations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  goal_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('detail','manual','seller_public')),
  evidence_key TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  request_id INTEGER UNIQUE REFERENCES action_requests(id),
  decision TEXT NOT NULL DEFAULT 'pending' CHECK(decision IN ('pending','approved','cancelled')),
  outcome_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(task_id,listing_id,kind,goal_revision,evidence_key)
);
CREATE TABLE IF NOT EXISTS monitors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  keyword TEXT NOT NULL,
  max_pages INTEGER NOT NULL,
  max_items INTEGER NOT NULL,
  interval_seconds INTEGER NOT NULL,
  max_rounds INTEGER NOT NULL,
  collect_seller_profiles INTEGER NOT NULL DEFAULT 0,
  rounds INTEGER NOT NULL DEFAULT 0,
  imported INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL CHECK(state IN ('waiting','running','paused','stopped','needs_attention')),
  desired_state TEXT,
  next_run_at TEXT,
  error_code TEXT,
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_running_monitor ON monitors((1)) WHERE state='running';
CREATE INDEX IF NOT EXISTS monitors_task ON monitors(task_id,id DESC);

CREATE TABLE IF NOT EXISTS monitor_diagnostic_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  monitor_id INTEGER NOT NULL REFERENCES monitors(id),
  round_id TEXT NOT NULL,
  phase TEXT NOT NULL,
  code TEXT NOT NULL,
  counts_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS monitor_diagnostics_scope ON monitor_diagnostic_events(monitor_id,id);
CREATE INDEX IF NOT EXISTS monitor_diagnostics_age ON monitor_diagnostic_events(created_at);

CREATE TABLE IF NOT EXISTS browser_auth (
  id INTEGER PRIMARY KEY CHECK(id=1),
  state TEXT NOT NULL CHECK(state IN ('unknown','verified','invalid'))
);
INSERT OR IGNORE INTO browser_auth(id,state) VALUES(1,'unknown');
CREATE TABLE IF NOT EXISTS browser_job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES browser_jobs(id),
  event_type TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS browser_job_events_job ON browser_job_events(job_id,id DESC);
CREATE INDEX IF NOT EXISTS browser_job_events_time ON browser_job_events(event_type,created_at DESC);

CREATE TABLE IF NOT EXISTS requirement_standards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  preference_revision_id INTEGER NOT NULL,
  criteria_json TEXT NOT NULL,
  operation_id INTEGER NOT NULL REFERENCES operations(id),
  created_at TEXT NOT NULL,
  UNIQUE(task_id, preference_revision_id)
);

CREATE TABLE IF NOT EXISTS research_assessments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  operation_id INTEGER NOT NULL REFERENCES operations(id),
  batch_index INTEGER NOT NULL DEFAULT 0,
  candidate_ids_json TEXT NOT NULL DEFAULT '[]',
  dependencies_json TEXT NOT NULL DEFAULT '{}',
  standard_id INTEGER NOT NULL REFERENCES requirement_standards(id),
  result_json TEXT NOT NULL,
  input_json TEXT NOT NULL,
  input_signature TEXT NOT NULL,
  evidence_signature TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(operation_id, batch_index)
);

CREATE TABLE IF NOT EXISTS history_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  operation_id INTEGER NOT NULL UNIQUE REFERENCES operations(id),
  standard_id INTEGER NOT NULL REFERENCES requirement_standards(id),
  preference_revision_id INTEGER NOT NULL,
  evidence_signature TEXT NOT NULL,
  scope_ids_json TEXT NOT NULL,
  input_json TEXT NOT NULL,
  previous_comparison_id INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_assessment_links (
  review_id INTEGER NOT NULL REFERENCES history_reviews(id),
  assessment_id INTEGER NOT NULL REFERENCES research_assessments(id),
  PRIMARY KEY(review_id, assessment_id)
);
CREATE TABLE IF NOT EXISTS comparison_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  operation_id INTEGER NOT NULL UNIQUE REFERENCES operations(id),
  review_id INTEGER NOT NULL UNIQUE REFERENCES history_reviews(id),
  standard_id INTEGER NOT NULL REFERENCES requirement_standards(id),
  preference_revision_id INTEGER NOT NULL,
  evidence_signature TEXT NOT NULL,
  previous_comparison_id INTEGER REFERENCES comparison_snapshots(id),
  result_json TEXT NOT NULL,
  input_json TEXT NOT NULL,
  input_signature TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  coverage_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_candidate_links (
  review_id INTEGER NOT NULL REFERENCES history_reviews(id),
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  assessment_id INTEGER NOT NULL REFERENCES research_assessments(id),
  PRIMARY KEY(review_id, listing_id)
);
CREATE TABLE IF NOT EXISTS review_nominations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  review_id INTEGER NOT NULL REFERENCES history_reviews(id),
  group_index INTEGER NOT NULL,
  result_json TEXT NOT NULL,
  input_json TEXT NOT NULL,
  input_signature TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(review_id, group_index)
);
CREATE TABLE IF NOT EXISTS candidate_statements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  source_message_id INTEGER NOT NULL UNIQUE REFERENCES conversation_messages(id),
  kind TEXT NOT NULL CHECK(kind IN ('seller_reply','user_observation')),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_statements_scope ON candidate_statements(task_id,listing_id,id DESC);
CREATE TABLE IF NOT EXISTS candidate_statement_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  statement_id INTEGER NOT NULL REFERENCES candidate_statements(id),
  previous_revision_id INTEGER NOT NULL,
  action TEXT NOT NULL CHECK(action IN ('rebind','withdraw')),
  old_listing_id INTEGER NOT NULL REFERENCES listings(id),
  new_listing_id INTEGER NOT NULL REFERENCES listings(id),
  new_kind TEXT NOT NULL CHECK(new_kind IN ('seller_reply','user_observation')),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_statement_changes_latest ON candidate_statement_changes(statement_id,id DESC);
CREATE VIEW IF NOT EXISTS candidate_statement_current AS
SELECT s.id,s.task_id,s.source_message_id,s.created_at,
  COALESCE(c.new_listing_id,s.listing_id) AS listing_id,COALESCE(c.new_kind,s.kind) AS kind,
  s.listing_id AS original_listing_id,s.kind AS original_kind,
  COALESCE(c.id,0) AS revision_id,
  CASE WHEN c.action='withdraw' THEN 'withdrawn' ELSE 'active' END AS status
FROM candidate_statements s LEFT JOIN candidate_statement_changes c
ON c.id=(SELECT MAX(x.id) FROM candidate_statement_changes x WHERE x.statement_id=s.id);
CREATE TABLE IF NOT EXISTS candidate_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  question TEXT NOT NULL,
  request_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(task_id,request_key)
);
CREATE INDEX IF NOT EXISTS idx_candidate_checks_scope ON candidate_checks(task_id,listing_id,id DESC);
CREATE TABLE IF NOT EXISTS candidate_check_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_id INTEGER NOT NULL REFERENCES candidate_checks(id),
  previous_revision_id INTEGER NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('pending','evidence_linked','dismissed')),
  statement_id INTEGER REFERENCES candidate_statements(id),
  statement_revision_id INTEGER,
  statement_kind TEXT,
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_check_changes_latest ON candidate_check_changes(check_id,id DESC);
CREATE VIEW IF NOT EXISTS candidate_check_current AS
SELECT q.*,COALESCE(c.id,0) AS revision_id,COALESCE(c.state,'pending') AS state,
  c.statement_id,c.statement_revision_id,c.statement_kind,c.note,c.created_at AS changed_at,
  m.content AS statement_text,
  CASE WHEN c.state='evidence_linked' AND m.role='user' AND s.status='active' AND s.listing_id=q.listing_id
    AND s.revision_id=c.statement_revision_id THEN 1 ELSE 0 END AS evidence_current,
  CASE WHEN c.state='evidence_linked' AND NOT COALESCE((m.role='user' AND s.status='active' AND s.listing_id=q.listing_id
    AND s.revision_id=c.statement_revision_id),0) THEN 'pending' ELSE COALESCE(c.state,'pending') END AS effective_state
FROM candidate_checks q LEFT JOIN candidate_check_changes c
  ON c.id=(SELECT MAX(x.id) FROM candidate_check_changes x WHERE x.check_id=q.id)
LEFT JOIN candidate_statement_current s ON s.id=c.statement_id AND s.task_id=q.task_id
LEFT JOIN conversation_messages m ON m.id=s.source_message_id AND m.task_id=q.task_id;
CREATE TABLE IF NOT EXISTS candidate_check_suggestions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES research_tasks(id),
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  operation_id INTEGER NOT NULL REFERENCES operations(id),
  source_message_id INTEGER NOT NULL REFERENCES conversation_messages(id),
  question TEXT NOT NULL,
  reason TEXT NOT NULL,
  preference_revision_id INTEGER NOT NULL,
  evidence_signature TEXT NOT NULL,
  created_at TEXT NOT NULL,
  check_id INTEGER REFERENCES candidate_checks(id),
  accepted_at TEXT,
  reused_existing INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_check_suggestions_scope ON candidate_check_suggestions(task_id,listing_id,id DESC);
CREATE TABLE IF NOT EXISTS candidate_check_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_id INTEGER NOT NULL REFERENCES candidate_checks(id),
  previous_review_id INTEGER NOT NULL,
  check_revision_id INTEGER NOT NULL,
  action TEXT NOT NULL CHECK(action IN ('record','withdraw')),
  outcome TEXT CHECK(outcome IN ('answered','uncertain','conflict')),
  summary TEXT,
  sources_json TEXT NOT NULL,
  preference_revision_id INTEGER NOT NULL,
  dependency_signature TEXT NOT NULL,
  basis_token TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_check_reviews_latest ON candidate_check_reviews(check_id,id DESC);
"""


def connect(database_path: Path, *, timeout: float = 5.0) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(database_path: Path, *, timeout: float = 5.0) -> None:
    from shopping_agent.image_evidence import SCHEMA as IMAGE_EVIDENCE_SCHEMA

    with connect(database_path, timeout=timeout) as conn:
        conn.executescript(SCHEMA)
        conn.executescript(IMAGE_EVIDENCE_SCHEMA)
        _ensure_listing_snapshot_source_schema(conn)
        _ensure_listing_snapshot_card_schema(conn)
        _ensure_listing_snapshot_seller_schema(conn)
        _ensure_seller_items_schema(conn)
        _ensure_detail_snapshot_attribute_schema(conn)
        _ensure_research_workflow_schema(conn)
        _ensure_assessment_batches(conn)
        _ensure_assessment_dependencies(conn)
        for table in ("task_preference_revisions", "task_runs", "saved_reports"):
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_task_history ON {table}(task_id, id DESC)")
        for table in ("queries", "page_snapshots", "listing_snapshots"):
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_run_history ON {table}(run_id)")
        for table in ("research_assessments", "history_reviews", "comparison_snapshots"):
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_task_page ON {table}(task_id, id DESC)")


def _ensure_assessment_dependencies(conn: sqlite3.Connection) -> None:
    """Old snapshots retain global validity; never invent missing dependencies."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(research_assessments)")}
    if "dependencies_json" in columns:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(research_assessments)")}
        if "dependencies_json" not in columns:
            conn.execute("ALTER TABLE research_assessments ADD COLUMN dependencies_json TEXT NOT NULL DEFAULT '{}'")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _ensure_assessment_batches(conn: sqlite3.Connection) -> None:
    """Remove the v1 operation-only uniqueness while preserving assessment IDs.

    SQLite cannot drop an autoindex. The transactional table copy keeps old
    snapshots intact, including IDs used by review links. No live data is reset.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(research_assessments)")}
    if "batch_index" in columns:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Recheck after acquiring the lock: initialization can run concurrently.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(research_assessments)")}
        if "batch_index" not in columns:
            previous_sequence = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='research_assessments'").fetchone()
            declaration = SCHEMA.split("CREATE TABLE IF NOT EXISTS research_assessments (", 1)[1].split(";", 1)[0]
            conn.execute("CREATE TABLE research_assessments_v2 (" + declaration)
            names = ", ".join(row["name"] for row in conn.execute("PRAGMA table_info(research_assessments)"))
            conn.execute(f"INSERT INTO research_assessments_v2 ({names}) SELECT {names} FROM research_assessments")
            conn.execute("DROP TABLE research_assessments")
            conn.execute("ALTER TABLE research_assessments_v2 RENAME TO research_assessments")
            if previous_sequence:
                conn.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='research_assessments'", (previous_sequence[0],))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _ensure_research_workflow_schema(conn: sqlite3.Connection) -> None:
    # Additive migration preserves previous approvals and executions.
    for table, columns in {
        "action_requests": {"search_query": "TEXT", "max_pages": "INTEGER NOT NULL DEFAULT 1"},
        "browser_jobs": {"analysis_operation_id": "INTEGER REFERENCES operations(id)"},
        "monitors": {"collect_seller_profiles": "INTEGER NOT NULL DEFAULT 0"},
        "monitor_import_records": {"seller_json": "TEXT NOT NULL DEFAULT '{}'",
                                   "evidence_json": "TEXT NOT NULL DEFAULT '{}'",
                                   "evidence_stage": "TEXT NOT NULL DEFAULT 'product_record'",
                                   "source_round_id": "TEXT"},
    }.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _touch_task(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("UPDATE research_tasks SET updated_at = ? WHERE id = ?", (utc_now_iso(), task_id))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_latest_platform_access_event(
    conn: sqlite3.Connection,
    *,
    platform: str,
    operation: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, platform, operation, target, attempted_at
        FROM platform_access_events
        WHERE platform = ? AND operation = ?
        ORDER BY attempted_at DESC, id DESC
        LIMIT 1
        """,
        (platform, operation),
    ).fetchone()


def fetch_recent_platform_access_events(
    conn: sqlite3.Connection,
    limit: int = 20,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, platform, operation, target, attempted_at
            FROM platform_access_events
            ORDER BY attempted_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
    )


def add_platform_access_event(
    conn: sqlite3.Connection,
    *,
    platform: str,
    operation: str,
    target: str | None,
    attempted_at: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO platform_access_events (platform, operation, target, attempted_at)
        VALUES (?, ?, ?, ?)
        """,
        (platform, operation, target, attempted_at),
    )
    return int(cursor.lastrowid)


def create_search_run(conn: sqlite3.Connection, goal: str, city: str) -> int:
    cursor = conn.execute(
        "INSERT INTO search_runs (goal, city, created_at) VALUES (?, ?, ?)",
        (goal, city, utc_now_iso()),
    )
    return int(cursor.lastrowid)


def create_research_task(
    conn: sqlite3.Connection,
    title: str,
    goal: str,
    city: str,
    notes: str | None = None,
) -> int:
    now = utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO research_tasks (title, goal, city, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (title, goal, city, notes, now, now),
    )
    return int(cursor.lastrowid)


def attach_run_to_task(
    conn: sqlite3.Connection,
    task_id: int,
    run_id: int,
    role: str = "search",
    notes: str | None = None,
) -> int:
    task = conn.execute("SELECT id FROM research_tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        raise ValueError(f"Research task not found: {task_id}")
    run = conn.execute("SELECT id FROM search_runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"Search run not found: {run_id}")
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO task_runs (task_id, run_id, role, notes, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(task_id, run_id) DO UPDATE SET
          role = excluded.role,
          notes = excluded.notes
        """,
        (task_id, run_id, role, notes, now),
    )
    _touch_task(conn, task_id)
    row = conn.execute(
        "SELECT id FROM task_runs WHERE task_id = ? AND run_id = ?",
        (task_id, run_id),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Failed to attach run {run_id} to task {task_id}")
    return int(row["id"])


def add_task_preference_revision(
    conn: sqlite3.Connection,
    task_id: int,
    user_message: str,
    effective_goal: str,
    added_preferences_json: str = "[]",
    removed_preferences_json: str = "[]",
) -> int:
    task = conn.execute("SELECT id FROM research_tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        raise ValueError(f"Research task not found: {task_id}")
    cursor = conn.execute(
        """
        INSERT INTO task_preference_revisions (
          task_id, user_message, effective_goal, added_preferences_json,
          removed_preferences_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            user_message,
            effective_goal,
            added_preferences_json,
            removed_preferences_json,
            utc_now_iso(),
        ),
    )
    _touch_task(conn, task_id)
    return int(cursor.lastrowid)


def create_query(conn: sqlite3.Connection, run_id: int, platform: str, query_text: str) -> int:
    cursor = conn.execute(
        "INSERT INTO queries (run_id, platform, query_text, created_at) VALUES (?, ?, ?, ?)",
        (run_id, platform, query_text, utc_now_iso()),
    )
    return int(cursor.lastrowid)


def upsert_listing(conn: sqlite3.Connection, platform: str, url: str) -> int:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO listings (platform, url, first_seen_at, last_seen_at, status)
        VALUES (?, ?, ?, ?, 'active')
        ON CONFLICT(url) DO UPDATE SET
          platform = excluded.platform,
          last_seen_at = excluded.last_seen_at,
          status = 'active'
        """,
        (platform, url, now, now),
    )
    row = conn.execute("SELECT id FROM listings WHERE url = ?", (url,)).fetchone()
    if row is None:
        raise RuntimeError(f"Failed to upsert listing: {url}")
    return int(row["id"])


def add_listing_snapshot(
    conn: sqlite3.Connection,
    listing_id: int,
    run_id: int,
    title: str | None = None,
    price_text: str | None = None,
    location: str | None = None,
    seller_name: str | None = None,
    description: str | None = None,
    search_condition: str | None = None,
    source_type: str = "web_search",
    source_label: str = "网页搜索",
    seller_credit_level: str | None = None,
    seller_registered_days: int | None = None,
    seller_sold_count: int | None = None,
    seller_good_rate: str | None = None,
    seller_realname_verified: bool | None = None,
    seller_reply_rate_24h: str | None = None,
) -> int:
    _ensure_listing_snapshot_source_schema(conn)
    _ensure_listing_snapshot_card_schema(conn)
    _ensure_listing_snapshot_seller_schema(conn)
    cursor = conn.execute(
        """
        INSERT INTO listing_snapshots (
          listing_id, run_id, source_type, source_label, title, price_text, location,
          seller_name, description, search_condition, collected_at,
          seller_credit_level, seller_registered_days, seller_sold_count,
          seller_good_rate, seller_realname_verified, seller_reply_rate_24h
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            listing_id,
            run_id,
            source_type,
            source_label,
            title,
            price_text,
            location,
            seller_name,
            description,
            search_condition,
            utc_now_iso(),
            seller_credit_level,
            seller_registered_days,
            seller_sold_count,
            seller_good_rate,
            1 if seller_realname_verified else (0 if seller_realname_verified is False else None),
            seller_reply_rate_24h,
        ),
    )
    return int(cursor.lastrowid)


def add_page_snapshot(
    conn: sqlite3.Connection,
    run_id: int,
    platform: str,
    query_text: str,
    url: str,
    title: str | None,
    screenshot_path: Path,
    html_path: Path,
    text_path: Path,
    links_path: Path,
    link_count: int,
    access_blocked: bool,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO page_snapshots (
          run_id, platform, query_text, url, title, screenshot_path, html_path, text_path,
          links_path, link_count, access_blocked, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            platform,
            query_text,
            url,
            title,
            str(screenshot_path),
            str(html_path),
            str(text_path),
            str(links_path),
            link_count,
            1 if access_blocked else 0,
            utc_now_iso(),
        ),
    )
    return int(cursor.lastrowid)


def add_detail_snapshot(
    conn: sqlite3.Connection,
    listing_id: int,
    run_id: int | None,
    url: str,
    title: str | None,
    screenshot_path: Path,
    html_path: Path,
    text_path: Path,
    links_path: Path,
    images_path: Path,
    link_count: int,
    image_count: int,
    access_blocked: bool,
    attributes_json: str = "{}",
    attributes_source: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO detail_snapshots (
          listing_id, run_id, url, title, screenshot_path, html_path, text_path,
          links_path, images_path, link_count, image_count, access_blocked,
          attributes_json, attributes_source, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            listing_id,
            run_id,
            url,
            title,
            str(screenshot_path),
            str(html_path),
            str(text_path),
            str(links_path),
            str(images_path),
            link_count,
            image_count,
            1 if access_blocked else 0,
            attributes_json,
            attributes_source,
            utc_now_iso(),
        ),
    )
    return int(cursor.lastrowid)


def fetch_recent_runs(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
              r.id,
              r.goal,
              r.city,
              r.created_at,
              COUNT(DISTINCT q.id) AS query_count,
              COUNT(DISTINCT ps.id) AS page_snapshot_count,
              COUNT(DISTINCT ls.id) AS listing_snapshot_count
            FROM search_runs r
            LEFT JOIN queries q ON q.run_id = r.id
            LEFT JOIN page_snapshots ps ON ps.run_id = r.id
            LEFT JOIN listing_snapshots ls ON ls.run_id = r.id
            GROUP BY r.id
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (limit,),
        )
    )


def fetch_search_run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, goal, city, created_at FROM search_runs WHERE id = ?",
        (run_id,),
    ).fetchone()


def fetch_recent_tasks(
    conn: sqlite3.Connection,
    limit: int = 10,
    offset: int = 0,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
              t.id,
              t.title,
              t.goal,
              t.city,
              t.status,
              t.notes,
              t.created_at,
              t.updated_at,
              COUNT(DISTINCT tr.run_id) AS run_count,
              COUNT(DISTINCT sr.id) AS report_count
            FROM research_tasks t
            LEFT JOIN task_runs tr ON tr.task_id = t.id
            LEFT JOIN saved_reports sr ON sr.task_id = t.id
            GROUP BY t.id
            ORDER BY t.updated_at DESC, t.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
    )


def fetch_task_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS count FROM research_tasks").fetchone()
    return int(row["count"])


def fetch_research_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, title, goal, city, status, notes, created_at, updated_at
        FROM research_tasks
        WHERE id = ?
        """,
        (task_id,),
    ).fetchone()


def fetch_task_preference_revisions(
    conn: sqlite3.Connection,
    task_id: int,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
              id, task_id, user_message, effective_goal,
              added_preferences_json, removed_preferences_json, created_at
            FROM task_preference_revisions
            WHERE task_id = ?
            ORDER BY id
            """,
            (task_id,),
        )
    )


def fetch_task_runs(conn: sqlite3.Connection, task_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
              tr.id,
              tr.task_id,
              tr.run_id,
              tr.role,
              tr.notes,
              tr.created_at AS attached_at,
              r.goal,
              r.city,
              r.created_at AS run_created_at,
              COUNT(DISTINCT q.id) AS query_count,
              COUNT(DISTINCT ps.id) AS page_snapshot_count,
              COUNT(DISTINCT ls.id) AS listing_snapshot_count
            FROM task_runs tr
            JOIN search_runs r ON r.id = tr.run_id
            LEFT JOIN queries q ON q.run_id = r.id
            LEFT JOIN page_snapshots ps ON ps.run_id = r.id
            LEFT JOIN listing_snapshots ls ON ls.run_id = r.id
            WHERE tr.task_id = ?
            GROUP BY tr.id
            ORDER BY tr.id
            """,
            (task_id,),
        )
    )


def fetch_queries_for_run(conn: sqlite3.Connection, run_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT query_text FROM queries WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    return list(dict.fromkeys(str(row["query_text"]) for row in rows))


def fetch_unique_listing_ids_for_run(conn: sqlite3.Connection, run_id: int) -> set[int]:
    rows = conn.execute(
        "SELECT DISTINCT listing_id FROM listing_snapshots WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    return {int(row["listing_id"]) for row in rows}


def fetch_listing_collection_states(
    conn: sqlite3.Connection,
    listing_ids: list[int],
) -> dict[int, dict]:
    if not listing_ids:
        return {}
    placeholders = ",".join("?" for _ in listing_ids)
    rows = conn.execute(
        f"""
        SELECT
          l.id AS listing_id,
          COUNT(DISTINCT ds.id) AS detail_snapshot_count,
          COUNT(DISTINCT CASE WHEN ds.access_blocked = 0 THEN ds.id END) AS valid_detail_snapshot_count,
          COUNT(DISTINCT CASE WHEN ma.media_type = 'product_image_url' THEN ma.id END) AS product_image_url_count
        FROM listings l
        LEFT JOIN detail_snapshots ds ON ds.listing_id = l.id
        LEFT JOIN media_assets ma ON ma.listing_id = l.id
        WHERE l.id IN ({placeholders})
        GROUP BY l.id
        """,
        listing_ids,
    ).fetchall()
    return {
        int(row["listing_id"]): {
            "detail_snapshot_count": int(row["detail_snapshot_count"]),
            "valid_detail_snapshot_count": int(row["valid_detail_snapshot_count"]),
            "product_image_url_count": int(row["product_image_url_count"]),
        }
        for row in rows
    }


def fetch_task_reports(conn: sqlite3.Connection, task_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, task_id, run_id, listing_id, title, goal, format, path, created_at
            FROM saved_reports
            WHERE task_id = ?
            ORDER BY id
            """,
            (task_id,),
        )
    )


def fetch_task_file_references(conn: sqlite3.Connection, task_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT 'page_snapshot' AS source, ps.id AS source_id, ps.screenshot_path AS path
            FROM task_runs tr
            JOIN page_snapshots ps ON ps.run_id = tr.run_id
            WHERE tr.task_id = ? AND ps.screenshot_path IS NOT NULL
            UNION ALL
            SELECT 'page_snapshot', ps.id, ps.html_path
            FROM task_runs tr
            JOIN page_snapshots ps ON ps.run_id = tr.run_id
            WHERE tr.task_id = ? AND ps.html_path IS NOT NULL
            UNION ALL
            SELECT 'page_snapshot', ps.id, ps.text_path
            FROM task_runs tr
            JOIN page_snapshots ps ON ps.run_id = tr.run_id
            WHERE tr.task_id = ? AND ps.text_path IS NOT NULL
            UNION ALL
            SELECT 'page_snapshot', ps.id, ps.links_path
            FROM task_runs tr
            JOIN page_snapshots ps ON ps.run_id = tr.run_id
            WHERE tr.task_id = ? AND ps.links_path IS NOT NULL
            UNION ALL
            SELECT 'detail_snapshot', ds.id, ds.screenshot_path
            FROM task_runs tr
            JOIN detail_snapshots ds ON ds.run_id = tr.run_id
            WHERE tr.task_id = ? AND ds.screenshot_path IS NOT NULL
            UNION ALL
            SELECT 'detail_snapshot', ds.id, ds.html_path
            FROM task_runs tr
            JOIN detail_snapshots ds ON ds.run_id = tr.run_id
            WHERE tr.task_id = ? AND ds.html_path IS NOT NULL
            UNION ALL
            SELECT 'detail_snapshot', ds.id, ds.text_path
            FROM task_runs tr
            JOIN detail_snapshots ds ON ds.run_id = tr.run_id
            WHERE tr.task_id = ? AND ds.text_path IS NOT NULL
            UNION ALL
            SELECT 'detail_snapshot', ds.id, ds.links_path
            FROM task_runs tr
            JOIN detail_snapshots ds ON ds.run_id = tr.run_id
            WHERE tr.task_id = ? AND ds.links_path IS NOT NULL
            UNION ALL
            SELECT 'detail_snapshot', ds.id, ds.images_path
            FROM task_runs tr
            JOIN detail_snapshots ds ON ds.run_id = tr.run_id
            WHERE tr.task_id = ? AND ds.images_path IS NOT NULL
            UNION ALL
            SELECT 'media_asset', m.id, m.local_path
            FROM task_runs tr
            JOIN listing_snapshots ls ON ls.run_id = tr.run_id
            JOIN media_assets m ON m.listing_id = ls.listing_id
            WHERE tr.task_id = ? AND m.local_path <> ''
            UNION ALL
            SELECT 'saved_report', sr.id, sr.path
            FROM saved_reports sr
            WHERE sr.task_id = ? AND sr.path IS NOT NULL
            """,
            (task_id,) * 11,
        )
    )


def add_saved_report(
    conn: sqlite3.Connection,
    *,
    path: Path,
    title: str,
    report_format: str,
    goal: str | None = None,
    task_id: int | None = None,
    run_id: int | None = None,
    listing_id: int | None = None,
) -> int:
    if task_id is not None and fetch_research_task(conn, task_id) is None:
        raise ValueError(f"Research task not found: {task_id}")
    cursor = conn.execute(
        """
        INSERT INTO saved_reports (
          task_id, run_id, listing_id, title, goal, format, path, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, run_id, listing_id, title, goal, report_format, str(path), utc_now_iso()),
    )
    if task_id is not None:
        _touch_task(conn, task_id)
    return int(cursor.lastrowid)


def fetch_page_snapshots_for_run(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, platform, query_text, title, url, screenshot_path, html_path, text_path,
                   links_path, link_count, access_blocked, created_at
            FROM page_snapshots
            WHERE run_id = ?
            ORDER BY id
            """,
            (run_id,),
        )
    )


def fetch_listing_snapshots_for_run(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
              ls.id,
              l.id AS listing_id,
              l.platform,
              l.url,
              ls.title,
              ls.price_text,
              ls.location,
              ls.seller_name,
              ls.description,
              ls.search_condition,
              ls.source_type,
              ls.source_label,
              ls.collected_at
            FROM listing_snapshots ls
            JOIN listings l ON l.id = ls.listing_id
            WHERE ls.run_id = ?
            ORDER BY ls.id
            """,
            (run_id,),
        )
    )


def fetch_latest_listing_snapshots_for_run(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
              ls.id,
              l.id AS listing_id,
              l.platform,
              l.url,
              ls.title,
              ls.price_text,
              ls.location,
              ls.seller_name,
              ls.description,
              ls.search_condition,
              ls.source_type,
              ls.source_label,
              ls.collected_at,
              (SELECT mi.observed_at FROM monitor_import_records mi
               WHERE mi.snapshot_id=ls.id) AS source_observed_at,
              (SELECT mi.seller_json FROM monitor_import_records mi
               WHERE mi.snapshot_id=ls.id) AS source_seller_json,
              (SELECT mi.evidence_stage FROM monitor_import_records mi
               WHERE mi.snapshot_id=ls.id) AS source_evidence_stage,
              (SELECT mi.source_round_id FROM monitor_import_records mi
               WHERE mi.snapshot_id=ls.id) AS source_round_id,
              ls.seller_credit_level,
              ls.seller_registered_days,
              ls.seller_sold_count,
              ls.seller_good_rate,
              ls.seller_realname_verified,
              ls.seller_reply_rate_24h,
              scoped.first_snapshot_id,
              (
                SELECT COUNT(*)
                FROM detail_snapshots ds
                WHERE ds.listing_id = l.id
              ) AS detail_snapshot_count,
              (
                SELECT COUNT(*)
                FROM media_assets ma
                WHERE ma.listing_id = l.id
                  AND ma.media_type = 'product_image_url'
              ) AS product_image_count,
              (
                SELECT COUNT(*)
                FROM media_assets ma
                WHERE ma.listing_id = l.id
                  AND ma.media_type = 'product_image_url'
                  AND ma.local_path <> ''
              ) AS downloaded_product_image_count,
              (
                SELECT COUNT(*)
                FROM media_assets ma
                JOIN ocr_results o ON o.media_asset_id = ma.id
                WHERE ma.listing_id = l.id
                  AND ma.media_type = 'product_image_url'
              ) AS ocr_result_count
            FROM listing_snapshots ls
            JOIN listings l ON l.id = ls.listing_id
            JOIN (
              SELECT listing_id, MIN(id) AS first_snapshot_id
              FROM listing_snapshots
              WHERE run_id = ?
              GROUP BY listing_id
            ) scoped ON scoped.listing_id = ls.listing_id
            WHERE ls.run_id = ?
              AND ls.id = (
                SELECT current.id
                FROM listing_snapshots current
                WHERE current.run_id = ls.run_id
                  AND current.listing_id = ls.listing_id
                ORDER BY CASE WHEN EXISTS (SELECT 1 FROM monitor_import_records mi
                    WHERE mi.snapshot_id=current.id AND mi.evidence_stage='search_card') THEN 0 ELSE 1 END DESC,
                  current.collected_at DESC, current.id DESC
                LIMIT 1
              )
            ORDER BY scoped.first_snapshot_id
            """,
            (run_id, run_id),
        )
    )


def fetch_task_report(
    conn: sqlite3.Connection,
    task_id: int,
    report_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, task_id, run_id, listing_id, title, goal, format, path, created_at
        FROM saved_reports
        WHERE task_id = ? AND id = ?
        """,
        (task_id, report_id),
    ).fetchone()


def add_media_asset(
    conn: sqlite3.Connection,
    listing_id: int,
    media_type: str,
    source_url: str | None,
    local_path: str,
) -> int:
    if source_url is not None:
        existing = conn.execute(
            """
            SELECT id
            FROM media_assets
            WHERE listing_id = ? AND media_type = ? AND source_url = ?
            """,
            (listing_id, media_type, source_url),
        ).fetchone()
        if existing is not None:
            return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO media_assets (listing_id, media_type, source_url, local_path, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (listing_id, media_type, source_url, local_path, utc_now_iso()),
    )
    return int(cursor.lastrowid)


def delete_legacy_media(conn: sqlite3.Connection, media_type: str = "image_url") -> int:
    cursor = conn.execute("DELETE FROM media_assets WHERE media_type = ?", (media_type,))
    return int(cursor.rowcount)


def fetch_media_assets(
    conn: sqlite3.Connection,
    media_type: str = "product_image_url",
    limit: int = 50,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, listing_id, media_type, source_url, local_path, created_at
            FROM media_assets
            WHERE media_type = ?
            ORDER BY id
            LIMIT ?
            """,
            (media_type, limit),
        )
    )


def fetch_pending_media(
    conn: sqlite3.Connection,
    limit: int,
    media_type: str = "product_image_url",
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, listing_id, source_url
            FROM media_assets
            WHERE media_type = ?
              AND source_url IS NOT NULL
              AND local_path = ''
            ORDER BY id
            LIMIT ?
            """,
            (media_type, limit),
        )
    )


def fetch_pending_media_for_run(
    conn: sqlite3.Connection,
    run_id: int,
    limit: int,
    media_type: str = "product_image_url",
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT m.id, m.listing_id, m.source_url, MIN(ls.id) AS first_snapshot_id
            FROM media_assets m
            JOIN listing_snapshots ls ON ls.listing_id = m.listing_id
            WHERE ls.run_id = ?
              AND m.media_type = ?
              AND m.source_url IS NOT NULL
              AND m.local_path = ''
            GROUP BY m.id, m.listing_id, m.source_url
            ORDER BY first_snapshot_id, m.id
            LIMIT ?
            """,
            (run_id, media_type, limit),
        )
    )


def fetch_pending_media_for_listing(
    conn: sqlite3.Connection,
    listing_id: int,
    limit: int,
    media_type: str = "product_image_url",
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, listing_id, source_url
            FROM media_assets
            WHERE listing_id = ?
              AND media_type = ?
              AND source_url IS NOT NULL
              AND local_path = ''
            ORDER BY id
            LIMIT ?
            """,
            (listing_id, media_type, limit),
        )
    )


def update_media_local_path(conn: sqlite3.Connection, media_id: int, local_path: Path) -> None:
    conn.execute(
        "UPDATE media_assets SET local_path = ? WHERE id = ?",
        (str(local_path), media_id),
    )


def fetch_downloaded_media(
    conn: sqlite3.Connection,
    media_type: str = "product_image_url",
    limit: int = 20,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, listing_id, source_url, local_path
            FROM media_assets
            WHERE media_type = ?
              AND local_path <> ''
            ORDER BY id
            LIMIT ?
            """,
            (media_type, limit),
        )
    )


def fetch_downloaded_media_for_run(
    conn: sqlite3.Connection,
    run_id: int,
    media_type: str = "product_image_url",
    limit: int = 20,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT m.id, m.listing_id, m.source_url, m.local_path, MIN(ls.id) AS first_snapshot_id
            FROM media_assets m
            JOIN listing_snapshots ls ON ls.listing_id = m.listing_id
            WHERE ls.run_id = ?
              AND m.media_type = ?
              AND m.local_path <> ''
            GROUP BY m.id, m.listing_id, m.source_url, m.local_path
            ORDER BY first_snapshot_id, m.id
            LIMIT ?
            """,
            (run_id, media_type, limit),
        )
    )


def fetch_downloaded_media_for_listing(
    conn: sqlite3.Connection,
    listing_id: int,
    media_type: str = "product_image_url",
    limit: int = 20,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, listing_id, source_url, local_path
            FROM media_assets
            WHERE listing_id = ?
              AND media_type = ?
              AND local_path <> ''
            ORDER BY id
            LIMIT ?
            """,
            (listing_id, media_type, limit),
        )
    )


def fetch_downloaded_media_pending_ocr(
    conn: sqlite3.Connection,
    media_type: str = "product_image_url",
    limit: int = 20,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT m.id, m.listing_id, m.source_url, m.local_path
            FROM media_assets m
            WHERE m.media_type = ?
              AND m.local_path <> ''
              AND NOT EXISTS (
                SELECT 1
                FROM ocr_results o
                WHERE o.media_asset_id = m.id
              )
            ORDER BY m.id
            LIMIT ?
            """,
            (media_type, limit),
        )
    )


def fetch_downloaded_media_pending_ocr_for_run(
    conn: sqlite3.Connection,
    run_id: int,
    media_type: str = "product_image_url",
    limit: int = 20,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT m.id, m.listing_id, m.source_url, m.local_path, MIN(ls.id) AS first_snapshot_id
            FROM media_assets m
            JOIN listing_snapshots ls ON ls.listing_id = m.listing_id
            WHERE ls.run_id = ?
              AND m.media_type = ?
              AND m.local_path <> ''
              AND NOT EXISTS (
                SELECT 1
                FROM ocr_results o
                WHERE o.media_asset_id = m.id
              )
            GROUP BY m.id, m.listing_id, m.source_url, m.local_path
            ORDER BY first_snapshot_id, m.id
            LIMIT ?
            """,
            (run_id, media_type, limit),
        )
    )


def fetch_downloaded_media_pending_ocr_for_listing(
    conn: sqlite3.Connection,
    listing_id: int,
    media_type: str = "product_image_url",
    limit: int = 20,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT m.id, m.listing_id, m.source_url, m.local_path
            FROM media_assets m
            WHERE m.listing_id = ?
              AND m.media_type = ?
              AND m.local_path <> ''
              AND NOT EXISTS (
                SELECT 1
                FROM ocr_results o
                WHERE o.media_asset_id = m.id
              )
            ORDER BY m.id
            LIMIT ?
            """,
            (listing_id, media_type, limit),
        )
    )


def add_ocr_result(
    conn: sqlite3.Connection,
    media_asset_id: int,
    ocr_text: str,
    detected_specs_json: str = "{}",
    risk_notes_json: str = "[]",
    confidence: float | None = None,
    backend: str | None = None,
    status: str = "ok",
    error: str | None = None,
) -> int:
    _ensure_ocr_schema(conn)
    cursor = conn.execute(
        """
        INSERT INTO ocr_results (
          media_asset_id, ocr_text, detected_specs_json, risk_notes_json,
          confidence, backend, status, error, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            media_asset_id,
            ocr_text,
            detected_specs_json,
            risk_notes_json,
            confidence,
            backend,
            status,
            error,
            utc_now_iso(),
        ),
    )
    return int(cursor.lastrowid)


def add_reference_evidence(
    conn: sqlite3.Connection,
    *,
    source_type: str,
    title: str,
    url: str,
    evidence_level: str,
    checked_at: str,
    run_id: int | None = None,
    listing_id: int | None = None,
    goal: str | None = None,
    platform: str | None = None,
    price_text: str | None = None,
    price_value: int | None = None,
    currency: str | None = None,
    model_key: str | None = None,
    spec_summary: str | None = None,
    comparable_scope: str | None = None,
    notes: str | None = None,
) -> int:
    _ensure_reference_evidence_schema(conn)
    cursor = conn.execute(
        """
        INSERT INTO reference_evidence (
          run_id, listing_id, goal, source_type, platform, title, url, price_text,
          price_value, currency, evidence_level, model_key, spec_summary,
          comparable_scope, notes, checked_at, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            listing_id,
            goal,
            source_type,
            platform,
            title,
            url,
            price_text,
            price_value,
            currency,
            evidence_level,
            model_key,
            spec_summary,
            comparable_scope,
            notes,
            checked_at,
            utc_now_iso(),
        ),
    )
    return int(cursor.lastrowid)


def fetch_reference_evidence(
    conn: sqlite3.Connection,
    *,
    run_id: int | None = None,
    listing_id: int | None = None,
    goal: str | None = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    _ensure_reference_evidence_schema(conn)
    clauses = []
    params: list[object] = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if listing_id is not None:
        clauses.append("listing_id = ?")
        params.append(listing_id)
    if goal:
        clauses.append("goal = ?")
        params.append(goal)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return list(
        conn.execute(
            f"""
            SELECT
              id, run_id, listing_id, goal, source_type, platform, title, url,
              price_text, price_value, currency, evidence_level, model_key,
              spec_summary, comparable_scope, notes, checked_at, created_at
            FROM reference_evidence
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        )
    )


def _ensure_ocr_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(ocr_results)").fetchall()}
    for column, definition in {
        "backend": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'ok'",
        "error": "TEXT",
    }.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE ocr_results ADD COLUMN {column} {definition}")


def _ensure_reference_evidence_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reference_evidence (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER,
          listing_id INTEGER,
          goal TEXT,
          source_type TEXT NOT NULL,
          platform TEXT,
          title TEXT NOT NULL,
          url TEXT NOT NULL,
          price_text TEXT,
          price_value INTEGER,
          currency TEXT,
          evidence_level TEXT NOT NULL,
          model_key TEXT,
          spec_summary TEXT,
          comparable_scope TEXT,
          notes TEXT,
          checked_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(run_id) REFERENCES search_runs(id),
          FOREIGN KEY(listing_id) REFERENCES listings(id)
        )
        """
    )


def _ensure_listing_snapshot_source_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(listing_snapshots)").fetchall()}
    for column, definition in {
        "source_type": "TEXT NOT NULL DEFAULT 'web_search'",
        "source_label": "TEXT NOT NULL DEFAULT '网页搜索'",
    }.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE listing_snapshots ADD COLUMN {column} {definition}")


def _ensure_listing_snapshot_card_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(listing_snapshots)").fetchall()}
    if "search_condition" not in columns:
        conn.execute("ALTER TABLE listing_snapshots ADD COLUMN search_condition TEXT")


def _ensure_listing_snapshot_seller_schema(conn: sqlite3.Connection) -> None:
    """Add structured seller columns to listing_snapshots if absent (MTOP pc.detail data)."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(listing_snapshots)").fetchall()}
    for column, definition in {
        "seller_credit_level": "TEXT",
        "seller_registered_days": "INTEGER",
        "seller_sold_count": "INTEGER",
        "seller_good_rate": "TEXT",
        "seller_realname_verified": "INTEGER",
        "seller_reply_rate_24h": "TEXT",
    }.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE listing_snapshots ADD COLUMN {column} {definition}")


def update_listing_snapshot_seller_fields(
    conn: sqlite3.Connection, snapshot_id: int, **fields
) -> int:
    """Update structured seller columns on an existing listing_snapshot row.

    Used to backfill seller fields from DOM detail text for runs collected
    before the MTOP pc.detail sellerDO parser was available.
    """
    allowed = (
        "seller_credit_level",
        "seller_registered_days",
        "seller_sold_count",
        "seller_good_rate",
        "seller_realname_verified",
        "seller_reply_rate_24h",
    )
    updates: list[str] = []
    values: list[object] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "seller_realname_verified" and isinstance(value, bool):
            value = 1 if value else 0
        updates.append(f"{key} = ?")
        values.append(value)
    if not updates:
        return 0
    values.append(snapshot_id)
    cursor = conn.execute(
        f"UPDATE listing_snapshots SET {', '.join(updates)} WHERE id = ?",
        values,
    )
    return cursor.rowcount


def _ensure_seller_items_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(seller_items)").fetchall()}
    if not columns:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seller_items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              seller_listing_id INTEGER NOT NULL,
              seller_name TEXT,
              item_id_ext TEXT,
              title TEXT,
              url TEXT,
              source_run_id INTEGER,
              collected_at TEXT NOT NULL,
              FOREIGN KEY(seller_listing_id) REFERENCES listings(id)
            )
            """
        )


def _ensure_detail_snapshot_attribute_schema(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(detail_snapshots)").fetchall()
    }
    if "attributes_json" not in columns:
        conn.execute(
            "ALTER TABLE detail_snapshots "
            "ADD COLUMN attributes_json TEXT NOT NULL DEFAULT '{}'"
        )
    if "attributes_source" not in columns:
        conn.execute("ALTER TABLE detail_snapshots ADD COLUMN attributes_source TEXT")


def add_seller_items(
    conn: sqlite3.Connection,
    seller_listing_id: int,
    seller_name: str | None,
    items: list[dict],
    source_run_id: int | None = None,
) -> int:
    """Persist a seller's other active listings from MTOP sellerDO.sellerItems.

    Replaces any previously stored items for this seller_listing_id so re-capture
    keeps the set current. Returns the number of items stored.
    """
    conn.execute(
        "DELETE FROM seller_items WHERE seller_listing_id = ?",
        (seller_listing_id,),
    )
    count = 0
    for item in items:
        item_id_ext = str(item.get("itemId") or "") or None
        title = (item.get("title") or "").strip() or None
        url = item.get("link") or (
            f"https://www.goofish.com/item?id={item_id_ext}" if item_id_ext else None
        )
        if not title and not item_id_ext:
            continue
        conn.execute(
            """
            INSERT INTO seller_items
              (seller_listing_id, seller_name, item_id_ext, title, url, source_run_id, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (seller_listing_id, seller_name, item_id_ext, title, url, source_run_id, utc_now_iso()),
        )
        count += 1
    return count


def fetch_seller_items_for_listing(
    conn: sqlite3.Connection, listing_id: int
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT item_id_ext, title, url, source_run_id, collected_at
            FROM seller_items
            WHERE seller_listing_id = ?
            ORDER BY id
            """,
            (listing_id,),
        )
    )


def fetch_seller_items_for_listing_in_runs(
    conn: sqlite3.Connection,
    listing_id: int,
    run_ids: list[int],
) -> list[sqlite3.Row]:
    if not run_ids:
        return []
    placeholders = ",".join("?" for _ in run_ids)
    return list(
        conn.execute(
            f"""
            SELECT item_id_ext, title, url, source_run_id, collected_at
            FROM seller_items
            WHERE seller_listing_id = ?
              AND source_run_id IN ({placeholders})
            ORDER BY id
            """,
            (listing_id, *run_ids),
        )
    )


def fetch_listing_urls_for_run(conn: sqlite3.Connection, run_id: int, limit: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT l.url
        FROM listing_snapshots ls
        JOIN listings l ON l.id = ls.listing_id
        WHERE ls.run_id = ?
        ORDER BY ls.id
        LIMIT ?
        """,
        (run_id, limit),
    ).fetchall()
    return [str(row["url"]) for row in rows]


def listing_url_belongs_to_run(conn: sqlite3.Connection, run_id: int, url: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM listing_snapshots ls
        JOIN listings l ON l.id = ls.listing_id
        WHERE ls.run_id = ? AND l.url = ?
        LIMIT 1
        """,
        (run_id, url),
    ).fetchone()
    return row is not None


def fetch_listing_urls_for_run_needing_detail(conn: sqlite3.Connection, run_id: int, limit: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT l.url, MIN(ls.id) AS first_snapshot_id
        FROM listing_snapshots ls
        JOIN listings l ON l.id = ls.listing_id
        WHERE ls.run_id = ?
          AND NOT EXISTS (
            SELECT 1
            FROM detail_snapshots ds
            WHERE ds.listing_id = l.id
          )
        GROUP BY l.id, l.url
        ORDER BY first_snapshot_id
        LIMIT ?
        """,
        (run_id, limit),
    ).fetchall()
    return [str(row["url"]) for row in rows]


def fetch_detail_snapshots_for_run(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, listing_id, run_id, url, title, screenshot_path, text_path, images_path, image_count,
                   access_blocked, attributes_json, attributes_source, created_at
            FROM detail_snapshots
            WHERE run_id = ?
            ORDER BY id
            """,
            (run_id,),
        )
    )


def fetch_latest_detail_snapshot_for_listing(conn: sqlite3.Connection, listing_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, listing_id, run_id, url, title, text_path, links_path, images_path,
               link_count, image_count, access_blocked, attributes_json, attributes_source,
               created_at
        FROM detail_snapshots
        WHERE listing_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (listing_id,),
    ).fetchone()


def fetch_latest_listing_snapshot(conn: sqlite3.Connection, listing_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
          ls.id,
          l.id AS listing_id,
          l.platform,
          l.url,
          ls.title,
          ls.price_text,
          ls.location,
          ls.seller_name,
          ls.description,
          ls.source_type,
          ls.source_label,
          ls.collected_at
        FROM listing_snapshots ls
        JOIN listings l ON l.id = ls.listing_id
        WHERE l.id = ?
          AND (
            ls.price_text IS NOT NULL
            OR ls.seller_name IS NOT NULL
            OR length(ls.description) > 80
          )
        ORDER BY ls.id DESC
        LIMIT 1
        """,
        (listing_id,),
    ).fetchone()


def fetch_latest_ocr_results_for_listing(conn: sqlite3.Connection, listing_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
              m.id AS media_asset_id,
              m.local_path,
              latest.ocr_text,
              latest.detected_specs_json,
              latest.backend,
              latest.status,
              latest.error,
              latest.created_at
            FROM media_assets m
            JOIN (
              SELECT o.*
              FROM ocr_results o
              JOIN (
                SELECT media_asset_id, MAX(id) AS latest_ocr_id
                FROM ocr_results
                GROUP BY media_asset_id
              ) pick ON pick.latest_ocr_id = o.id
            ) latest ON latest.media_asset_id = m.id
            WHERE m.listing_id = ?
              AND m.media_type = 'product_image_url'
            ORDER BY m.id
            """,
            (listing_id,),
        )
    )
