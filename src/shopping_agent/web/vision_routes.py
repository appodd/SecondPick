"""Legacy local endpoints plus the versioned multi-configuration management routes."""
from fastapi import HTTPException, Request
from shopping_agent.vision_settings import VisionSettings, VisionSettingsStore


def register_vision_routes(app, settings_path):
    store = VisionSettingsStore(settings_path.parent / 'vision')
    app.state.vision_settings = store

    @app.get('/api/vision/settings')
    def read():
        return store.status()

    @app.put('/api/vision/settings')
    def save(settings: VisionSettings):
        if settings.enabled:
            raise HTTPException(409, '请通过多配置管理验证当前模型后启用视觉研究')
        try:
            store.save(settings)
        except ValueError:
            raise HTTPException(409, '请通过多配置管理修改指定模型') from None
        return store.status()

    @app.post('/api/vision/check')
    def check():
        return store.status(checked=True)

    @app.put('/api/vision/key/{provider}')
    async def replace_key(provider: str, request: Request):
        # Read bounded body manually, so framework validation cannot echo a secret.
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 8192:
                raise HTTPException(400, '密钥请求过大')
        try:
            import json
            body = json.loads(data)
            if not isinstance(body, dict) or set(body) != {'key'}:
                raise ValueError
            store.set_key(provider, body['key'])
        except Exception:
            raise HTTPException(400, '无法保存视觉密钥，请检查服务商、格式与安全存储') from None
        return store.status()

    @app.delete('/api/vision/key/{provider}')
    def clear_key(provider: str):
        store.clear_key(provider)
        return store.status()

    from shopping_agent.web.vision_profile_routes import register
    register(app, store)
