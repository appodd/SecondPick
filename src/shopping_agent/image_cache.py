"""Shared P5 byte/cache publication, independent of model credentials and approval."""
from shopping_agent.image_safety import fetch_image
from shopping_agent.product_media import read_bytes


def prepare_cached_image(config, media_id, listing_id, source_url, *, authorize,
                         connection, resolver=None, transport=None):
    def row():
        with connection() as c:
            r=c.execute("SELECT * FROM media_assets WHERE id=? AND listing_id=? AND media_type='product_image_url'",(media_id,listing_id)).fetchone()
        if r is None or r['source_url']!=source_url:raise ValueError('image_source_changed')
        return r
    authorize();current=row()
    try:
        _,meta=read_bytes(current,config.media_dir)
        return dict(meta,local_path=current['local_path'],cache_reused=True)
    except (ValueError,OSError):pass
    # Reuse a validated cache for the same original URL, including other records.
    with connection() as c:
        others=c.execute("SELECT * FROM media_assets WHERE source_url=? AND local_path!='' AND media_type='product_image_url' LIMIT 10",(source_url,)).fetchall()
    for other in others:
        try:_,meta=read_bytes(other,config.media_dir)
        except (ValueError,OSError):continue
        path=other['local_path'];reused=True;break
    else:
        authorize()
        data,meta=fetch_image(source_url,resolver=resolver,transport=transport)
        authorize();row()
        # Existing P4-A/P5 immutable, content-addressed byte publication.
        from shopping_agent.visual_investigations import publish
        path=str(publish(data,meta,config.media_dir));reused=False
    authorize();row()
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        updated=c.execute("UPDATE media_assets SET local_path=? WHERE id=? AND listing_id=? AND source_url=?",(str(path),media_id,listing_id,source_url))
        if updated.rowcount!=1:raise ValueError('image_source_changed')
    return dict(meta,local_path=str(path),cache_reused=reused)
