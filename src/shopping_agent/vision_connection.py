"""Explicit, single-submission connection check; no product evidence or research."""
import base64
import asyncio
import binascii
import json
import struct
import time
import zlib

from shopping_agent.vision import encode, exchange_once, provider_for, redact
from shopping_agent.vision_profiles import ProfileError


def test_image():
    def chunk(kind, data):
        return struct.pack('!I', len(data))+kind+data+struct.pack('!I', binascii.crc32(kind+data)&0xffffffff)
    raw = b''.join(b'\x00'+b'\xff\x00\x00'*8 for _ in range(8))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('!2I5B', 8, 8, 8, 2, 0, 0, 0))+chunk(b'IDAT', zlib.compress(raw))+chunk(b'IEND', b'')


def verification_body(model):
    return dict(model=model, input=[dict(role='user', content=[
        dict(type='input_text', text='Identify the dominant solid color in this test image. Choose red, blue, green, white or black. Return JSON with exactly one field: color.'),
        dict(type='input_image', image_url='data:image/png;base64,'+base64.b64encode(test_image()).decode(), detail='auto')])],
        stream=False, tools=[], tool_choice='none', reasoning=dict(effort='none'), max_output_tokens=128,
        text=dict(format=dict(type='json_schema', name='vision_connection_check', schema={
            'type':'object','additionalProperties':False,'required':['color'],'properties':{'color':{'type':'string','enum':['red','blue','green','white','black']}}})))


async def verify_connection(config, key, *, mock_transport=None):
    from shopping_agent.vision_settings import VisionSettings
    config = VisionSettings(**config)
    provider = provider_for(config.provider)
    if not provider.supports(config.model) or not hasattr(provider, 'build_verification'):
        raise ProfileError('unsupported_model', '此模型尚无图片输入验证适配支持。', 400)
    if mock_transport is not None:
        import httpx
        if not isinstance(mock_transport, httpx.MockTransport):
            raise ValueError('only_mock_transport_may_be_injected')
    result = dict(client_submissions=0)
    started = time.monotonic()
    try:
        timeout = min(config.timeout_seconds, 60)
        response = await asyncio.wait_for(exchange_once(provider.endpoint, encode(provider.build_verification(config.model)), key,
            timeout, result, mock_transport=mock_transport), timeout)
        output = provider.extract(response)
        if output.model != config.model or json.loads(output.text) != {'color':'red'}:
            raise ProfileError('visual_check_failed', '服务未正确完成内置测试图验证，请核对模型图片输入能力。', 400)
        usage = {k:v for k,v in (output.usage.items() if isinstance(output.usage,dict) else []) if k in ('input_tokens','output_tokens','total_tokens') and type(v) is int and 0<=v<10**9}
        return redact(dict(state='verified', request_id=str(result.get('request_id','unavailable'))[:128], model=output.model,
            http_status=result.get('http_status'), usage=usage, elapsed_seconds=round(time.monotonic()-started,3),
            client_submissions=result['client_submissions'], test='built_in_color_image_v1'), key)
    except ProfileError:
        raise
    except Exception:
        code = result.get('http_status')
        if code in (401,403):
            message = '鉴权失败或账户无权使用该模型，请更新密钥或检查服务商权限。'
        elif code == 429:
            message = '服务商限流或额度受限，请检查账户状态后再明确重试。'
        elif code:
            message = '服务未返回有效验证结果，请核对模型或稍后重试。'
        else:
            message = '连接失败或请求超时，请检查网络和服务状态；请求可能已处理，请勿连续重试。'
        raise ProfileError('connection_failed', message, 400) from None
