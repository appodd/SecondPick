"""Read-only display projection. No downloads, models, research policy or DDL."""
from pathlib import Path
import json
from shopping_agent.image_safety import ImageLimits,checked_url,validate_bytes
from shopping_agent.vision import encode,sha

def belongs(conn,task,listing):
    if not conn.execute('SELECT 1 FROM listing_snapshots s JOIN task_runs t ON t.run_id=s.run_id WHERE t.task_id=? AND s.listing_id=? LIMIT 1',(task,listing)).fetchone():raise ValueError('image_outside_project')

def read_bytes(row,root):
    if not row['local_path']:raise ValueError('image_not_prepared')
    p=Path(row['local_path']);root=Path(root).resolve()
    if p.is_symlink() or not p.resolve().is_relative_to(root):raise ValueError('image_path_outside_store')
    if not p.is_file() or p.stat().st_size>ImageLimits().max_bytes:raise ValueError('image_cache_missing_or_invalid')
    checked_url(row['source_url'],ImageLimits())
    data=p.read_bytes();metadata=validate_bytes(data)
    return data,metadata

def gallery(conn,root,task,listing):
    belongs(conn,task,listing)
    rows=conn.execute("SELECT id,listing_id,source_url,local_path,created_at FROM media_assets WHERE listing_id=? AND media_type='product_image_url' ORDER BY id LIMIT 30",(listing,)).fetchall()
    failed=set()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='project_investigations'").fetchone():
        for r in conn.execute("SELECT plan_json,outcome_json FROM project_investigations WHERE task_id=? AND listing_id=? ORDER BY id DESC LIMIT 50",(task,listing)):
            try:
                p,o=json.loads(r[0]),json.loads(r[1])
                if o.get('error')=='image_preparation_failed':failed.update(i['id'] for i in p.get('media',[]))
            except (ValueError,KeyError,TypeError):continue
    images=[];seen=set()
    for row in rows:
        try:checked_url(row['source_url'],ImageLimits())
        except (ValueError,TypeError):continue
        if row['source_url'] in seen:continue
        seen.add(row['source_url'])
        item=dict(id=row['id'],url=row['source_url'],source_url=row['source_url'],created_at=row['created_at'],state='fetch_failed' if row['id'] in failed else 'not_prepared',display_url=None,sha256=None,width=None,height=None,mime=None)
        if row['local_path']:
            try:
                _,meta=read_bytes(row,root)
                item.update(state='local_available',sha256=meta['sha256'],width=meta['width'],height=meta['height'],mime=meta['mime'],bytes=meta['bytes'],display_url=f'/api/tasks/{task}/listings/{listing}/images/{row["id"]}/content?sha256={meta["sha256"]}')
            except (ValueError,OSError):item['state']='cache_invalid'
        images.append(item)
    local=[i for i in images if i['state']=='local_available']
    state='local_available' if local else 'cache_invalid' if any(i['state']=='cache_invalid' for i in images) else 'fetch_failed' if failed and images else 'not_prepared' if images else 'source_missing'
    try:
        from shopping_agent.auto_covers import load_state
        from types import SimpleNamespace
        cv=load_state(SimpleNamespace(database_path=conn.execute('PRAGMA database_list').fetchone()[2])) if not local and images else None
        job=(cv or {}).get('jobs',{}).get(f'{task}:{listing}')
        if not local and images and job:
            state={'queued':'waiting','fetching':'preparing','failed':'fetch_failed'}.get(job['state'],state)
    except (OSError,ValueError,TypeError):pass
    signature=sha(encode([task,listing,[(i['id'],i['source_url'],i['sha256'],i['state']) for i in images]]))
    return dict(listing_id=listing,images=images,state=state,source_count=len(images),local_count=len(local),cover_url=local[0]['display_url'] if local else None,cover_media_id=local[0]['id'] if local else None,source_signature=signature)

def summary(conn,root,task,listing):
    """Cheap list projection; image decoding belongs to gallery/content reads.

    local_cached means bounded local bytes exist, not that this request decoded
    the image. The content endpoint still checks ownership, path, exact SHA and
    validates the actual image before returning any bytes. This projection is
    never an image approval, evidence manifest, or model input.
    """
    belongs(conn,task,listing)
    root=Path(root).resolve()
    rows=conn.execute("SELECT id,source_url,local_path FROM media_assets WHERE listing_id=? AND media_type='product_image_url' ORDER BY id LIMIT 30",(listing,)).fetchall()
    seen=set();cached=[];invalid=False
    for row in rows:
        try:checked_url(row['source_url'],ImageLimits())
        except (ValueError,TypeError):continue
        if row['source_url'] in seen:continue
        seen.add(row['source_url'])
        if not row['local_path']:continue
        try:
            path=Path(row['local_path'])
            if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('image_path_outside_store')
            if not path.is_file() or not 0<path.stat().st_size<=ImageLimits().max_bytes:raise ValueError('image_cache_missing_or_invalid')
            cached.append((row,path))
        except (ValueError,OSError):invalid=True
    cover_url=None;cover_id=None;local_count=len(cached)
    for row,path in cached:
        try:
            with path.open('rb') as stream:data=stream.read(ImageLimits().max_bytes+1)
            if not data or len(data)>ImageLimits().max_bytes:raise ValueError('image_cache_missing_or_invalid')
            digest=sha(data)
            if len(path.stem)==64 and all(c in '0123456789abcdef' for c in path.stem.lower()) and path.stem.lower()!=digest:
                raise ValueError('cached_image_content_invalid')
            cover_url=f'/api/tasks/{task}/listings/{listing}/images/{row["id"]}/content?sha256={digest}'
            cover_id=row['id'];break
        except (ValueError,OSError):invalid=True;local_count-=1
    state='local_cached' if cover_url else 'cache_invalid' if invalid else 'not_prepared' if seen else 'source_missing'
    if not cover_url and seen:
        try:
            from shopping_agent.auto_covers import load_state
            from types import SimpleNamespace
            value=load_state(SimpleNamespace(database_path=conn.execute('PRAGMA database_list').fetchone()[2]))
            job=(value or {}).get('jobs',{}).get(f'{task}:{listing}')
            if job:state={'queued':'waiting','fetching':'preparing','failed':'fetch_failed'}.get(job['state'],state)
        except (OSError,ValueError,TypeError):pass
    return dict(state=state,source_count=len(seen),local_count=local_count,cover_url=cover_url,cover_media_id=cover_id)
