"""All pictures, keys and model responses are synthetic; external sockets denied."""
import asyncio
import base64
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import time

import httpx
from PIL import Image
import pytest

from shopping_agent.codex_runtime import CodexRequest, AnswerResult
from shopping_agent.vision import freeze_input, provider_for, TrialApproval, VisionExecutor, validate_result
from shopping_agent.vision_settings import VisionSettings, VisionSettingsStore
from shopping_agent.visual_inputs import freeze, image_refs, validate_observations


@pytest.fixture
def pair(tmp_path):
    request=CodexRequest(task=dict(id=1,original_goal='Synthetic camera',effective_goal='Synthetic camera'),
        messages=(dict(task_id=1,role='user',content='Synthetic evidence only'),),
        candidates=(dict(task_id=1,listing_id=7,data={'title':'Synthetic camera','price':'100'}),),
        evidence=(),runs=(),allowed_listing_ids=frozenset({7}),review_context={'source_namespace':'isolated:test'},
        current_criteria=(dict(criterion_id='visible',description='Visible condition',priority='soft',
                               source_message_ids=[],source_refs=['task_goal']),))
    images=[]
    for media,color in enumerate(('red','blue','green'),1):
        stream=io.BytesIO();Image.new('RGB',(25,20),color).save(stream,format='PNG');data=stream.getvalue()
        p=tmp_path/f'{media}.png';p.write_bytes(data);digest=hashlib.sha256(data).hexdigest()
        images.append(dict(listing_id=7,media_id=media,evidence_id=f'image:7:{media}:{digest}',
            sha256=digest,local_path=str(p),bytes=len(data),width=25,height=20,mime='image/png',
            source_url=f'https://img.alicdn.com/synthetic-{media}.png',source_detail_id=57))
    request=freeze(request,images,123,1)
    args=(request,tmp_path,(1<<60)+123,'isolated:test',1)
    return request,args


def result_for(frozen, *, visual=None):
    request=CodexRequest.model_validate_json(frozen.request_json)
    from shopping_agent.assessment import input_refs
    isvisual=frozen.with_images if visual is None else visual
    ref=next(iter(image_refs(request))) if isvisual else next(iter(input_refs(request)))
    return AnswerResult(type='answer',content='MOCK ONLY: no actual picture interpretation',candidate_ids=[],
        research=dict(criteria=[c.model_dump() for c in request.current_criteria],assessments=[dict(
            listing_id=7,conclusion='conditional',summary='Mock unknown',judgments=[dict(criterion_id='visible',
            status='UNKNOWN',reason='Mock only',source_type='image_observation' if isvisual else 'seller_claim',evidence_refs=[ref])])]))


def envelope(result):
    return dict(id='mock-id',model='deepseek-flash',status='completed',usage={'input_tokens':100,'output_tokens':20},
        output=[dict(type='message',role='assistant',content=[dict(type='output_text',text=result.model_dump_json())])])


def trial(tmp_path, inputs):
    (tmp_path/'isolated-vision-trial.json').write_text('{"production":false}')
    return TrialApproval('mock-approval','deepseek','deepseek-flash',tuple(i.signature for i in inputs),time.time()+300,True,True)


def evaluate(frozen,approval,root,handler,config=None,enabled=True,key=lambda:'dummy-key-only'):
    return asyncio.run(VisionExecutor(execution_enabled=enabled).evaluate(
        config or VisionSettings(enabled=True),frozen,approval,key,root,mock_transport=httpx.MockTransport(handler)))


def test_pair_same_text_and_three_actual_images(pair,tmp_path):
    request,args=pair
    a=freeze_input(*args,with_images=False);b=freeze_input(*args,with_images=True)
    assert a.text==b.text and len(a.images)==0 and len(b.images)==3
    adapter=provider_for('deepseek');pa=adapter.build('deepseek-flash',a,3000);pb=adapter.build('deepseek-flash',b,3000)
    assert pa['instructions']==pb['instructions'] and pa['text']==pb['text']
    assert len(pa['input'][0]['content'])==1 and len(pb['input'][0]['content'])==4
    assert pb['tools']==[] and pb['tool_choice']=='none' and pb['reasoning']=={'effort':'none'}
    assert 'store' not in pb and 'parallel_tool_calls' not in pb
    for part,entry in zip(pb['input'][0]['content'][1:],request.review_context['visual_inputs']['images']):
        assert hashlib.sha256(base64.b64decode(part['image_url'].split(',')[1])).hexdigest()==entry['sha256']
    approval=trial(tmp_path,[a,b]);calls=[]
    def handler(req):
        calls.append(req)
        assert str(req.url)=='https://api.deepseek.com/responses'
        f=a if len(calls)==1 else b
        return httpx.Response(200,json=envelope(result_for(f)),headers={'x-request-id':'mock-request'})
    ar=evaluate(a,approval,tmp_path,handler);br=evaluate(b,approval,tmp_path,handler)
    assert ar['success'] and br['success'] and len(calls)==2
    assert br['cost']=='unavailable' and br['request_id']=='mock-request'
    assert br['raw_output'] and br['raw_response'] and br['parsed']
    assert br['model_delivery_verified'] is False
    with pytest.raises(ValueError):validate_observations(request,result_for(b))
    with pytest.raises(ValueError,match='already_attempted'):evaluate(b,approval,tmp_path,handler)


