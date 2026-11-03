"""Bounded metadata/key inputs; explicit connection verification only."""
import json
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from shopping_agent.vision_profiles import ProfileError
from shopping_agent.vision_connection import verify_connection


def register(app, store):
    profiles = store.profiles
    app.state.vision_validation_transport = None
    app.state.vision_validation_disabled = False

    async def body(request, allowed):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 8192:
                raise HTTPException(400, '配置请求过大')
        try:
            value = json.loads(data)
            if not isinstance(value, dict) or set(value)-set(allowed):
                raise ValueError
            if type(value.get('expected_revision')) is not int:
                raise ValueError
            return value
        except Exception:
            raise HTTPException(400, '配置请求格式不正确，请刷新后重试') from None

    def consent(data):
        if app.state.vision_validation_disabled:
            raise HTTPException(403, '隔离预览未开放外部连接验证。配置可保存，尚未验证；不会发起模型请求。')
        if data.get('verification_confirmed') is not True:
            raise HTTPException(400, '请明确确认发送内置测试图进行连接验证，可能产生费用')

    async def validator(config, key):
        return await verify_connection(config, key, mock_transport=app.state.vision_validation_transport)

    async def execute(operation):
        try:
            return await operation
        except ProfileError as exc:
            return JSONResponse(status_code=exc.status, content={'error':dict(code=exc.code, message=exc.message)})
        except Exception:
            return JSONResponse(status_code=400, content={'error':dict(code='operation_failed', message='操作未完成，请刷新核对；不会自动重试。')})

    @app.get('/api/vision/profiles')
    def read():
        return profiles.status()

    async def upsert(request, ident=None):
        data = await body(request, {'expected_revision','request_key','config','key','verification_confirmed'})
        config = data.get('config')
        if not isinstance(config, dict) or set(config) != {'provider','model','timeout_seconds','max_output_tokens'}:
            raise HTTPException(400, '模型参数不完整')
        if ident is not None and profiles.effective().enabled and profiles.status()['current_id'] == ident:
            existing = profiles.find(profiles.document(), ident)
            if existing['config'] != config or data.get('key'):
                consent(data)
        return await execute(profiles.upsert(config, data.get('key'), data['expected_revision'], data.get('request_key'), validator, ident))

    @app.post('/api/vision/profiles')
    async def create(request: Request):
        return await upsert(request)

    @app.patch('/api/vision/profiles/{ident}')
    async def edit(ident: str, request: Request):
        return await upsert(request, ident)

    @app.post('/api/vision/profiles/{ident}/verify')
    async def verify(ident: str, request: Request):
        data = await body(request, {'expected_revision','request_key','verification_confirmed'})
        consent(data)
        return await execute(profiles.action('verify', ident, data['expected_revision'], data.get('request_key'), validator))

    @app.post('/api/vision/profiles/{ident}/select')
    async def select(ident: str, request: Request):
        data = await body(request, {'expected_revision','request_key','verification_confirmed'})
        if profiles.effective().enabled:
            consent(data)
        return await execute(profiles.action('select', ident, data['expected_revision'], data.get('request_key'), validator))

    @app.put('/api/vision/feature')
    async def feature(request: Request):
        data = await body(request, {'expected_revision','request_key','enabled','verification_confirmed'})
        if type(data.get('enabled')) is not bool:
            raise HTTPException(400, '请选择明确的功能状态')
        if data['enabled']:
            consent(data)
            current = profiles.status()['current_id']
            if not current:
                raise HTTPException(400, '请先添加配置并选择当前模型')
            return await execute(profiles.action('enable', current, data['expected_revision'], data.get('request_key'), validator))
        try:
            return profiles.disable(data['expected_revision'])
        except ProfileError as exc:
            return JSONResponse(status_code=exc.status, content={'error':dict(code=exc.code, message=exc.message)})

    @app.delete('/api/vision/profiles/{ident}')
    async def delete(ident: str, request: Request):
        data = await body(request, {'expected_revision','request_key','confirmed'})
        try:
            return profiles.delete(ident, data['expected_revision'], data.get('request_key'), data.get('confirmed'))
        except ProfileError as exc:
            return JSONResponse(status_code=exc.status, content={'error':dict(code=exc.code, message=exc.message)})
