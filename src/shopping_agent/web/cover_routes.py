"""Local display-cache preferences. No execution, model or historic-backfill endpoint."""
from fastapi import Request,HTTPException
from pydantic import BaseModel,ConfigDict,StrictBool,Field
from shopping_agent.auto_covers import AutoCovers
from shopping_agent.web.dependencies import get_config


class CoverSetting(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    enabled:StrictBool
    expected_revision:int=Field(ge=0)


def service(app,config):
    if getattr(app.state,'auto_covers',None) is None:app.state.auto_covers=AutoCovers(config)
    return app.state.auto_covers


def register(app):
    from typing import Annotated
    from fastapi import Depends
    from shopping_agent.config import AppConfig
    @app.get('/api/projects/{task}/cover-cache')
    def read(task:int,request:Request,config:Annotated[AppConfig,Depends(get_config)]):
        return service(app,config).status(task)
    @app.put('/api/projects/{task}/cover-cache')
    def save(task:int,body:CoverSetting,request:Request,config:Annotated[AppConfig,Depends(get_config)]):
        from shopping_agent.web.app import _same_loopback_origin
        if not _same_loopback_origin(request.headers.get('origin',''),request.url):raise HTTPException(403,'仅允许本机页面修改封面缓存设置')
        return service(app,config).configure(task,body.enabled,body.expected_revision)
