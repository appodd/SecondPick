"""Synthetic image bytes and mock visual HTTP. No real network or CLI."""
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import io
import json
import multiprocessing
from pathlib import Path
import threading
import time
import httpx
from PIL import Image
import pytest
from test_project_research import research,ingest
from shopping_agent.db import add_media_asset,initialize
from shopping_agent.conversation_service import ConversationService
from shopping_agent.conversation_store import ActionRequestInput
from shopping_agent.image_safety import ImageLimits,ImageSafetyError,fetch_image,public_addresses,bounded_worker
from shopping_agent.image_evidence import save_approved_image,manifest_entry,image_status
from shopping_agent.visual_inputs import freeze,verified_bytes,validate_observations
from shopping_agent.codex_runtime import CodexRequest,AnswerResult
from shopping_agent.project_visual import ProjectVisualExecutor,VisualApproval
from shopping_agent.vision_settings import VisionSettings


def png(color='red',size=(32,32)):
    data=io.BytesIO();Image.new('RGB',size,color).save(data,format='PNG');return data.getvalue()


@pytest.fixture
def setup(research,tmp_path):
    p=research;p.config=p.config.model_copy(update=dict(media_dir=tmp_path/'media',browser_profile_dir=tmp_path/'profile'))
    listing=ingest(p,title='Synthetic camera model, saved condition',price='300')
    with p.source_db() as conn:media=add_media_asset(conn,listing,'product_image_url','https://img.alicdn.com/synthetic.png','')
    return p,listing,media


@pytest.fixture
def visual(setup):
    """Already prepared local pixels plus an explicit, scoped upload approval.

    The transport and credential supplier are test doubles; enqueue must call
    neither. Execution exercises the production visual executor and parser.
    """
    p,listing,media=setup
    data=png();path=p.config.media_dir/'synthetic.png'
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    with p.source_db() as conn:
        conn.execute('UPDATE media_assets SET local_path=? WHERE id=?',(str(path),media))
    wire=dict(calls=[],credential_calls=[],reply=dict(listing_id=listing,observations=[dict(
        attachment_index=1,origin='pixels',subject='surface',status='visible',
        visible_content='Synthetic red surface',limited_inference='',
        uncertainty='Mock pixels cannot establish physical condition',affects_criteria=['goal'])]))
    def transport(request):
        wire['calls'].append(request)
        return httpx.Response(200,json=dict(id='synthetic-response',model='deepseek-flash',status='completed',
            output=[dict(type='message',role='assistant',content=[dict(type='output_text',text=json.dumps(wire['reply']))])]))
    def credential():
        wire['credential_calls'].append(True)
        return 'synthetic-credential-only'
    p.visual_executor=ProjectVisualExecutor(VisionSettings(enabled=True),credential,enabled=True,
        mock_transport=httpx.MockTransport(transport))
    approval=VisualApproval(id='synthetic-upload-approval',task_id=p.task_id,listing_id=listing,
        goal_revision=p.goal(p.task_id)['revision'],item_signature=p.signature(p.cards(p.task_id)[0]),
        images=[dict(media_id=media,sha256=hashlib.sha256(data).hexdigest())],
        approved=True,upload_authorized=True,downstream_text_authorized=True,budget_accepted=True,
        expires_at=time.time()+300)
    return p,listing,media,approval,wire,path,data


def approve(p,listing,decision=True):
    s=ConversationService(p.config);message=s.send_message(p.task_id,'Only synthetic saved image')
    s.store.transition_operation(message.operation.id,{'queued'},'running')
    req=s.store.complete_with_action_request(message.operation.id,ActionRequestInput(summary='Image',risk='Explicit one image',actions=['media'],listing_ids=[listing]))
    if decision:s.approve_action(p.task_id,req.id)
    else:s.reject_action(p.task_id,req.id)
    return req.id


def capture(setup,data=None,approval=None,transport=None):
    p,listing,media=setup;calls=[]
    def http(url,ip,deadline,cap):calls.append((url,ip));return 200,{'content-type':'not-trusted'},data or png()
    result=save_approved_image(p.config,p.task_id,media,approval or approve(p,listing),resolver=lambda host:['8.8.8.8'],transport=transport or http)
    return result,calls


