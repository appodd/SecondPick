"""Read-only galleries and explicit image-only preparation using P5, never AI."""
import secrets,threading,time,sqlite3
from typing import Annotated
from fastapi import Depends,FastAPI,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field,StrictBool
from shopping_agent.config import AppConfig
from shopping_agent.web.dependencies import get_config
from shopping_agent import product_media

class Selection(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    media_ids:list[int]=Field(min_length=1,max_length=3)
    source_signature:str=Field(pattern='^[a-f0-9]{64}$')
class Confirmation(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    ticket:str=Field(min_length=20,max_length=100)
    confirmed:StrictBool

def register_image_routes(app:FastAPI):
    tickets={};lock=threading.Lock()
    def ro(config):
        c=sqlite3.connect(config.database_path.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c
    def local(request):
        from shopping_agent.web.app import _same_loopback_origin
        if not _same_loopback_origin(request.headers.get('origin',''),request.url):raise HTTPException(403,'需要本机页面的明确图片授权')
    @app.get('/api/tasks/{task_id}/listings/{listing_id}/images')
    def images(task_id:int,listing_id:int,request:Request,config:Annotated[AppConfig,Depends(get_config)]):
        with ro(config) as c:
            try:value=product_media.gallery(c,config.media_dir,task_id,listing_id)
            except ValueError:raise HTTPException(404,'商品不属于当前项目')
        value['preparation_enabled']=getattr(request.app.state,'visual_image_fetch_enabled',False) is True
        value['notice']='仅本地缓存用于显示；读取不会下载、上传或调用模型。'
        return value
    @app.get('/api/tasks/{task_id}/listings/{listing_id}/images/{media_id}/content')
    def content(task_id:int,listing_id:int,media_id:int,sha256:str,config:Annotated[AppConfig,Depends(get_config)]):
        with ro(config) as c:
            try:
                product_media.belongs(c,task_id,listing_id)
                row=c.execute("SELECT * FROM media_assets WHERE id=? AND listing_id=? AND media_type='product_image_url'",(media_id,listing_id)).fetchone()
                if row is None:raise ValueError('image_outside_listing')
                data,meta=product_media.read_bytes(row,config.media_dir)
                if meta['sha256']!=sha256:raise ValueError('image_version_changed')
            except (ValueError,OSError):raise HTTPException(404,'图片缓存不可用或版本已变化，请重新检查图片列表')
        return Response(data,media_type=meta['mime'],headers={'Cache-Control':'private, max-age=86400, immutable','X-Content-Type-Options':'nosniff'})
    @app.post('/api/tasks/{task_id}/listings/{listing_id}/images/prepare-preview')
    def preview(task_id:int,listing_id:int,body:Selection,request:Request,config:Annotated[AppConfig,Depends(get_config)]):
        local(request)
        if getattr(app.state,'visual_image_fetch_enabled',False) is not True:raise HTTPException(403,'服务端图片获取关闭；不需启用视觉模型或恢复研究')
        with ro(config) as c:value=product_media.gallery(c,config.media_dir,task_id,listing_id)
        if value['source_signature']!=body.source_signature:raise ValueError('image_sources_changed')
        index={i['id']:i for i in value['images']}
        if len(set(body.media_ids))!=len(body.media_ids) or not set(body.media_ids)<=set(index):raise ValueError('image_selection_outside_listing')
        chosen=[index[i] for i in body.media_ids]
        with lock:
            for k in list(tickets):
                if tickets[k]['expires_at']<=time.time():del tickets[k]
            if len(tickets)>=64:raise ValueError('image_confirmation_limit')
            ticket=secrets.token_urlsafe(32);tickets[ticket]=dict(task=task_id,listing=listing_id,signature=body.source_signature,chosen=chosen,expires_at=time.time()+300,used=False)
        return dict(ticket=ticket,media=[{k:i[k] for k in ('id','source_url')} for i in chosen],expires_at=tickets[ticket]['expires_at'],model_authorized=False,notice='只获取所选已有URL，最多三张；不上传模型、不创建研究；失败不自动重试。')
    @app.post('/api/tasks/{task_id}/listings/{listing_id}/images/prepare')
    def prepare(task_id:int,listing_id:int,body:Confirmation,request:Request,config:Annotated[AppConfig,Depends(get_config)]):
        local(request)
        with lock:
            grant=tickets.get(body.ticket)
            if not body.confirmed or not grant or grant['used'] or grant['expires_at']<=time.time() or (grant['task'],grant['listing'])!=(task_id,listing_id):raise ValueError('image_approval_missing_expired_or_used')
            grant['used']=True
        with ro(config) as c:current=product_media.gallery(c,config.media_dir,task_id,listing_id)
        if current['source_signature']!=grant['signature']:raise ValueError('image_sources_changed')
        from shopping_agent.web.visual_investigation_routes import service
        s=service(app)
        plans=s.propose(task_id,[listing_id],media_ids=[i['id'] for i in grant['chosen']],media_only=True,image_request_key=body.ticket)['items']
        row=next(r for r in plans if r['listing_id']==listing_id and r['plan'].get('media_only') and [m['id'] for m in r['plan']['media']]==[i['id'] for i in grant['chosen']])
        def check():
            if app.state.visual_image_fetch_enabled is not True or grant['expires_at']<=time.time():raise ValueError('image_preparation_authorization_expired_or_disabled')
        return s.prepare(task_id,row['id'],image_only_check=check)
