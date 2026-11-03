import asyncio
import copy
import json
import socket
import uuid

import httpx
import pytest
from fastapi import FastAPI
from shopping_agent.vision_settings import VisionSettings, VisionSettingsStore
from shopping_agent.vision_profiles import ProfileError
from shopping_agent.vision_connection import verify_connection
from shopping_agent.web.vision_profile_routes import register

CFG = dict(provider='deepseek', model='deepseek-flash', timeout_seconds=300, max_output_tokens=3000)
KEY_A, KEY_B = 'SYNTHETIC-KEY-A', 'SYNTHETIC-KEY-B'

@pytest.fixture
def store(tmp_path, monkeypatch):
    original_connect = socket.socket.connect
    def deny(sock, address):
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return original_connect(sock, address)  # asyncio's local self-pipe on Windows.
        raise AssertionError('No external network allowed')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    # Exercise persistence without using the OS credential facility or real keys.
    from shopping_agent.browser import auth_state
    monkeypatch.setattr(auth_state, '_protect', lambda data, decrypt=False: data[5:] if decrypt else b'FAKE:'+data)
    return VisionSettingsStore(tmp_path/'vision')

def run(coro): return asyncio.run(coro)
def nonce(): return uuid.uuid4().hex
async def good(config, key): return dict(state='verified', client_submissions=1, model=config['model'])
async def bad(config, key): raise ProfileError('connection_failed', 'Connection refused', 400)
def add(store, key=KEY_A, config=None):
    return run(store.profiles.upsert(config or CFG, key, store.profiles.status()['revision'], nonce(), good))
def act(store, kind, ident, validator=good):
    return run(store.profiles.action(kind, ident, store.profiles.status()['revision'], nonce(), validator))
def response(color='red', model='deepseek-flash'):
    return dict(status='completed', model=model, id='mock-response', usage=dict(input_tokens=12, output_tokens=4),
        output=[dict(type='message', role='assistant',content=[dict(type='output_text',text=json.dumps({'color':color}))])])

def test_legacy_read_import_does_not_decrypt_or_rewrite(store, monkeypatch):
    store.save(VisionSettings(**CFG, enabled=True));store.set_key('deepseek', KEY_A)
    paths=list(store.directory.iterdir());before={p.name:p.read_bytes() for p in paths}
    monkeypatch.setattr(store, '_legacy_credential', lambda p: pytest.fail('metadata read decrypted key'))
    status=store.profiles.status()
    assert status['current_id']=='legacy-default' and len(status['profiles'])==1
    assert status['legacy_requires_verification'] and not status['enabled']
    assert before=={p.name:p.read_bytes() for p in store.directory.iterdir()}

def test_same_provider_profiles_preserve_blank_keys_and_reopen(store):
    first=add(store);a=first['current_id'];second=add(store,KEY_B);b=second['profiles'][1]['id']
    assert a!=b and not second['enabled'] and sum(p['current'] for p in second['profiles'])==1
    run(store.profiles.upsert(dict(CFG, timeout_seconds=120),'',second['revision'],nonce(),good,a))
    assert store.credential('deepseek')==KEY_A
    act(store,'select',b);assert store.credential('deepseek')==KEY_B
    assert not store.read().enabled
    if store.profiles.status()['storage']=='windows_dpapi':
        reopened=VisionSettingsStore(store.directory)
        assert reopened.credential('deepseek')==KEY_B
    text=store.profiles.path.read_text('utf-8')
    assert KEY_A not in text and KEY_B not in text and 'key_ref' not in json.dumps(store.profiles.status())

def test_add_requires_key_and_invalid_models_never_verify(store):
    with pytest.raises(ProfileError):add(store,'')
    result=add(store,config=dict(CFG,model='text-only'))
    async def never(*a):pytest.fail('unsupported model contacted provider')
    with pytest.raises(ProfileError):act(store,'enable',result['current_id'],never)
    assert not store.read().enabled

def test_enable_verify_disable_and_reenable_always_verifies(store):
    a=add(store)['current_id'];calls=[]
    async def count(config,key):calls.append(key);return await good(config,key)
    act(store,'verify',a,count);assert not store.read().enabled
    act(store,'enable',a,count);assert store.read().enabled
    store.profiles.disable(store.profiles.status()['revision'])
    assert store.profiles.status()['profiles'] and not store.read().enabled
    act(store,'enable',a,count);assert calls==[KEY_A]*3

