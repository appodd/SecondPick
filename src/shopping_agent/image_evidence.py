"""Versioned, approved image files on existing media assets. No auto downloads.

One additive table is an attempt ledger; stable evidence IDs address content,
not attempts. This module never starts a BrowserJob, AgentRun or model.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from shopping_agent.image_safety import ImageLimits,ImageSafetyError,fetch_image

SCHEMA='''
CREATE TABLE IF NOT EXISTS media_image_evidence (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 task_id INTEGER NOT NULL REFERENCES research_tasks(id),
 media_id INTEGER NOT NULL REFERENCES media_assets(id),
 approval_id INTEGER NOT NULL REFERENCES action_requests(id),
 request_key TEXT NOT NULL UNIQUE,
 source_url TEXT NOT NULL,
 source_detail_id INTEGER REFERENCES detail_snapshots(id),
 state TEXT NOT NULL CHECK(state IN ('running','saved','failed')),
 sha256 TEXT, local_path TEXT, mime TEXT, bytes INTEGER, width INTEGER, height INTEGER,
 created_at TEXT NOT NULL, verified_at TEXT, error TEXT,
 UNIQUE(approval_id,media_id));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_image_capture ON media_image_evidence(media_id) WHERE state='running';
'''


def exists(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name='media_image_evidence' AND type='table'").fetchone() is not None


def version_id(row,listing):return f"image:{listing}:{row['media_id']}:{row['sha256']}"


def scoped_media(conn,task,media):
    row=conn.execute('''SELECT m.* FROM media_assets m WHERE m.id=? AND m.media_type='product_image_url'
        AND EXISTS(SELECT 1 FROM listing_snapshots ls JOIN task_runs tr ON tr.run_id=ls.run_id WHERE tr.task_id=? AND ls.listing_id=m.listing_id)''',(media,task)).fetchone()
    if row is None:raise ImageSafetyError('image_outside_project')
    return dict(row)


def _publish(data,metadata,root):
    root=Path(root)
    if root.is_symlink():raise ImageSafetyError('image_store_symlink')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    directory=root/'image-evidence'
    if directory.is_symlink():raise ImageSafetyError('image_store_symlink')
    directory.mkdir(exist_ok=True,mode=0o700)
    suffix={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[metadata['mime']]
    path=directory/(metadata['sha256']+suffix)
    def existing():
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=metadata['sha256']:
            raise ImageSafetyError('existing_image_content_invalid')
    if path.exists():existing();return path.resolve()
    fd,temp=tempfile.mkstemp(prefix='.image-',suffix='.tmp',dir=directory)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        try:os.link(temp,path) # Atomic, exclusive publication. Never replace historical bytes.
        except FileExistsError:existing()
        return path.resolve()
    finally:
        Path(temp).unlink(missing_ok=True)


def save_approved_image(config,task,media,approval,*,limits=ImageLimits(),resolver=None,transport=None):
    """Explicit internal executor only, not registered as an automatic/API action.

    It requires an existing approved media-only action and the same profile lock.
    No automatic retries; a crash leaves a visible running attempt for review.
    """
    from shopping_agent.db import connect,utc_now_iso
    from shopping_agent.detail import browser_profile_lock
    key=f'image-download:{approval}:{media}'
    with connect(config.database_path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        item=scoped_media(conn,task,media)
        request=conn.execute('SELECT * FROM action_requests WHERE id=? AND task_id=?',(approval,task)).fetchone()
        if not request or request['state']!='approved' or set(json.loads(request['actions_json']))!={'media'} or item['listing_id'] not in json.loads(request['listing_ids_json']):
            raise ImageSafetyError('image_specific_approval_required')
        previous=conn.execute('SELECT * FROM media_image_evidence WHERE request_key=?',(key,)).fetchone()
        if previous:return dict(previous)
        if conn.execute('SELECT COUNT(*) FROM media_image_evidence WHERE approval_id=?',(approval,)).fetchone()[0]>=3:raise ImageSafetyError('image_approval_limit')
        if conn.execute("SELECT 1 FROM browser_jobs WHERE state IN ('queued','running')").fetchone() or conn.execute("SELECT 1 FROM monitors WHERE state IN ('running','waiting')").fetchone():
            raise ImageSafetyError('image_browser_or_monitor_busy')
        if conn.execute("SELECT 1 FROM operations WHERE task_id=? AND state IN ('queued','running')",(task,)).fetchone():raise ImageSafetyError('image_research_busy')
        details=conn.execute('SELECT d.id,d.images_path FROM detail_snapshots d JOIN task_runs tr ON tr.run_id=d.run_id WHERE tr.task_id=? AND d.listing_id=? ORDER BY d.id DESC',(task,item['listing_id'])).fetchall()
        source=None
        for d in details:
            p=Path(d['images_path'] or '')
            if p.is_file() and item['source_url'] in p.read_text(encoding='utf-8',errors='replace').splitlines():source=d['id'];break
        try:
            cursor=conn.execute("INSERT INTO media_image_evidence(task_id,media_id,approval_id,request_key,source_url,source_detail_id,state,created_at) VALUES(?,?,?,?,?,?,'running',?)",(task,media,approval,key,item['source_url'],source,utc_now_iso()))
        except sqlite3.IntegrityError as exc:raise ImageSafetyError('image_capture_busy') from exc
        record=cursor.lastrowid
    try:
        # Never steal a stale lock or stop an existing collector.
        with browser_profile_lock(config.browser_profile_dir,timeout_seconds=0,stale_after_seconds=float('inf')):
            research=config.database_path.with_suffix('.secondpick.sqlite')
            if research.exists():
                with sqlite3.connect(research.resolve().as_uri()+'?mode=ro',uri=True) as studies:
                    if studies.execute("SELECT 1 FROM studies WHERE state IN ('queued','running')").fetchone():raise ImageSafetyError('image_research_busy')
            data,metadata=fetch_image(item['source_url'],limits=limits,resolver=resolver,transport=transport)
            path=_publish(data,metadata,config.media_dir)
            with connect(config.database_path) as conn:
                conn.execute("UPDATE media_image_evidence SET state='saved',sha256=?,local_path=?,mime=?,bytes=?,width=?,height=?,verified_at=? WHERE id=?",(metadata['sha256'],str(path),metadata['mime'],metadata['bytes'],metadata['width'],metadata['height'],utc_now_iso(),record))
                conn.execute('UPDATE media_assets SET local_path=? WHERE id=?',(str(path),media))
    except Exception as exc:
        with connect(config.database_path) as conn:conn.execute("UPDATE media_image_evidence SET state='failed',error=? WHERE id=?",(str(exc) if isinstance(exc,ImageSafetyError) else 'image_capture_failed',record))
    with connect(config.database_path) as conn:return dict(conn.execute('SELECT * FROM media_image_evidence WHERE id=?',(record,)).fetchone())


def manifest_entry(conn,task,record,root):
    row=conn.execute("SELECT * FROM media_image_evidence WHERE id=? AND state='saved'",(record,)).fetchone()
    if row is None:raise ImageSafetyError('image_not_saved')
    if row['task_id']!=task:raise ImageSafetyError('image_outside_project')
    item=scoped_media(conn,task,row['media_id'])
    root=Path(root).resolve();path=Path(row['local_path'])
    if path.is_symlink() or not path.resolve().is_relative_to(root):raise ImageSafetyError('image_path_outside_store')
    if not path.is_file() or path.stat().st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ImageSafetyError('image_hash_mismatch')
    return dict(evidence_id=version_id(row,item['listing_id']),listing_id=item['listing_id'],media_id=item['id'],record_id=row['id'],sha256=row['sha256'],local_path=str(path.resolve()),bytes=row['bytes'],width=row['width'],height=row['height'],mime=row['mime'],source_url=row['source_url'],source_detail_id=row['source_detail_id'])


def image_status(conn,media):
    original=conn.execute('SELECT local_path FROM media_assets WHERE id=?',(media,)).fetchone()
    default='legacy_unverified' if original and original['local_path'] else 'url_only'
    if not exists(conn):return dict(state=default,observed=False)
    rows=conn.execute('SELECT * FROM media_image_evidence WHERE media_id=? ORDER BY id DESC',(media,)).fetchall()
    saved=next((r for r in rows if r['state']=='saved'),None)
    if saved:
        item=conn.execute('SELECT listing_id FROM media_assets WHERE id=?',(media,)).fetchone()
        path=Path(saved['local_path'])
        if saved['bytes']>4*1024*1024 or path.is_symlink() or not path.is_file() or path.stat().st_size!=saved['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=saved['sha256']:return dict(state='unreadable',observed=False)
        return dict(state='saved',observed=False,evidence_id=version_id(saved,item['listing_id']),sha256=saved['sha256'],bytes=saved['bytes'],width=saved['width'],height=saved['height'],mime=saved['mime'],first_saved_at=min(r['created_at'] for r in rows if r['state']=='saved' and r['sha256']==saved['sha256']),verified_at=saved['verified_at'])
    return dict(state='failed' if rows and rows[0]['state']=='failed' else 'pending' if rows else default,observed=False)


def input_uses(research_path,task,evidence_id):
    """Read only actual frozen manifests; constructed is never 'viewed'."""
    if not Path(research_path).is_file():return []
    with sqlite3.connect(Path(research_path).resolve().as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='studies'").fetchone():return []
        rows=conn.execute('SELECT id,state,request_json FROM studies WHERE task_id=? AND request_json LIKE ? ORDER BY id DESC',(task,'%'+evidence_id+'%')).fetchall()
    result=[]
    for row in rows:
        try:ctx=json.loads(row['request_json']).get('review_context',{}).get('visual_inputs',{})
        except (ValueError,AttributeError):continue
        if ctx.get('version')!=1 or ctx.get('task_id')!=task or ctx.get('study_id')!=row['id'] or type(ctx.get('goal_revision')) is not int or ctx['goal_revision']<=0:continue
        if any(i.get('evidence_id')==evidence_id for i in ctx.get('images',[])):
            result.append(dict(study_id=row['id'],goal_revision=ctx.get('goal_revision'),study_state=row['state'],input_constructed=True,remote_received=False,observed=False))
    return result
