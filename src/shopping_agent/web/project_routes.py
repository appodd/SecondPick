"""Verified project endpoints; legacy /api/tasks contracts remain unchanged."""
import json
from typing import Literal, Annotated

from fastapi import FastAPI, Request, HTTPException, Query, Depends
from shopping_agent.config import AppConfig
from shopping_agent.web.dependencies import get_config
from pydantic import BaseModel, ConfigDict, Field, field_validator
from shopping_agent.codex_runtime import AnswerResult


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class GoalInput(Input):
    goal: str = Field(min_length=1, max_length=8000)

    @field_validator('goal')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('目标不能为空')
        return value.strip()


class ProjectInput(GoalInput):
    title: str = Field(min_length=1, max_length=60)
    budget: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    hard: list[str] = Field(default_factory=list, max_length=30)
    soft: list[str] = Field(default_factory=list, max_length=30)
    minimum: int = Field(default=20, ge=1, le=200)
    auto_research: bool = False
    auto_cover_cache: bool = True
    request_key: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator('title')
    @classmethod
    def title_nonblank(cls, value):
        if not value.strip():
            raise ValueError('项目名称不能为空')
        return value.strip()


class StudyInput(Input):
    ids: list[int] | None = Field(default=None, max_length=20)
    question: str | None = Field(default=None, min_length=1, max_length=8000)
    request_key: str = Field(min_length=8, max_length=64)
    expected_goal_revision: int | None = Field(default=None, ge=1)


class InvestigationPlanInput(Input):
    ids: list[int] | None = Field(default=None, max_length=3)

    @field_validator('ids', mode='before')
    @classmethod
    def valid_ids(cls, value):
        if value is not None and (not isinstance(value,list) or not value or any(type(i) is not int or i<=0 for i in value) or len(set(value))!=len(value)):
            raise ValueError('请选择不同的已有商品 ID')
        return value


class InvestigationConfirmation(Input):
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError('需要明确确认本次具体详情访问')
        return value


class GoalUpdate(GoalInput):
    budget: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    hard: list[str] = Field(default_factory=list, max_length=30)
    soft: list[str] = Field(default_factory=list, max_length=30)
    expected_revision: int = Field(ge=1)
    request_key: str = Field(min_length=8, max_length=64)
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError('必须明确确认')
        return value

    @field_validator('hard','soft')
    @classmethod
    def conditions(cls, values):
        if any(not value.strip() or len(value)>1000 for value in values):
            raise ValueError('条件须为非空文本，每项最多1000字')
        return list(dict.fromkeys(value.strip() for value in values))


class ReadInput(Input):
    report_id: int = Field(gt=0)


class GoalDraftContext(GoalInput):
    budget: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    hard: list[str] = Field(default_factory=list, max_length=30)
    soft: list[str] = Field(default_factory=list, max_length=30)

    @field_validator('hard', 'soft')
    @classmethod
    def conditions(cls, values):
        if any(not value.strip() or len(value)>1000 for value in values):
            raise ValueError('条件须为非空文本，每项最多1000字')
        return list(dict.fromkeys(value.strip() for value in values))


class GoalDraftInput(GoalInput):
    current: GoalDraftContext | None = None


class MonitorGoalInput(GoalInput):
    pass


class WindowInput(Input):
    name: str = Field(min_length=1, max_length=120)
    keyword: str = Field(min_length=1, max_length=120)
    mode: Literal['once','timed','ongoing']
    duration_seconds: int = Field(default=1800, ge=60, le=86400)
    interval_seconds: int = Field(default=1800, ge=60, le=86400)
    max_pages: int = Field(default=3, ge=1, le=50)
    max_items: int = Field(default=50, ge=1, le=1000)
    collect_seller_profiles: bool = False
    request_key: str | None = Field(default=None, min_length=8, max_length=64)
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError('必须明确确认')
        return value


class WindowEdit(WindowInput):
    expected_revision: int = Field(ge=0)