@pytest.mark.parametrize('model',['deepseek-chat','deepseek-v4-pro','not-real','deepseek-flash-extra'])
def test_unknown_or_text_model_not_declared_visual(pair,model):
    assert not provider_for('deepseek').supports(model)
    with pytest.raises(ValueError):provider_for('deepseek').build(model,freeze_input(*pair[1],with_images=True),3000)


@pytest.mark.parametrize('bad',['hash','path','source','listing','goal','count'])
def test_bad_evidence_denied(pair,bad):
    request,args=pair
    ctx=request.review_context['visual_inputs'];entry=ctx['images'][0]
    if bad=='hash':Path(entry['local_path']).write_bytes(b'X'*entry['bytes'])
    if bad=='path':entry['local_path']='https://img.alicdn.com/never-fetch.png'
    if bad=='source':entry['source_url']='https://127.0.0.1/private'
    if bad=='listing':entry['listing_id']=8
    if bad=='goal':ctx['goal_revision']=2
    if bad=='count':ctx['images'].append(dict(entry))
    with pytest.raises(ValueError):freeze_input(*args,with_images=True)


@pytest.mark.parametrize('kind',['http','timeout','connect','invalid_json','invalid_shape','wrong_hash','wrong_item','no_refs','summary','tool','model_change','incomplete'])
def test_error_material_retained_no_retry_or_second_arm(pair,tmp_path,kind):
    a=freeze_input(*pair[1],with_images=False);b=freeze_input(*pair[1],with_images=True)
    approval=trial(tmp_path,[a,b]);calls=[]
    def handler(req):
        calls.append(1)
        if kind=='http':return httpx.Response(429,json={'error':{'message':'dummy-key-only'}})
        if kind=='timeout':raise httpx.ReadTimeout('dummy-key-only')
        if kind=='connect':raise httpx.ConnectError('dummy-key-only')
        if kind=='invalid_json':return httpx.Response(200,content=b'not JSON')
        r=result_for(a)
        if kind=='wrong_item':r.research.assessments[0].listing_id=99
        if kind=='wrong_hash':r.research.assessments[0].judgments[0].evidence_refs=['image:7:1:'+'0'*64]
        if kind=='no_refs':r.research.assessments[0].judgments[0].source_type='image_observation';r.research.assessments[0].judgments[0].evidence_refs=[]
        if kind=='summary':r.research=None
        value=envelope(r)
        if kind=='invalid_shape':value['output'][0]['content'][0]['text']='{"type":"answer"}'
        if kind=='model_change':value['model']='another-model'
        if kind=='tool':value['output']=[{'type':'function_call'}]
        if kind=='incomplete':value['status']='incomplete'
        return httpx.Response(200,json=value)
    outcome=evaluate(a,approval,tmp_path,handler)
    assert not outcome['success'] and outcome['error'] and len(calls)==1
    records=[json.loads(p.read_text('utf-8')) for p in tmp_path.glob('*.json') if p.name!='isolated-vision-trial.json']
    assert len(records)==1 and not records[0]['success']
    if kind not in ('timeout','connect'):assert records[0]['raw_response']
    if kind in ('invalid_shape','wrong_hash','wrong_item','no_refs','summary'):assert records[0]['raw_output']
    assert all('dummy-key-only' not in p.read_text('utf-8') for p in tmp_path.glob('*.json'))
    with pytest.raises(ValueError,match='baseline_not_successful'):evaluate(b,approval,tmp_path,handler)
    with pytest.raises(ValueError,match='already_attempted'):evaluate(a,approval,tmp_path,handler)
    assert len(calls)==1


