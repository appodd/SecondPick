"""P5 local policy / proposal / pixel preparation; two server gates default off."""
from fastapi import Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from shopping_agent.visual_investigations import VisualInvestigations, ProjectGrant


def service(app):
    p=app.state.project_research
    if getattr(p,'visual_investigations',None) is None:
        p.visual_investigations=VisualInvestigations(p,app.state.vision_settings,
            execution_allowed=lambda: app.state.visual_execution_enabled is True,
            fetch_allowed=lambda: app.state.visual_image_fetch_enabled is True,
            mock_transport=getattr(app.state,'visual_execution_transport',None))
    return p.visual_investigations


class Local(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    confirmed:StrictBool


class PolicyInput(Local):
    expected_revision:int=Field(ge=0)
    grant:ProjectGrant


class SuggestInput(Local):
    listing_ids:list[int]|None=Field(default=None,max_length=3)


def register(app):
    app.state.visual_image_fetch_enabled=False  # Independent of Provider gate and project opt-in.

    def local(request):
        from shopping_agent.web.app import _same_loopback_origin
        if not _same_loopback_origin(request.headers.get('origin',''),request.url):
            raise HTTPException(403,'需要来自本机页面的明确操作')

    @app.get('/api/projects/{task}/visual-investigations')
    def read(task:int,request:Request,listing:int|None=None):
        s=service(request.app)
        return dict(items=s.presentation(task,listing),policy=s.policy(task),
                    image_fetch_enabled=request.app.state.visual_image_fetch_enabled,
                    execution_enabled=request.app.state.visual_execution_enabled,
                    notice='图片获取与模型发送分别授权；待审阅观察不是已确认事实。')

    @app.put('/api/projects/{task}/visual-investigations/policy')
    def save(task:int,body:PolicyInput,request:Request):
        local(request)
        return service(request.app).save_policy(task,body.grant,expected_revision=body.expected_revision,confirmed=body.confirmed)

    @app.post('/api/projects/{task}/visual-investigations/propose')
    def suggest(task:int,body:SuggestInput,request:Request):
        local(request)
        if not body.confirmed: raise ValueError('explicit_local_planning_required')
        return service(request.app).propose(task,body.listing_ids)

    @app.post('/api/projects/{task}/visual-investigations/{ident}/prepare')
    def prepare(task:int,ident:int,body:Local,request:Request):
        local(request)
        if not body.confirmed: raise ValueError('explicit_image_preparation_required')
        return service(request.app).prepare(task,ident)

    @app.post('/api/projects/{task}/visual-investigations/{ident}/execute')
    def execute(task:int,ident:int,body:Local,request:Request):
        local(request)
        if not body.confirmed: raise ValueError('explicit_visual_execution_required')
        return service(request.app).execute(task,ident)