def test_saved_metadata_repeat_approval_and_content_version(setup):
    p,listing,media=setup;approval=approve(p,listing);first,calls=capture(setup,approval=approval)
    assert first['state']=='saved' and first['width']==32 and first['height']==32 and first['mime']=='image/png'
    assert first['sha256']==hashlib.sha256(png()).hexdigest() and Path(first['local_path']).read_bytes()==png()
    again,second=capture(setup,approval=approval);assert again['id']==first['id'] and not second
    same,_=capture(setup);assert same['sha256']==first['sha256'] and same['local_path']==first['local_path']
    changed,_=capture(setup,png('blue'));assert changed['sha256']!=first['sha256']
    assert Path(first['local_path']).read_bytes()==png() and not list(p.config.media_dir.rglob('*.tmp'))
    assert not p.config.browser_profile_dir.with_suffix('.lock').exists()
    with p.source_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM media_assets').fetchone()[0]==1
        assert image_status(conn,media)['observed'] is False
        assert conn.execute('SELECT COUNT(DISTINCT sha256) FROM media_image_evidence').fetchone()[0]==2


def test_rejection_and_legacy_url_never_download_or_become_viewed(setup):
    p,listing,media=setup
    with p.source_db() as conn:assert image_status(conn,media)['state']=='url_only'
    with pytest.raises(ImageSafetyError,match='approval'):
        capture(setup,approval=approve(p,listing,False),transport=lambda *a:pytest.fail('No network'))


@pytest.mark.parametrize('url',['http://img.alicdn.com/a','https://localhost/a','https://img.alicdn.com:444/a','https://u:p@img.alicdn.com/a','https://127.0.0.1/a','https://img.alicdn.com.evil.test/a','https://img.alicdn.com/a#x'])
def test_url_rejected_before_dns(url):
    with pytest.raises(ImageSafetyError):fetch_image(url,resolver=lambda h:pytest.fail('No DNS'),transport=lambda *a:pytest.fail('No HTTP'))


@pytest.mark.parametrize('ip',['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1','fc00::1','224.0.0.1','0.0.0.0'])
def test_all_addresses_must_be_public(ip):
    with pytest.raises(ImageSafetyError):public_addresses(['8.8.8.8',ip])


def test_redirect_rebinding_and_hop_limit():
    calls=[]
    def http(url,ip,*args):calls.append(ip);return 302,{'location':'https://gw.alicdn.com/next'},b''
    with pytest.raises(ImageSafetyError,match='public'):
        fetch_image('https://img.alicdn.com/a',resolver=lambda h:['8.8.8.8'] if h.startswith('img') else ['192.168.1.2'],transport=http)
    assert calls==['8.8.8.8']
    with pytest.raises(ImageSafetyError):fetch_image('https://img.alicdn.com/a',resolver=lambda h:['8.8.8.8'],transport=lambda *a:(302,{'location':'https://evil.test/a'},b''))
    with pytest.raises(ImageSafetyError,match='redirect'):fetch_image('https://img.alicdn.com/a',resolver=lambda h:['8.8.8.8'],transport=http)


@pytest.mark.parametrize('data,limits',[(b'<html>login</html>',ImageLimits()),(b'<svg onload="x"/>',ImageLimits()),(png()[:30],ImageLimits()),(png(),ImageLimits(max_bytes=10)),(png(size=(64,64)),ImageLimits(max_pixels=100)),(png(size=(64,64)),ImageLimits(max_edge=40))])
def test_invalid_or_oversized_content(data,limits):
    with pytest.raises(ImageSafetyError):fetch_image('https://img.alicdn.com/a',limits=limits,resolver=lambda h:['8.8.8.8'],transport=lambda *a:(200,{'content-type':'image/png'},data))