def test_default_disabled_and_missing_authorization(pair,tmp_path):
    a=freeze_input(*pair[1],with_images=False);approval=trial(tmp_path,[a])
    no=lambda r:pytest.fail('network must not run')
    with pytest.raises(ValueError,match='disabled'):evaluate(a,approval,tmp_path,no,enabled=False)
    with pytest.raises(ValueError,match='disabled'):evaluate(a,approval,tmp_path,no,config=VisionSettings())
    for bad in (replace(approval,upload_authorized=False),replace(approval,expires_at=0),replace(approval,model='other'),
                replace(approval,max_output_tokens=128)):
        with pytest.raises(ValueError):evaluate(a,bad,tmp_path,no)
    with pytest.raises(ValueError):evaluate(a,approval,tmp_path,no,key=None)


def test_no_images_cannot_claim_visual_observation(pair):
    a=freeze_input(*pair[1],with_images=False)
    with pytest.raises(ValueError):validate_result(a,result_for(a,visual=True).model_dump_json())


def test_settings_secret_update_clear_restart_and_non_secret_json(tmp_path):
    store=VisionSettingsStore(tmp_path/'vision');before=store.status()
    assert before['state']=='disabled' and not before['connection_verified'] and not store.directory.exists()
    store.save(VisionSettings(enabled=True))
    assert store.status()['state']=='disabled'  # Legacy enable is not a real connection verification.
    store.set_key('deepseek','fake-first-key-123')
    store.set_key('deepseek','fake-second-key-456')
    assert store.status()['state']=='disabled' and store.status(checked=True)['local_check']['passed']
    import os
    if os.name=='nt':
        assert VisionSettingsStore(store.directory).credential('deepseek')=='fake-second-key-456'
        data=store.key_path('deepseek').read_bytes()
        assert b'fake-first-key' not in data and b'fake-second-key' not in data
    assert 'key' not in json.loads((store.directory/'vision-model.json').read_text('utf-8'))
    assert 'fake-second-key' not in json.dumps(store.status())
    store.clear_key('deepseek');assert not store.has_key('deepseek') and not store.key_path('deepseek').exists()
    store.save(VisionSettings(enabled=True,model='unknown-model'));assert not store.status()['capability_declared']
    for invalid in (dict(timeout_seconds=301),dict(max_output_tokens=9999),dict(endpoint='https://evil.invalid')):
        with pytest.raises(ValueError):VisionSettings(**invalid)


def test_settings_api_only_local_no_cli_or_runtime(tmp_path,monkeypatch):
    from shopping_agent.web.app import create_app
    from shopping_agent.codex_runtime import CodexRuntime
    monkeypatch.setattr(CodexRuntime,'run',lambda *a,**k:pytest.fail('CLI invoked'))
    app=create_app(tmp_path/'absent.toml',tmp_path/'settings.json')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            response=await c.get('/api/vision/settings');assert response.json()['state']=='disabled'
            response=await c.put('/api/vision/settings',json=VisionSettings(enabled=True).model_dump());assert response.status_code==409
            response=await c.put('/api/vision/settings',json=VisionSettings(enabled=False).model_dump());assert response.status_code==200
            response=await c.put('/api/vision/key/deepseek',json={'key':'fake-api-secret-value'})
            assert response.status_code==200 and 'fake-api-secret' not in response.text
            response=await c.post('/api/vision/check');assert response.json()['connection_verified'] is False
            assert response.json()['local_check']['network_used'] is False
            response=await c.put('/api/vision/key/deepseek',json={'key':{'wrong':'fake-api-secret-value'}})
            assert response.status_code==400 and 'fake-api-secret' not in response.text
            response=await c.delete('/api/vision/key/deepseek');assert not response.json()['key_configured']
            assert (await c.post('/api/vision/run')).status_code in (404,405)
    asyncio.run(scenario())
    assert not list(tmp_path.glob('*.sqlite')) and not (tmp_path/'settings.json').exists()


def test_duplicate_concurrent_requests_latched(pair,tmp_path):
    a=freeze_input(*pair[1],with_images=False);approval=trial(tmp_path,[a]);calls=[]
    async def handler(req):
        calls.append(1);await asyncio.sleep(.02)
        return httpx.Response(200,json=envelope(result_for(a)))
    async def both():
        executor=VisionExecutor(execution_enabled=True)
        return await asyncio.gather(*[executor.evaluate(VisionSettings(enabled=True),a,approval,
            lambda:'fake-key-only',tmp_path,mock_transport=httpx.MockTransport(handler)) for _ in range(2)],return_exceptions=True)
    outcomes=asyncio.run(both())
    assert len(calls)==1 and sum(isinstance(x,ValueError) for x in outcomes)==1