def test_failed_enable_current_verify_and_switch_preserve_correct_state(store):
    a=add(store)['current_id'];b=add(store,KEY_B)['profiles'][1]['id']
    with pytest.raises(ProfileError):act(store,'enable',a,bad)
    assert not store.read().enabled
    act(store,'enable',a)
    with pytest.raises(ProfileError):act(store,'select',b,bad)
    assert store.read().enabled and store.profiles.status()['current_id']==a
    act(store,'select',b);assert store.read().enabled and store.credential('deepseek')==KEY_B
    with pytest.raises(ProfileError):act(store,'verify',b,bad)
    assert not store.read().enabled

def test_active_edit_is_transactional_and_rotates_identity(store):
    a=add(store)['current_id'];act(store,'enable',a);original=store.read();files=set(store.directory.iterdir())
    with pytest.raises(ProfileError):run(store.profiles.upsert(dict(CFG,timeout_seconds=100), KEY_B, store.profiles.status()['revision'],nonce(),bad,a))
    assert store.read()==original and store.credential('deepseek')==KEY_A
    assert set(store.directory.iterdir())==files
    run(store.profiles.upsert(dict(CFG,timeout_seconds=100), KEY_B,store.profiles.status()['revision'],nonce(),good,a))
    assert store.read().enabled and store.read().profile_revision>original.profile_revision
    with pytest.raises(ProfileError):store.credential('deepseek',expected=original)

def test_unrelated_profile_edit_does_not_invalidate_active_identity(store):
    a=add(store)['current_id'];b=add(store,KEY_B)['profiles'][1]['id'];act(store,'enable',a);before=store.read()
    run(store.profiles.upsert(dict(CFG,timeout_seconds=75),None,store.profiles.status()['revision'],nonce(),good,b))
    assert store.read()==before and store.credential('deepseek',expected=before)==KEY_A

def test_duplicate_request_stale_revision_and_current_deletion_protected(store):
    a=add(store)['current_id'];key=nonce();rev=store.profiles.status()['revision']
    run(store.profiles.action('verify',a,rev,key,good))
    with pytest.raises(ProfileError):run(store.profiles.action('verify',a,store.profiles.status()['revision'],key,good))
    with pytest.raises(ProfileError):run(store.profiles.action('verify',a,rev,nonce(),good))
    act(store,'enable',a)
    with pytest.raises(ProfileError):store.profiles.delete(a,store.profiles.status()['revision'],nonce(),True)
    assert store.read().enabled
    store.profiles.disable(store.profiles.status()['revision'])
    with pytest.raises(ProfileError):store.profiles.delete(a,store.profiles.status()['revision'],nonce(),False)
    result=store.profiles.delete(a,store.profiles.status()['revision'],nonce(),True)
    assert not result['profiles'] and result['current_id'] is None and not result['enabled']

def test_disable_cancels_inflight_enable_without_replaying(store):
    a=add(store)['current_id']
    async def sequence():
        started=asyncio.Event();finish=asyncio.Event();calls=[]
        async def wait(config,key):calls.append(key);started.set();await finish.wait();return await good(config,key)
        task=asyncio.create_task(store.profiles.action('enable',a,store.profiles.status()['revision'],nonce(),wait))
        await started.wait()
        with pytest.raises(ProfileError):await store.profiles.action('verify',a,store.profiles.status()['revision'],nonce(),good)
        store.profiles.disable(store.profiles.status()['revision']);finish.set()
        with pytest.raises(ProfileError):await task
        assert calls==[KEY_A] and not store.read().enabled
    run(sequence())

@pytest.mark.parametrize('mode',['success','auth','timeout','bad-color','wrong-model','invalid-json'])
def test_connection_uses_one_builtin_image_and_sanitizes_errors(store, mode):
    calls=[]
    def handler(req):
        calls.append(req);body=json.loads(req.content)
        assert req.url==httpx.URL('https://api.deepseek.com/responses')
        assert body['max_output_tokens']==128 and body['tools']==[]
        images=[p for p in body['input'][0]['content'] if p['type']=='input_image']
        assert len(images)==1 and images[0]['image_url'].startswith('data:image/png;base64,')
        if mode=='timeout':raise httpx.ReadTimeout(KEY_A)
        if mode=='auth':return httpx.Response(401,text=KEY_A)
        if mode=='invalid-json':return httpx.Response(200,text=KEY_A)
        return httpx.Response(200,json=response(color='blue' if mode=='bad-color' else 'red',model='other' if mode=='wrong-model' else 'deepseek-flash'))
    coro=verify_connection(CFG,KEY_A,mock_transport=httpx.MockTransport(handler))
    if mode=='success':
        value=run(coro);assert value['state']=='verified' and value['usage']['input_tokens']==12
        assert 'raw_response' not in value and KEY_A not in json.dumps(value)
    else:
        with pytest.raises(ProfileError) as exc:run(coro)
        assert KEY_A not in str(exc.value)
    assert len(calls)==1