def test_worker_timeout_releases_process():
    before={p.pid for p in multiprocessing.active_children()}
    with pytest.raises(ImageSafetyError):bounded_worker('decode',png(),ImageLimits(),.00001)
    assert {p.pid for p in multiprocessing.active_children()}==before


def test_animation_and_atomic_publish_failure_are_safe(setup,monkeypatch):
    from shopping_agent.image_evidence import _publish
    from shopping_agent.image_safety import validate_bytes
    frames=[Image.new('RGB',(16,16),color) for color in ('red','blue')]
    animated=io.BytesIO()
    frames[0].save(animated,format='PNG',save_all=True,append_images=frames[1:],duration=100,loop=0)
    with pytest.raises(ImageSafetyError,match='animated'):
        validate_bytes(animated.getvalue())
    data=png();metadata=validate_bytes(data)
    def interrupted(*args):raise OSError('Synthetic publication interruption')
    monkeypatch.setattr('shopping_agent.image_evidence.os.link',interrupted)
    with pytest.raises(OSError):_publish(data,metadata,setup[0].config.media_dir)
    assert not list(setup[0].config.media_dir.rglob('*.tmp'))
    assert not list(setup[0].config.media_dir.rglob('*.png'))


def test_image_count_total_bytes_and_private_staging_bounds(setup):
    import os
    import stat
    p,listing,media=setup;request,entry=frozen(setup)
    entries=[dict(entry,sha256=f'{i:064x}',evidence_id=f'image:{listing}:{media}:{i:064x}') for i in range(4)]
    with pytest.raises(ImageSafetyError,match='limit'):freeze(request,entries,53,1)
    with pytest.raises(ImageSafetyError,match='limit'):freeze(request,[dict(i,bytes=3*1024*1024) for i in entries[:3]],53,1)
    if os.name=='posix':
        assert stat.S_IMODE(Path(entry['local_path']).stat().st_mode)==0o600
        assert stat.S_IMODE(Path(entry['local_path']).parent.stat().st_mode)==0o700


def test_failed_attempt_is_durable_no_retry(setup):
    p,listing,media=setup;approval=approve(p,listing)
    failed,calls=capture(setup,b'not an image',approval=approval)
    assert failed['state']=='failed' and failed['sha256'] is None and len(calls)==1
    again,calls=capture(setup,approval=approval);assert again['id']==failed['id'] and not calls
    with p.source_db() as conn:assert image_status(conn,media)['observed'] is False


def test_concurrent_request_and_restart_never_replay(setup):
    p,listing,media=setup;approval=approve(p,listing);entered=threading.Event();release=threading.Event();calls=[]
    def http(*args):calls.append(1);entered.set();assert release.wait(5);return 200,{},png()
    with ThreadPoolExecutor(2) as pool:
        pending=pool.submit(capture,setup,None,approval,http);assert entered.wait(5)
        row,_=capture(setup,approval=approval);assert row['state']=='running'
        release.set();finished,_=pending.result()
    assert len(calls)==1;initialize(p.config.database_path)
    again,calls=capture(setup,approval=approval);assert not calls and again['id']==finished['id']


def frozen(setup):
    p,listing,media=setup;row,_=capture(setup)
    with p.source_db() as conn:entry=manifest_entry(conn,p.task_id,row['id'],p.config.media_dir)
    request=p._request(p.task_id,p.cards(p.task_id),'Synthetic local input only')
    return freeze(request,[entry,entry],53,1),entry


def test_frozen_manifest_run_binding_and_hash(setup):
    p,listing,media=setup;request,entry=frozen(setup)
    assert len(request.review_context['visual_inputs']['images'])==1
    assert request.review_context['visual_inputs']['study_id']==53 and request.review_context['visual_inputs']['remote_received'] is False
    assert verified_bytes(request,p.config.media_dir,(1<<60)+53)[0][1]==png()
    with pytest.raises(ImageSafetyError):verified_bytes(request,p.config.media_dir,(1<<60)+54)
    Path(entry['local_path']).write_bytes(png('blue'))
    with pytest.raises(ImageSafetyError,match='hash|changed'):verified_bytes(request,p.config.media_dir)


