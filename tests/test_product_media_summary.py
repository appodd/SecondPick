"""Display summaries must never decode an entire project's image library."""
import hashlib
import io
from pathlib import Path
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from shopping_agent.db import add_media_asset
from shopping_agent import product_media
from shopping_agent.web.app import create_app
from test_project_research import research, ingest


def png():
    out=io.BytesIO();Image.new('RGB',(12,12),'blue').save(out,format='PNG');return out.getvalue()


def asset(p,listing,path=None):
    root=p.config.media_dir;root.mkdir(parents=True,exist_ok=True)
    data=png();path=path or root/(hashlib.sha256(data).hexdigest()+'.png')
    path.write_bytes(data)
    with p.source_db() as db:
        media=add_media_asset(db,listing,'product_image_url',f'https://img.alicdn.com/{listing}.png',str(path))
    return media,path,data


def test_overview_reads_cached_covers_without_gallery_or_decoder(research,tmp_path,monkeypatch):
    p=research;p.config=p.config.model_copy(update={'media_dir':tmp_path/'media'})
    listings=[ingest(p,url=f'https://www.goofish.com/item?id=summary-{i}') for i in range(6)]
    for listing in listings:asset(p,listing)
    monkeypatch.setattr(product_media,'gallery',lambda *a,**kw:pytest.fail('Overview must not expand full galleries'))
    monkeypatch.setattr(product_media,'validate_bytes',lambda *a,**kw:pytest.fail('Overview must not spawn image decoders'))
    value=p.overview(p.task_id)
    assert len(value['cards'])==6
    assert all(c['product_images']['state']=='local_cached' and c['image_url'] for c in value['cards'])
    assert not p.runtime.requests


def test_summary_has_no_database_writes_and_requires_project_ownership(research,tmp_path):
    p=research;p.config=p.config.model_copy(update={'media_dir':tmp_path/'media'})
    listing=ingest(p);mid,path,data=asset(p,listing)
    with p.source_db() as db:
        changes=db.total_changes;value=product_media.summary(db,p.config.media_dir,p.task_id,listing)
        assert db.total_changes==changes
        assert value['cover_media_id']==mid and value['local_count']==1
        assert value['cover_url'].endswith('sha256='+hashlib.sha256(data).hexdigest())
        with pytest.raises(ValueError):product_media.summary(db,p.config.media_dir,99999,listing)


@pytest.mark.parametrize('problem',['outside','tampered','missing','too_large'])
def test_summary_rejects_unusable_paths_and_tampered_addressed_bytes(research,tmp_path,problem):
    p=research;p.config=p.config.model_copy(update={'media_dir':tmp_path/'media'});listing=ingest(p)
    mid,path,_=asset(p,listing,tmp_path/'outside.png' if problem=='outside' else None)
    if problem=='tampered':path.write_bytes(b'bad image data')
    if problem=='missing':path.unlink()
    if problem=='too_large':
        with path.open('wb') as stream:stream.truncate(product_media.ImageLimits().max_bytes+1)
    with p.source_db() as db:value=product_media.summary(db,p.config.media_dir,p.task_id,listing)
    assert value['state']=='cache_invalid' and value['cover_url'] is None


def test_served_content_still_validates_bytes_and_exact_version(tmp_path,monkeypatch):
    config=tmp_path/'config.toml';media=tmp_path/'media'
    config.write_text(f'database_path="{(tmp_path/"app.sqlite").as_posix()}"\nmedia_dir="{media.as_posix()}"\n',encoding='utf8')
    app=create_app(config,tmp_path/'settings.json')
    with TestClient(app,base_url='http://127.0.0.1') as client:
        p=app.state.project_research;p.task_id=p.create('test','synthetic',None,[],[],2,False)['id']
        listing=ingest(p);mid,path,data=asset(p,listing)
        with p.source_db() as db:cover=product_media.summary(db,media,p.task_id,listing)['cover_url']
        response=client.get(cover)
        assert response.status_code==200 and response.content==data and response.headers['content-type']=='image/png'
        assert client.get(cover.replace(hashlib.sha256(data).hexdigest(),'0'*64)).status_code==404
        calls=[]
        def reject(*a,**kw):calls.append(True);raise ValueError('invalid pixels')
        monkeypatch.setattr(product_media,'validate_bytes',reject)
        assert client.get(cover).status_code==404
        assert calls  # Display projection never bypasses the content validator.