def register_project_routes(app: FastAPI):
    def service(request):
        return request.app.state.project_research

    def investigations(request):
        from shopping_agent.project_investigations import ProjectInvestigations
        return ProjectInvestigations(service(request))

    @app.get('/api/projects/{task_id}/investigations')
    def investigation_list(task_id: int, request: Request, listing: int | None = Query(default=None,ge=1)):
        return investigations(request).list(task_id,listing=listing)

    @app.post('/api/projects/{task_id}/investigations/plan')
    def investigation_plan(task_id: int, body: InvestigationPlanInput, request: Request):
        return investigations(request).propose(task_id, body.ids)

    @app.post('/api/projects/{task_id}/investigations/{ident}/approve')
    def investigation_approve(task_id: int, ident: int, body: InvestigationConfirmation, request: Request):
        return investigations(request).decide(task_id,ident,'approve')

    @app.post('/api/projects/{task_id}/investigations/{ident}/cancel')
    def investigation_cancel(task_id: int, ident: int, request: Request):
        return investigations(request).decide(task_id,ident,'cancel')

    @app.post('/api/projects/{task_id}/investigations/{ident}/execute')
    def investigation_execute(task_id: int, ident: int, body: InvestigationConfirmation, request: Request,
                              config: Annotated[AppConfig, Depends(get_config)]):
        from shopping_agent.browser_jobs import BrowserJobError, BrowserJobStore
        manager = investigations(request)
        item = next((i for i in manager.list(task_id)['items'] if i['id']==ident), None)
        if item is None:
            raise BrowserJobError('not_found','调查不属于此项目。',404)
        if not item['request_id']:
            raise BrowserJobError('unsupported_action','此事项不能通过当前详情采集执行。')
        store = BrowserJobStore(config)
        if not config.allow_login or 'xianyu' not in config.platforms:
            raise BrowserJobError('collection_disabled','当前未启用闲鱼浏览器采集。')
        # A duplicate HTTP request returns its existing job, including terminal
        # failures, without restarting or broadening the approved scope.
        previous = store.latest_for_request(task_id,item['request_id'])
        if previous:
            return manager.list(task_id)
        if store.status()['auth_status'] != 'verified':
            raise BrowserJobError('login_required','请先在设置中验证闲鱼登录；本次未创建任务。')
        try:
            job = store.create_collection(task_id,item['request_id'],'',1,investigation_id=ident)
        except BrowserJobError as exc:
            if exc.code == 'browser_busy':
                raise BrowserJobError('browser_busy','采集资源正忙，本次未创建调查任务；请等待现有任务结束后再次确认执行，不会停止监控。') from exc
            raise
        request.app.state.browser_coordinator.start(job['id'], config=config)
        return manager.list(task_id)

    def engine_ready(request):
        cfg = request.app.state.monitor_store.config
        if not cfg.monitor_engine.enabled or 'xianyu' not in cfg.platforms:
            raise HTTPException(409, '请先在设置中配置并启用采集引擎。')
        readiness = getattr(request.app.state, 'monitor_environment_result', None)
        if readiness is not None and not readiness['ready']:
            raise HTTPException(409, '采集环境检查未通过。')
        if cfg.monitor_engine.state_file is None and request.app.state.browser_store.status()['auth_status'] != 'verified':
            raise HTTPException(409, '请先登录闲鱼并验证；本次未启动采集。')

    @app.post('/api/project-goal-drafts')
    def goal_draft(body: GoalDraftInput, request: Request):
        # No project or monitor is created by a draft. Reuse the configured runtime.
        runtime = request.app.state.codex_runtime
        prompt = ('解析以下选购需求，只返回 answer，content 必须是纯 JSON 对象，字段 title,goal,budget(数字或null),hard(字符串数组),soft(字符串数组)。'
                  '用户的优先/最好是软偏好，不升级为硬约束；未明确地区时不设置地区偏好，不继承系统默认城市。'
                  '上海优先只放入soft，只考虑上海自提放入hard。不要凭默认城市新增地区，不执行采集。需求：'+body.goal)
        if body.current is not None:
            prompt = ('根据当前选购条件和本次修改意图，生成完整可编辑的选购目标草案。只返回 answer，content 为纯 JSON，'
                      '字段 title,goal,budget(数字或null),hard(字符串数组),soft(字符串数组)。'
                      'goal 必须是调整后的完整自然语言选购目标，不是修改指令，不要包含提示词、JSON、旧新两套互相矛盾的要求。'
                      '本次明确修改优先，替换旧条件；未要求改变的预算、必须条件和偏好保留，不擅自增加条件。'
                      '预算未设置保持null；硬盘存储与运行内存分开，存储256GB不能解释成内存256GB。'
                      '优先/最好属于soft，不升级为硬约束；地区仅依据用户现有条件和明确修改，不继承系统城市。'
                      '不保存、不研究、不采集、不修改监控。\n当前选购条件（JSON）：'+body.current.model_dump_json()+
                      '\n本次修改意图（原文）：'+body.goal)
        query = runtime.build_request(task=dict(id=1, original_goal=body.goal, effective_goal=body.goal),
            messages=[dict(task_id=1,role='user',content=prompt)], candidates=[], evidence=[], runs=[], allowed_listing_ids=set())
        try:
            result = runtime.run(query, run_id=(1 << 61) + int.from_bytes(__import__('os').urandom(6),'big'), stage_callback=lambda stage: None)
            if not isinstance(result, AnswerResult):
                raise ValueError('模型未返回需求草案')
            from shopping_agent.region_preference import normalize_region_draft
            raw = json.loads(result.content)
            if body.current is None:
                payload = normalize_region_draft(raw, body.goal)
            else:
                from shopping_agent.region_preference import region_preference
                import re
                if not isinstance(raw,dict) or not {'title','goal','budget','hard','soft'}.issubset(raw):
                    raise ValueError('修改草案缺少完整目标、预算或条件字段，请重试或手动修改')
                generated_goal = GoalInput.model_validate({'goal':raw.get('goal')}).goal
                if generated_goal == prompt or any(marker in generated_goal for marker in ('当前选购条件（JSON）', '本次修改意图（原文）')):
                    raise ValueError('模型返回了整理指令而非完整选购目标，请重试或手动修改')
                explicit_region = region_preference(body.goal)['mode'] != 'none' or re.search(r'取消.*(?:地区|自提)|不限地区|不限制地区|不再.*(?:地区|自提)',body.goal)
                region_source = body.goal if explicit_region else '\n'.join([body.current.goal,*body.current.hard,*body.current.soft])
                allowed_region = region_preference(region_source)
                generated_region = region_preference(generated_goal)
                if generated_region['city'] and (generated_region['city'],generated_region['mode']) != (allowed_region['city'],allowed_region['mode']):
                    raise ValueError('目标描述改变了未经确认的地区条件，请重试或手动核对')
                payload = normalize_region_draft(raw, region_source)
                payload['goal'] = generated_goal
            draft = ProjectInput.model_validate(payload)
            return draft.model_dump(exclude={'request_key'})
        except Exception as exc:
            raise HTTPException(502, 'AI 解析失败，可保留原文并手动编辑：'+str(exc)[:300]) from exc

    @app.post('/api/projects', status_code=201)
    def create_project(body: ProjectInput, request: Request):
        return service(request).create(**body.model_dump())

    @app.patch('/api/projects/{task_id}/goal')
    def update_goal(task_id: int, body: GoalUpdate, request: Request):
        from shopping_agent.project_goals import GoalConflict
        try:
            return service(request).save_goal(task_id, **body.model_dump())
        except GoalConflict as exc:
            raise HTTPException(409,str(exc)) from exc

    @app.get('/api/projects/{task_id}/reports')
    def reports(task_id: int, request: Request, before_id: int | None = Query(default=None,gt=0), limit: int = Query(default=20,ge=1,le=50)):
        return service(request).report_history(task_id,before_id,limit)

    @app.post('/api/projects/{task_id}/monitor-drafts')
    def monitor_draft(task_id: int, body: MonitorGoalInput, request: Request):
        store = service(request)
        runtime = request.app.state.codex_runtime
        prompt = ('将用户要求转换为监控配置草案，只返回 answer；content 是纯 JSON 对象，字段 name,keyword,mode(once/timed/ongoing),'
            'duration_seconds(60到86400),interval_seconds(至少60),max_pages(1到50),max_items(1到1000),collect_seller_profiles(false)。'
            '30分钟表示限时窗口，不是间隔；间隔未指定用1800秒；默认3页50件。关键词只包含明确搜索目标，不把最好/优先等偏好变硬过滤。'
            '不执行采集，不改变现有监控。用户要求：'+body.goal)
        query = store._request(task_id, [], prompt)
        try:
            result = runtime.run(query, run_id=(1 << 61)+int.from_bytes(__import__('os').urandom(6),'big'), stage_callback=lambda stage: None)
            if not isinstance(result, AnswerResult):
                raise ValueError('模型未返回草案')
            draft = WindowInput.model_validate({**json.loads(result.content), 'confirmed':True})
            return draft.model_dump(exclude={'confirmed','request_key'})
        except Exception as exc:
            raise HTTPException(502,'监控草案解析失败，请手动配置：'+str(exc)[:300]) from exc

    @app.get('/api/projects/{task_id}/overview')
    def overview(task_id: int, request: Request):
        return service(request).overview(task_id)

    @app.post('/api/projects/{task_id}/studies', status_code=202)
    def study(task_id: int, body: StudyInput, request: Request):
        from shopping_agent.project_goals import GoalConflict
        try:
            return {'id':service(request).enqueue(task_id, **body.model_dump())}
        except GoalConflict as exc:
            raise HTTPException(409,str(exc)) from exc

    @app.post('/api/projects/{task_id}/studies/{study_id}/retry', status_code=202)
    def retry(task_id: int, study_id: int, request: Request):
        return service(request).retry(task_id, study_id)

    @app.put('/api/projects/{task_id}/favorites/{listing_id}')
    def favorite(task_id: int, listing_id: int, request: Request):
        return service(request).favorite(task_id, listing_id, True)

    @app.get('/api/projects/{task_id}/listings/{listing_id}/seller')
    def seller(task_id: int, listing_id: int, request: Request):
        return service(request).seller(task_id,listing_id)

    @app.post('/api/projects/{task_id}/listings/{listing_id}/seller/studies',status_code=202)
    def study_seller(task_id: int, listing_id: int, request: Request):
        return service(request).seller(task_id,listing_id,study=True)

    @app.delete('/api/projects/{task_id}/favorites/{listing_id}')
    def unfavorite(task_id: int, listing_id: int, request: Request):
        return service(request).favorite(task_id, listing_id, False)

    @app.post('/api/projects/{task_id}/read')
    def read(task_id: int, body: ReadInput, request: Request):
        return service(request).mark_read(task_id, body.report_id)

    @app.post('/api/projects/{task_id}/research/{action}')
    def control(task_id: int, action: Literal['pause','resume','complete_keep','complete_pause'], request: Request):
        return service(request).control(task_id, action)

    @app.get('/api/projects/{task_id}/goal/history')
    def goal_history(task_id: int, request: Request):
        return service(request).goal_history(task_id)

    @app.get('/api/projects/{task_id}/monitors')
    def monitors(task_id: int, request: Request):
        return service(request).windows(task_id)

    @app.post('/api/projects/{task_id}/monitors', status_code=202)
    def create_monitor(task_id: int, body: WindowInput, request: Request):
        engine_ready(request)
        return service(request).create_window(task_id,body.name,body.mode,body.duration_seconds,
            dict(keyword=body.keyword,interval_seconds=body.interval_seconds,max_pages=body.max_pages,max_items=body.max_items,collect_seller_profiles=body.collect_seller_profiles),body.request_key)

    @app.post('/api/projects/{task_id}/monitors/{monitor_id}/runs', status_code=202)
    def rerun(task_id: int, monitor_id: int, request: Request):
        engine_ready(request)
        return service(request).rerun_window(task_id,monitor_id)

    @app.patch('/api/projects/{task_id}/monitors/{monitor_id}')
    def edit_monitor(task_id: int, monitor_id: int, body: WindowEdit, request: Request):
        return service(request).edit_window(task_id,monitor_id,body.model_dump(exclude={'confirmed','request_key','expected_revision'}),body.expected_revision)