def test_visual_service_payload_parser_and_artifacts_without_cli(visual,monkeypatch):
    p,listing,media,approval,wire,path,data=visual
    monkeypatch.setattr(p.runtime,'run',lambda *a,**kw:pytest.fail('Visual execution must not invoke Codex CLI'))
    job=p.enqueue_visual(approval)
    assert wire['calls']==wire['credential_calls']==[]
    assert p.execute_next()
    assert len(wire['calls'])==len(wire['credential_calls'])==1
    request=wire['calls'][0];body=json.loads(request.content)
    assert str(request.url)=='https://api.deepseek.com/responses'
    assert body['tools']==[] and body['tool_choice']=='none'
    content=body['input'][0]['content']
    assert json.loads(content[0]['text'])['listing_id']==listing
    assert len(content)==2 and content[1]['type']=='input_image'
    assert base64.b64decode(content[1]['image_url'].split(',',1)[1])==data
    assert str(path).encode() not in request.content
    with p.db() as conn:
        row=conn.execute('SELECT * FROM studies WHERE id=?',(job,)).fetchone()
        context=json.loads(conn.execute('SELECT context_json FROM study_evidence_context WHERE study_id=?',(job,)).fetchone()[0])['visual']
    assert row['state']=='completed' and row['kind']=='visual'
    assert context['receipt']['mode']=='mock' and context['receipt']['client_submissions']==1
    observed=context['result']['observations'][0]
    assert observed['image']['media_id']==media and observed['image']['sha256']==approval.images[0].sha256
    assert observed['independently_verified'] is False
    assert path.read_bytes()==data and not list(p.config.media_dir.rglob('*.tmp'))
    artifacts=p.config.media_dir/'visual-research'/str(job)
    assert {f.name for f in artifacts.iterdir()}=={'attempt.json','raw-before-parse.json','execution.json'}
    assert all('synthetic-credential-only' not in f.read_text(encoding='utf-8') for f in artifacts.iterdir())


def visual_result(listing,ref):
    return AnswerResult(type='answer',content='Mock uncertain observation',candidate_ids=[],research=dict(criteria=[dict(criterion_id='appearance',description='外观',priority='soft',source_refs=['task_goal'])],assessments=[dict(listing_id=listing,conclusion='conditional',summary='Mock only',judgments=[dict(criterion_id='appearance',status='UNKNOWN',reason='图片中标签不清楚，实物待核实',source_type='image_observation',evidence_refs=[ref])])]))


def test_visual_refs_and_no_fake_delivery(setup):
    p,listing,media=setup;request,entry=frozen(setup);result=visual_result(listing,entry['evidence_id'])
    assert validate_observations(request,result,require_delivery=False) # Shape only, never publication.
    with pytest.raises(ImageSafetyError,match='远端接收'):validate_observations(request,result)
    for ref in ('card:unknown',entry['evidence_id'].replace(entry['sha256'],'0'*64),entry['evidence_id'].replace(f':{listing}:',':999:')):
        with pytest.raises(ImageSafetyError):validate_observations(request,visual_result(listing,ref),require_delivery=False)
    with pytest.raises(ImageSafetyError,match='没有视觉输入'):validate_observations(p._request(p.task_id,p.cards(p.task_id),'No images'),result)


def test_agent_run_idempotent_and_mock_summary_never_covers_or_integrates(visual):
    p,listing,media,approval,wire,path,data=visual;baseline=p.overview(p.task_id)
    wire['reply']=dict(type='answer',content='Mock summary only',candidate_ids=[])
    job=p.enqueue_visual(approval)
    assert p.enqueue_visual(approval)==job
    with p.db() as conn:
        snapshot=conn.execute('SELECT request_json FROM studies WHERE id=?',(job,)).fetchone()[0]
    req=CodexRequest.model_validate_json(snapshot)
    assert req.review_context['visual_inputs']['study_id']==job
    assert p.execute_next();after=p.overview(p.task_id)
    with p.db() as conn:
        assert tuple(conn.execute('SELECT state,request_json FROM studies WHERE id=?',(job,)).fetchone())==('failed',snapshot)
        assert conn.execute("SELECT COUNT(*) FROM studies WHERE kind='integration'").fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM studies').fetchone()[0]==1
        context=json.loads(conn.execute('SELECT context_json FROM study_evidence_context WHERE study_id=?',(job,)).fetchone()[0])['visual']
    assert context['current_usable'] is False and 'result' not in context
    assert after['coverage']['evaluated']==baseline['coverage']['evaluated'] and after['report']==baseline['report']
    assert p.enqueue_visual(approval)==job and not p.execute_next()
    assert len(wire['calls'])==1 and not p.runtime.requests
    with p.source_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM research_assessments').fetchone()[0]==0


