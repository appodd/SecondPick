from fastapi import HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field,StrictInt,field_validator
from shopping_agent.project_chat import ProjectChat

class ChatInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    message:str=Field(min_length=1,max_length=6000)
    ids:list[StrictInt]=Field(default_factory=list,max_length=20)
    request_key:str=Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    expected_goal_revision:int=Field(ge=1)
    study_id:StrictInt|None=Field(default=None,gt=0)
    report_id:StrictInt|None=Field(default=None,gt=0)
    @field_validator('message')
    @classmethod
    def nonblank(cls,value):
        if not value.strip():raise ValueError('请输入问题')
        return value.strip()

def register(app):
    def service(request):return ProjectChat(request.app.state.project_research,request.app.state.codex_runtime)
    @app.get('/api/projects/{task_id}/agent-chat')
    def history(task_id:int,request:Request):return service(request).history(task_id)
    @app.post('/api/projects/{task_id}/agent-chat')
    def send(task_id:int,body:ChatInput,request:Request):
        try:return service(request).send(task_id,**body.model_dump())
        except ValueError as exc:raise HTTPException(502,str(exc)) from exc