def test_routes_real_asgi_save_switch_verify_and_consent(store, monkeypatch):
    app=FastAPI();register(app,store);calls=[]
    def handler(req):calls.append(req);return httpx.Response(200,json=response())
    app.state.vision_validation_transport=httpx.MockTransport(handler)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            async def send(path,method='POST',**kw):
                rev=(await client.get('/api/vision/profiles')).json()['revision']
                return await client.request(method,path,json=dict(expected_revision=rev,request_key=nonce(),**kw))
            first=await send('/api/vision/profiles',config=CFG,key=KEY_A);assert first.status_code==200
            a=first.json()['current_id']
            second=await send('/api/vision/profiles',config=dict(CFG,timeout_seconds=60),key=KEY_B);assert second.status_code==200
            b=second.json()['profiles'][1]['id']
            refused=await send('/api/vision/feature',method='PUT',enabled=True)
            assert refused.status_code==400 and calls==[]
            enabled=await send('/api/vision/feature',method='PUT',enabled=True,verification_confirmed=True)
            assert enabled.json()['enabled'] and len(calls)==1
            no_consent=await send(f'/api/vision/profiles/{b}/select');assert no_consent.status_code==400 and len(calls)==1
            switched=await send(f'/api/vision/profiles/{b}/select',verification_confirmed=True)
            assert switched.json()['current_id']==b and len(calls)==2
            edited=await send(f'/api/vision/profiles/{b}',method='PATCH',config=dict(CFG,timeout_seconds=45),key='',verification_confirmed=True)
            assert edited.json()['enabled'] and len(calls)==3
            assert calls[-1].headers['authorization']=='Bearer '+KEY_B
            disabled=await send('/api/vision/feature',method='PUT',enabled=False)
            assert not disabled.json()['enabled'] and len(disabled.json()['profiles'])==2
            read=await client.get('/api/vision/profiles');assert KEY_A not in read.text and KEY_B not in read.text
    run(scenario())

def test_legacy_key_survives_catalog_creation_and_selection(store):
    store.save(VisionSettings(**CFG));store.set_key('deepseek',KEY_A)
    cipher=store.key_path('deepseek').read_bytes() if store.key_path('deepseek').exists() else None
    second=add(store,KEY_B)
    assert second['current_id']=='legacy-default' and store.credential('deepseek')==KEY_A
    act(store,'enable','legacy-default')
    assert store.read().enabled and store.status()['connection_verified']
    if cipher is not None:assert store.key_path('deepseek').read_bytes()==cipher

def test_restarted_catalog_never_replays_reserved_request(store):
    a=add(store)['current_id'];key=nonce()
    base,token=store.profiles.begin(store.profiles.status()['revision'],key,'verify',a)
    reopened=VisionSettingsStore(store.directory)
    assert reopened.profiles.status()['operation']['state']=='interrupted'
    with pytest.raises(ProfileError):run(reopened.profiles.action('verify',a,base['revision'],key,good))

def test_edit_disabled_invalidates_only_edited_verification(store):
    a=add(store)['current_id'];b=add(store,KEY_B)['profiles'][1]['id']
    act(store,'verify',a);act(store,'verify',b)
    state=run(store.profiles.upsert(dict(CFG,timeout_seconds=90),None,store.profiles.status()['revision'],nonce(),good,a))
    assert state['profiles'][0]['verification']['state']=='unverified'
    assert state['profiles'][1]['verification']['state']=='verified' and not state['enabled']

def test_preview_denial_occurs_before_credential_supply(store, monkeypatch):
    a=add(store)['current_id'];app=FastAPI();register(app,store);app.state.vision_validation_disabled=True
    monkeypatch.setattr(store.profiles,'secret',lambda p:pytest.fail('preview decrypted credential'))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            result=await client.post(f'/api/vision/profiles/{a}/verify',json=dict(expected_revision=store.profiles.status()['revision'],request_key=nonce(),verification_confirmed=True))
            assert result.status_code==403
    run(scenario())