def test_peer_pinning_tls_hostname_and_response_cleanup_without_network(monkeypatch):
    from shopping_agent.image_safety import PinnedHTTPS
    calls=[]
    class Sock:
        def getpeername(self):return ('8.8.8.8',443)
        def settimeout(self,v):pass
        def close(self):calls.append('closed')
    class Response:
        status=200
        def getheaders(self):return [('Content-Type','image/png')]
        def read1(self,n):
            if getattr(self,'done',False):return b''
            self.done=True;return png()
    def connect(address,timeout):calls.append(address);return Sock()
    def tls(context,sock,server_hostname):assert server_hostname=='img.alicdn.com';return sock
    monkeypatch.setattr('shopping_agent.image_safety.socket.create_connection',connect)
    monkeypatch.setattr('shopping_agent.image_safety.ssl.SSLContext.wrap_socket',tls)
    monkeypatch.setattr('shopping_agent.image_safety.http.client.HTTPSConnection.request',lambda self,*a,**kw:self.connect())
    monkeypatch.setattr('shopping_agent.image_safety.http.client.HTTPSConnection.getresponse',lambda self:Response())
    data,meta=fetch_image('https://img.alicdn.com/a',resolver=lambda h:['8.8.8.8'],transport=PinnedHTTPS._fetch)
    assert data==png() and ('8.8.8.8',443) in calls and 'closed' in calls


def test_expired_dns_budget_no_http_and_empty_policy():
    import time
    def slow(host):time.sleep(.015);return ['8.8.8.8']
    with pytest.raises(ImageSafetyError,match='deadline'):
        fetch_image('https://img.alicdn.com/a',limits=ImageLimits(total_seconds=.001),resolver=slow,transport=lambda *a:pytest.fail('Must not connect'))
    with pytest.raises(ImageSafetyError):fetch_image('https://img.alicdn.com/a',limits=ImageLimits(hosts=()),resolver=lambda h:pytest.fail('No policy'))


def test_original_bytes_not_overwritten_and_old_database_has_no_fake_saved_proof(setup):
    p,listing,media=setup
    with p.source_db() as conn:
        before=[tuple(r) for r in conn.execute('SELECT * FROM listing_snapshots')]
        conn.execute('DROP TABLE media_image_evidence')
        assert image_status(conn,media)['state']=='url_only'
    initialize(p.config.database_path)
    with p.source_db() as conn:
        assert before==[tuple(r) for r in conn.execute('SELECT * FROM listing_snapshots')]
        assert conn.execute('SELECT COUNT(*) FROM media_image_evidence').fetchone()[0]==0


def test_profile_busy_no_takeover_or_network(setup):
    p,listing,media=setup;approval=approve(p,listing)
    lock=p.config.browser_profile_dir.parent/(p.config.browser_profile_dir.name+'.lock')
    lock.write_text('existing owner')
    row,_=capture(setup,approval=approval,transport=lambda *a:pytest.fail('No network'))
    assert row['state']=='failed' and lock.read_text()=='existing owner'


@pytest.mark.parametrize('category',['MacBook Pro','NS2 Pro','Sony camera'])
def test_reference_validator_is_category_independent(setup,category):
    p,listing,media=setup;request,entry=frozen(setup)
    request=request.model_copy(update={'messages':(request.messages[0].model_copy(update={'content':category}),)})
    assert validate_observations(request,visual_result(listing,entry['evidence_id']),require_delivery=False)


def test_image_api_read_only_states_and_project_scope(setup):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from shopping_agent.web.image_routes import register_image_routes
    from shopping_agent.web.dependencies import get_config
    p,listing,media=setup;app=FastAPI();register_image_routes(app);app.dependency_overrides[get_config]=lambda:p.config
    foreign=p.create('Other project','Other goal',None,[],[],1,False)['id']
    base=f'/api/tasks/{p.task_id}/listings/{listing}/images'
    def snapshot():
        with p.source_db() as conn:return list(conn.iterdump())
    with TestClient(app) as client:
        before=snapshot();response=client.get(base);result=response.json()
        assert result['state']=='not_prepared' and result['local_count']==0
        assert result['images'][0]['state']=='not_prepared' and result['images'][0]['display_url'] is None
        assert 'evidence' not in result['images'][0] and snapshot()==before
        path=p.config.media_dir/'prepared.png';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(png())
        with p.source_db() as conn:conn.execute('UPDATE media_assets SET local_path=? WHERE id=?',(str(path),media))
        before=snapshot();response=client.get(base);result=response.json()['images'][0]
        assert result['state']=='local_available' and result['sha256']==hashlib.sha256(png()).hexdigest()
        assert result['display_url'].startswith(base+f'/{media}/content?sha256=')
        assert client.get(result['display_url']).content==png()
        assert str(path) not in response.text and str(p.config.media_dir) not in response.text
        assert client.get(f'/api/tasks/999/listings/{listing}/images').status_code==404
        assert client.get(f'/api/tasks/{foreign}/listings/{listing}/images').status_code==404
        assert client.get(f'/api/tasks/999/listings/{listing}/images/{media}/content?sha256='+result['sha256']).status_code==404
        assert client.get(base+f'/{media}/content?sha256='+'0'*64).status_code==404
        assert snapshot()==before
    with p.db() as conn:assert conn.execute('SELECT COUNT(*) FROM studies').fetchone()[0]==0
    assert not p.runtime.requests


def test_manifest_rejects_wrong_project_path_and_scope(setup,tmp_path):
    p,listing,media=setup;row,_=capture(setup)
    with p.source_db() as conn:
        with pytest.raises(ImageSafetyError):manifest_entry(conn,p.task_id+99,row['id'],p.config.media_dir)
        with pytest.raises(ImageSafetyError):manifest_entry(conn,p.task_id,row['id'],tmp_path/'another-root')
    request,entry=frozen(setup)
    with pytest.raises(ImageSafetyError):freeze(request,[dict(entry,listing_id=999)],53,1)


def test_crash_reservation_not_replayed(setup):
    p,listing,media=setup;approval=approve(p,listing)
    with p.source_db() as conn:
        conn.execute("INSERT INTO media_image_evidence(task_id,media_id,approval_id,request_key,source_url,state,created_at) VALUES(?,?,?,?,?,'running','now')",(p.task_id,media,approval,f'image-download:{approval}:{media}','https://img.alicdn.com/a'))
    initialize(p.config.database_path);row,calls=capture(setup,approval=approval)
    assert row['state']=='running' and not calls


def test_existing_bytes_not_overwritten_and_staging_cleaned(setup):
    p,listing,media=setup;row,_=capture(setup);path=Path(row['local_path']);path.write_bytes(b'tampered')
    again,_=capture(setup)
    assert again['state']=='failed' and path.read_bytes()==b'tampered' and not list(p.config.media_dir.rglob('*.tmp'))


def test_research_enqueue_concurrency_and_restart_keep_one_frozen_task(visual):
    p,listing,media,approval,wire,path,data=visual
    barrier=threading.Barrier(2)
    def enqueue():
        barrier.wait(timeout=10)
        return p.enqueue_visual(approval)
    with ThreadPoolExecutor(2) as pool:
        jobs=list(pool.map(lambda _:enqueue(),range(2)))
    assert len(set(jobs))==1
    def frozen_rows(research):
        with research.db() as conn:
            return [tuple(row) for row in conn.execute('SELECT s.id,s.request_json,s.request_key,x.context_json,b.goal_revision FROM studies s JOIN study_evidence_context x ON x.study_id=s.id JOIN study_goal_bindings b ON b.study_id=s.id')]
    before=frozen_rows(p);assert len(before)==1
    request=CodexRequest.model_validate_json(before[0][1])
    images=request.review_context['visual_inputs']
    assert images['study_id']==jobs[0] and images['goal_revision']==approval.goal_revision
    assert request.allowed_listing_ids==frozenset({listing})
    assert [(i['media_id'],i['sha256']) for i in images['images']]==[(media,approval.images[0].sha256)]
    from shopping_agent.project_research import ProjectResearch
    from shopping_agent.monitoring import MonitorStore
    reopened=ProjectResearch(p.config,p.runtime,MonitorStore(p.config))
    reopened.visual_executor=p.visual_executor
    assert reopened.enqueue_visual(approval)==jobs[0]
    assert frozen_rows(reopened)==before
    assert wire['calls']==wire['credential_calls']==[] and not p.runtime.requests


def test_limits_source_and_approval_do_not_mutate_signature_or_expand_scope(visual):
    p,listing,media,approval,wire,path,data=visual
    before=p.signature(p.cards(p.task_id)[0]);goal=p.goal(p.task_id)
    foreign=p.create('Other project','Other goal',None,[],[],1,False)['id']
    payload=approval.model_dump()
    invalid=[dict(payload,**{flag:False}) for flag in
             ['approved','upload_authorized','downstream_text_authorized','budget_accepted']]
    invalid += [dict(payload,expires_at=0.0),dict(payload,task_id=p.task_id+999),dict(payload,task_id=foreign),
        dict(payload,listing_id=listing+999),dict(payload,goal_revision=approval.goal_revision+1),
        dict(payload,images=[dict(media_id=media+999,sha256=approval.images[0].sha256)]),
        dict(payload,images=[dict(media_id=media,sha256='0'*64)]),
        dict(payload,images=[dict(media_id=media+i,sha256=approval.images[0].sha256) for i in range(4)])]
    for value in invalid:
        with pytest.raises(ValueError):p.enqueue_visual(value)
    with pytest.raises(ValueError):p.enqueue(p.task_id,ids=[listing],use_visual=True,automatic=True)
    with p.source_db() as conn:conn.execute('UPDATE media_assets SET source_url=? WHERE id=?',('https://127.0.0.1/private',media))
    try:
        with pytest.raises(ValueError):p.enqueue_visual(approval)
    finally:
        with p.source_db() as conn:conn.execute('UPDATE media_assets SET source_url=? WHERE id=?',('https://img.alicdn.com/synthetic.png',media))
    assert p.signature(p.cards(p.task_id)[0])==before and p.goal(p.task_id)==goal
    assert wire['calls']==wire['credential_calls']==[] and not p.runtime.requests
    with p.db() as conn:assert conn.execute('SELECT COUNT(*) FROM studies').fetchone()[0]==0


def test_actual_peer_mismatch_is_rejected_and_connection_closed(monkeypatch):
    from shopping_agent.image_safety import PinnedHTTPS
    closed=[]
    class Sock:
        def getpeername(self):return ('127.0.0.1',443)
        def close(self):closed.append(True)
    monkeypatch.setattr('shopping_agent.image_safety.socket.create_connection',lambda *a,**kw:Sock())
    monkeypatch.setattr('shopping_agent.image_safety.ssl.SSLContext.wrap_socket',lambda self,sock,**kw:sock)
    monkeypatch.setattr('shopping_agent.image_safety.http.client.HTTPSConnection.request',lambda self,*a,**kw:self.connect())
    with pytest.raises(ImageSafetyError,match='peer_mismatch'):
        fetch_image('https://img.alicdn.com/a',resolver=lambda h:['8.8.8.8'],transport=PinnedHTTPS._fetch)
    assert closed
