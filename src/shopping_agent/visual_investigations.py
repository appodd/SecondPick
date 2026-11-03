"""P5 bounded planning on P1 investigation records and D2 visual studies.

No scheduler or DDL. Only the existing completed-text hook may advance granted
plans automatically. Downloads and model transmission have separate permissions.
"""
from pathlib import Path
import hashlib
import json
import os
import tempfile
import time
import uuid
from pydantic import BaseModel, ConfigDict, Field
from shopping_agent import project_visual as pv, visual_decisions as vd
from shopping_agent.image_safety import ImageLimits, checked_url, fetch_image, validate_bytes
from shopping_agent.vision import encode, sha
from shopping_agent.vision_settings import VisionSettingsStore


class ProjectGrant(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool = False
    allow_image_fetch: bool = False
    listing_ids: list[int] = Field(default_factory=list, max_length=20)
    max_requests: int = Field(default=1, ge=1, le=2)
    budget_usd: float = Field(default=.25, gt=0, le=1)
    expires_at: float = 0.0
    provider: str = 'deepseek'
    model: str = 'deepseek-flash'


class VisualInvestigations:
    def __init__(self, research, store, *, execution_allowed=lambda: False,
                 fetch_allowed=lambda: False, transport=None, resolver=None, mock_transport=None):
        self.p, self.store = research, store
        self.execution_allowed, self.fetch_allowed = execution_allowed, fetch_allowed
        self.transport, self.resolver, self.mock_transport = transport, resolver, mock_transport
        self.root = Path(research.config.media_dir) / 'visual-investigation-settings'

    def _path(self, task):
        self.p.require(task)
        if self.root.is_symlink(): raise ValueError('unsafe_visual_policy_directory')
        path = self.root / (str(task) + '.json')
        if path.is_symlink(): raise ValueError('unsafe_visual_policy_file')
        return path

    def policy(self, task):
        path = self._path(task)
        return json.loads(path.read_text('utf-8')) if path.exists() else dict(
            revision=0, grant=ProjectGrant().model_dump(), id=None, goal_revision=None)

    def save_policy(self, task, grant, *, expected_revision, confirmed):
        if confirmed is not True: raise ValueError('explicit_project_visual_authorization_required')
        grant = ProjectGrant.model_validate(grant)
        goal = self.p.goal(task)
        if grant.provider != 'deepseek' or grant.model != 'deepseek-flash': raise ValueError('unsupported_visual_model')
        ids = {c['listing_id'] for c in self.p.cards(task)}
        if len(set(grant.listing_ids)) != len(grant.listing_ids) or any(type(i) is not int or i not in ids for i in grant.listing_ids):
            raise ValueError('visual_policy_item_outside_project')
        if grant.enabled or grant.allow_image_fetch:
            if not grant.listing_ids or not time.time() < grant.expires_at <= time.time()+86400:
                raise ValueError('bounded_scope_and_expiry_required')
        # Same source transaction serializes policy updates and budget reservations.
        with self.p.source_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = self.policy(task)
            if old['revision'] != expected_revision: raise ValueError('visual_policy_revision_changed')
            value = dict(revision=expected_revision+1, id=uuid.uuid4().hex,
                         goal_revision=goal['revision'], grant=grant.model_dump(), at=time.time())
            writer = VisionSettingsStore(self.root)
            writer._write(self._path(task), encode(value))
        return value  # Saving never prepares pixels, enqueues or calls a model.

    def _items(self, conn, task):
        rows = conn.execute("SELECT * FROM project_investigations WHERE task_id=? AND kind='manual' AND json_extract(plan_json,'$.visual_investigation')=1 ORDER BY id DESC LIMIT 101", (task,)).fetchall()
        if len(rows)>100: raise ValueError('visual_investigation_history_limit_requires_review')
        return [dict(r, plan=json.loads(r['plan_json']), outcome=json.loads(r['outcome_json']))
                for r in rows if json.loads(r['plan_json']).get('visual_investigation') is True]

    def list(self, task, listing=None):
        self.p.require(task)
        with self.p.source_db() as conn: rows = self._items(conn, task)
        current = self.p.goal(task)['revision']
        signatures={c['listing_id']:self.p.signature(c) for c in self.p.cards(task)}
        return [dict(id=r['id'], listing_id=r['listing_id'], goal_revision=r['goal_revision'],
                     stale=r['goal_revision'] != current or signatures.get(r['listing_id'])!=r['plan']['item_signature'], plan=r['plan'], outcome=r['outcome'])
                for r in rows if listing is None or r['listing_id'] == listing][:20]

    def _row(self, task, ident):
        with self.p.source_db() as conn:
            r = next((r for r in self._items(conn, task) if r['id'] == ident), None)
        if not r: raise ValueError('visual_investigation_outside_project')
        if r['decision']=='cancelled': raise ValueError('visual_investigation_cancelled')
        card = next((c for c in self.p.cards(task) if c['listing_id'] == r['listing_id']), None)
        if not card or self.p.goal(task)['revision'] != r['goal_revision'] or self.p.signature(card) != r['plan']['item_signature']:
            raise ValueError('visual_investigation_stale')
        with self.p.source_db() as c:
            for image in r['plan']['media']:
                source=c.execute('SELECT listing_id,source_url FROM media_assets WHERE id=?',(image['id'],)).fetchone()
                if not source or tuple(source)!=(r['listing_id'],image['source_url']): raise ValueError('image_source_changed')
        return r

    def presentation(self, task, listing=None):
        """Small live projection; rejected/stale evidence is never a current finding."""
        from shopping_agent.web.visual_routes import evidence_view
        rows=self.list(task,listing)
        for row in rows[:3]:
            row['insights']=[]
            inv=vd.inventory(self.p,task,row['listing_id'])
            available={i['media_id']:i for i in inv['images']}
            expected={i['media_id']:i for i in row['outcome'].get('images',[])}
            row['media_states']=[]
            for media in row['plan']['media']:
                actual=available.get(media['id']);old=expected.get(media['id'])
                if old and (not actual or actual['sha256']!=old['sha256'] or actual['source_url']!=media['source_url']): state='expired'
                elif actual: state='local_available'
                elif row['outcome'].get('error')=='image_preparation_failed': state='fetch_failed'
                else: state='url_only'
                row['media_states'].append(dict(media_id=media['id'],state=state,sha256=actual['sha256'] if actual else None,availability_only=True))
            if row['stale'] or row['outcome'].get('state')!='completed': continue
            dto=evidence_view(self.p,task,row['listing_id'],row['outcome']['study_id'],inv=inv)
            for observation in dto['observations']:
                if observation['review_state'] not in {'accepted','pending_review'}: continue
                if observation['freshness']!='fresh' and set(observation['freshness_reasons'])!={'requires_human_review'}: continue
                if observation['subject'] not in {'accessory','label','packaging_print','identity','device_count'}: continue
                question=('请卖家补充可区分包装印刷图与实际设备的照片，不能据此认定数量。'
                          if observation['subject'] in {'device_count','packaging_print','identity'} else observation['uncertainty'])
                row['insights'].append(dict(observation_id=observation['id'],media_id=observation['media_id'],
                    review_state=observation['review_state'],question=question[:240],source_type='image_observation'))
            row['insights']=row['insights'][:2]
        return rows

    def _update(self, task, ident, **changes):
        with self.p.source_db() as c:
            c.execute('BEGIN IMMEDIATE')
            r = next(r for r in self._items(c, task) if r['id'] == ident)
            out = dict(r['outcome'], **changes)
            c.execute('UPDATE project_investigations SET outcome_json=? WHERE id=?', (json.dumps(out, ensure_ascii=False), ident))
        return out

    def _signals(self, task, card, explicit):
        """Only current bound structured research; old nomination alone is insufficient."""
        from shopping_agent.evidence_research import assessment
        listing = card['listing_id']; goal = self.p.goal(task); sig = self.p.signature(card)
        with self.p.db() as c:
            favorite = bool(c.execute('SELECT 1 FROM favorites WHERE task_id=? AND listing_id=?', (task, listing)).fetchone())
            rows = c.execute("SELECT s.*,b.goal_revision FROM studies s JOIN study_goal_bindings b ON b.study_id=s.id WHERE s.task_id=? AND s.state='completed' AND s.kind!='visual' ORDER BY s.id DESC LIMIT 100", (task,)).fetchall()
        current = next((r for r in rows if r['goal_revision']==goal['revision'] and [listing, sig] in json.loads(r['versions_json'])), None)
        result = json.loads(current['result_json'] or '{}') if current else {}
        prior = assessment(result, listing) if current else None
        reasons = []
        if explicit: reasons.append('用户明确要求深入调查')
        if prior and prior['conclusion']=='not_met' and not explicit: return [], '已有当前文字判断明确不符，不消耗视觉预算', []
        if goal['budget'] is not None and isinstance(card.get('price_value'), (int,float)) and card['price_value'] > goal['budget'] and not explicit:
            return [], '挂牌超出项目预算，暂不优先调查', []
        if favorite: reasons.append('用户关注的商品，需要补充可见证据')
        if prior and any(j['status']=='CONFLICT' for j in prior['judgments']): reasons.append('当前逐项判断存在证据冲突，需要核对图片')
        if prior and listing in result.get('candidate_ids', []) and any(j['status']=='UNKNOWN' for j in prior['judgments']):
            reasons.append('当前文字研究候选仍有关键未知项')
        if not reasons: return [], '没有当前候选、用户关注或结构化异常依据；不因新图片自动调查', []
        return reasons, None, [current['id']] if current else []

    def propose(self, task, ids=None, *, media_ids=None, media_only=False, image_request_key=None):
        policy = self.p.policy(task)
        if policy['completed'] and not media_only: return dict(items=self.list(task), skipped=[dict(reason='项目已结束')])
        cards = self.p.cards(task); index = {c['listing_id']: c for c in cards}
        if ids is not None and (not ids or len(ids)>3 or not set(ids)<=set(index)): raise ValueError('visual_proposal_scope_invalid')
        if media_ids is not None and (not media_only or not ids or len(ids)!=1 or not 1<=len(media_ids)<=3 or len(set(media_ids))!=len(media_ids)):raise ValueError('image_only_scope_invalid')
        chosen=[]; skipped=[]; goal=self.p.goal(task)
        for card in cards[:100]:
            listing=card['listing_id']
            if ids is not None and listing not in ids: continue
            reasons, skip, source_studies=self._signals(task,card,ids is not None)
            if skip: skipped.append(dict(listing_id=listing,reason=skip));continue
            audit=vd.catalog(self.p,task,listing,self.store.read())
            if audit['bundles'] and not media_only:
                skipped.append(dict(listing_id=listing,reason='相同内容和研究版本已有认可观察，复用而不重传'));continue
            if audit['attempts'] and not media_only:
                attempted={h for a in audit['attempts'] for h in a['hashes']}
                available={i['sha256'] for i in audit['inventory']['unique']}
                if available and available<=attempted:
                    skipped.append(dict(listing_id=listing,reason='同图已尝试或待审阅，不自动重试'));continue
            with self.p.source_db() as c:
                media=[dict(r) for r in c.execute("SELECT id,source_url FROM media_assets WHERE listing_id=? AND media_type='product_image_url' ORDER BY id LIMIT 20",(listing,))]
            safe=[]
            for m in media:
                try: checked_url(m['source_url'],ImageLimits());safe.append(m)
                except ValueError: pass
            if not safe: skipped.append(dict(listing_id=listing,reason='没有允许来源的商品图片，保持 UNKNOWN'));continue
            if media_ids is not None:
                by_id={m['id']:m for m in safe}
                if not set(media_ids)<=set(by_id):raise ValueError('image_selection_outside_listing')
                safe=[by_id[i] for i in media_ids]
            # No OCR, seller text or URL is promoted to an observed pixel.
            plan=dict(visual_investigation=True,title=card['title'],reason='；'.join(reasons),
                      item_signature=self.p.signature(card),media=safe[:3],purpose=pv.DEFAULT_PURPOSE,
                      objective='选择性图片辅助调查，不自动改写研究判断',capability='需独立授权的视觉调查，不是 BrowserJob',
                      expected_information=['补充外观、实际展示的配件与待核查线索；不证明功能或真伪'],
                      evidence_gaps=[],manual_questions=[],seller_public_questions=[],
                      source_study_ids=source_studies,
                      selection_source='explicit_user' if ids is not None else 'current_saved_research')
            if media_only:plan['media_only']=True
            key='p5:'+sha(encode([listing,goal['revision'],plan['item_signature'],plan['media']]+(['images-only',image_request_key] if media_only else [])))
            chosen.append((listing,key,plan))
        with self.p.source_db() as c:
            c.execute('BEGIN IMMEDIATE')
            existing=self._items(c,task)
            active=sum(not r['plan'].get('media_only') and r['outcome'].get('state') not in {'completed','failed','skipped'} and r['goal_revision']==goal['revision'] for r in existing)
            for listing,key,plan in chosen:
                if any(r['evidence_key']==key for r in existing) or not media_only and active>=3: continue
                c.execute("INSERT OR IGNORE INTO project_investigations(task_id,listing_id,goal_revision,kind,evidence_key,plan_json,created_at) VALUES(?,?,?,'manual',?,?,?)",
                          (task,listing,goal['revision'],key,json.dumps(plan,ensure_ascii=False),self.p.clock()))
                active+=1
        return dict(items=self.list(task),skipped=skipped[:20])

    def _allowed(self, task, row, *, model=False):
        p=self.p.policy(task);cfg=self.store.read();value=self.policy(task);g=ProjectGrant.model_validate(value['grant'])
        if p['paused'] or p['completed']: raise ValueError('project_paused_or_completed')
        if value['goal_revision']!=row['goal_revision'] or g.expires_at<=time.time() or row['listing_id'] not in g.listing_ids:
            raise ValueError('project_visual_authorization_missing_expired_or_stale')
        if model:
            if not g.enabled or not self.execution_allowed() or not cfg.enabled: raise ValueError('visual_execution_disabled_or_unauthorized')
            if (cfg.provider,cfg.model,cfg.timeout_seconds,cfg.max_output_tokens)!=('deepseek','deepseek-flash',300,3000):
                raise ValueError('visual_execution_configuration_changed')
            card=next(c for c in self.p.cards(task) if c['listing_id']==row['listing_id'])
            reasons,_,_=self._signals(task,card,row['plan']['selection_source']=='explicit_user')
            if not reasons: raise ValueError('visual_investigation_value_signal_no_longer_current')
        else:
            if not g.allow_image_fetch or not self.fetch_allowed(): raise ValueError('image_fetch_not_authorized')
        return value

    def prepare(self, task, ident, *, image_only_check=None):
        row=self._row(task,ident)
        media_only=row['plan'].get('media_only') is True
        if media_only and not callable(image_only_check):raise ValueError('explicit_image_only_approval_required')
        if not media_only and (self.p.policy(task)['paused'] or self.p.policy(task)['completed']): raise ValueError('project_paused_or_completed')
        def authorize():
            if media_only:image_only_check()
            else:self._allowed(task,self._row(task,ident))
        if media_only:authorize()
        if row['outcome'].get('state') in {'fetching','failed','executing','completed'}: raise ValueError('visual_plan_already_attempted')
        inv=vd.inventory(self.p,task,row['listing_id'])
        existing={i['media_id']:i for i in inv['images']}
        selected=[m['id'] for m in row['plan']['media']]
        if all(i in existing for i in selected):
            unique={}
            for i in selected: unique.setdefault(existing[i]['sha256'],existing[i])
            images=list(unique.values())
            if sum(i['bytes'] for i in images)>8*1024*1024: raise ValueError('image_total_bytes_exceeded')
            return self._update(task,ident,state='prepared',images=images,cache_reused=True)
        authorize()
        from shopping_agent.detail import browser_profile_lock
        # Same platform profile lease and busy checks as the existing controlled downloader.
        with browser_profile_lock(self.p.config.browser_profile_dir,timeout_seconds=0,stale_after_seconds=float('inf')):
            with self.p.source_db() as c:
                c.execute('BEGIN IMMEDIATE')
                live=next(r for r in self._items(c,task) if r['id']==ident)
                if live['outcome'].get('state') in {'fetching','failed','executing','completed'}: raise ValueError('visual_plan_already_attempted')
                if c.execute("SELECT 1 FROM browser_jobs WHERE state IN ('queued','running')").fetchone() or c.execute("SELECT 1 FROM monitors WHERE state IN ('running','waiting')").fetchone() or c.execute("SELECT 1 FROM operations WHERE state IN ('queued','running')").fetchone(): raise ValueError('image_platform_busy')
                c.execute('UPDATE project_investigations SET outcome_json=? WHERE id=?',(json.dumps(dict(live['outcome'],state='fetching')),ident))
            with self.p.db() as c:
                if c.execute("SELECT 1 FROM studies WHERE state IN ('queued','running')").fetchone():
                    self._update(task,ident,state='failed',error='image_research_busy',image_state='unknown')
                    raise ValueError('image_research_busy')
            images=[];seen=set();total=0
            try:
                for m in row['plan']['media']:
                    self._row(task,ident);authorize()
                    if m['id'] in existing: image=existing[m['id']]
                    else:
                        from shopping_agent.image_cache import prepare_cached_image
                        meta=prepare_cached_image(self.p.config,m['id'],row['listing_id'],m['source_url'],authorize=authorize,connection=self.p.source_db,resolver=self.resolver,transport=self.transport)
                        image=pv.entries(self.p,task,row['listing_id'],[pv.ImagePermission(media_id=m['id'],sha256=meta['sha256'])])[0]
                    total+=image['bytes']
                    if total>8*1024*1024: raise ValueError('image_total_bytes_exceeded')
                    if image['sha256'] not in seen: images.append(image);seen.add(image['sha256'])
                    self._update(task,ident,state='fetching',images=images)
                # Downloads do not authorize silently re-binding changed seller text or goals.
                self._row(task,ident)
                return self._update(task,ident,state='prepared',images=images,image_state='local_available')
            except Exception:
                self._update(task,ident,state='failed',error='image_preparation_failed',image_state='unknown')
                return dict(state='failed',image_state='unknown',error='image_preparation_failed')

    def execute(self, task, ident):
        row=self._row(task,ident)
        if row['plan'].get('media_only'):raise ValueError('images_only_is_not_visual_authorization')
        if row['outcome'].get('state')!='prepared': raise ValueError('visual_images_not_prepared_or_attempt_used')
        policy=self._allowed(task,row,model=True)
        from shopping_agent.web.visual_routes import ApprovalDesk, PreviewInput
        # This is an explicit project grant, NOT a fabricated D2 range-confirmation ticket.
        desk=ApprovalDesk();scope=desk.scope(self.p,self.store,task,row['listing_id'],PreviewInput(media_ids=[i['media_id'] for i in row['outcome']['images']],purpose=row['plan']['purpose']))
        config=self.store.read()
        if getattr(config,'profile_id',None) and (config.profile_id,config.profile_revision)!=(scope.get('profile_id'),scope.get('profile_revision')): raise ValueError('visual_configuration_changed')
        if [(i['media_id'],i['sha256']) for i in scope['images']]!=[(i['media_id'],i['sha256']) for i in row['outcome']['images']]: raise ValueError('prepared_image_content_changed')
        with self.p.source_db() as c:
            c.execute('BEGIN IMMEDIATE')
            current=next(r for r in self._items(c,task) if r['id']==ident)
            if current['outcome'].get('reservation'): raise ValueError('visual_plan_attempt_used')
            if self.policy(task)!=policy: raise ValueError('visual_project_grant_changed')
            used=[r['outcome']['reservation'] for r in self._items(c,task) if r['outcome'].get('reservation',{}).get('policy_id')==policy['id']]
            if len(used)>=policy['grant']['max_requests'] or sum(x['estimated_usd'] for x in used)+scope['cost_estimate']['usd']>policy['grant']['budget_usd']: raise ValueError('visual_local_budget_exhausted')
            reservation=dict(policy_id=policy['id'],authorization=policy,estimated_usd=scope['cost_estimate']['usd'],scope_sha256=sha(encode(scope)),at=time.time())
            out=dict(current['outcome'],state='executing',reservation=reservation)
            c.execute('UPDATE project_investigations SET outcome_json=? WHERE id=?',(json.dumps(out),ident))
        approval=pv.VisualApproval(id=f'p5:{ident}:{policy["id"]}',task_id=task,listing_id=row['listing_id'],goal_revision=scope['goal_revision'],
            item_signature=scope['item_signature'],images=[pv.ImagePermission(media_id=i['media_id'],sha256=i['sha256']) for i in scope['images']],
            provider=scope['provider'],model=scope['model'],timeout_seconds=scope['timeout_seconds'],max_output_tokens=scope['max_output_tokens'],
            approved=True,upload_authorized=True,downstream_text_authorized=True,budget_accepted=True,
            expires_at=min(policy['grant']['expires_at'],time.time()+300),request_sha256=scope['request_sha256'],
            analysis_purpose=scope['purpose'],authorization_source='project_policy',authorization_revision=policy['revision'])
        service=self
        class GrantedExecutor(pv.ProjectVisualExecutor):
            def check(executor,grant):
                if service.store.read() != executor.settings: raise ValueError('visual_configuration_changed')
                super().check(grant)
                if service._allowed(task,service._row(task,ident),model=True)!=policy: raise ValueError('visual_project_grant_changed')
        executor=GrantedExecutor(config,None,enabled=True,mock_transport=self.mock_transport)
        def credential():
            executor.check(approval)
            pv._validate_permission(self.p,approval)
            pv.entries(self.p,task,row['listing_id'],approval.images)
            return self.store.credential(approval.provider, expected=executor.settings)
        executor.credential_supplier=credential
        try:
            study=pv.enqueue(self.p,approval,executor=executor,start_now=True)
            with self.p.db() as c: run=dict(c.execute('SELECT * FROM studies WHERE id=?',(study,)).fetchone())
            if run['state']!='running': raise ValueError('visual_study_already_attempted')
            pv.run_claimed(self.p,run,executor=executor)
            with self.p.db() as c:
                state=c.execute('SELECT state FROM studies WHERE id=?',(study,)).fetchone()[0]
                ctx=json.loads(c.execute('SELECT context_json FROM study_evidence_context WHERE study_id=?',(study,)).fetchone()[0])['visual']
            return self._update(task,ident,state=state,study_id=study,receipt={k:ctx.get('receipt',{}).get(k) for k in ('http_status','model','elapsed_seconds','usage','client_submissions','mode')},requires_visual_review=True)
        except Exception:
            self._update(task,ident,state='failed',error='visual_investigation_execution_failed')
            raise ValueError('visual_investigation_execution_failed') from None

    def after_text(self, task):
        """One bounded pass on the existing Agent completion boundary, no polling loop."""
        proposals=self.propose(task)
        for r in proposals['items'][:3]:
            try:
                if r['plan'].get('media_only') or r['stale'] or r['outcome'].get('state') in {'failed','completed','executing','fetching'}: continue
                if r['outcome'].get('state')!='prepared': self.prepare(task,r['id'])
                if self.policy(task)['grant']['enabled']: self.execute(task,r['id'])
            except (ValueError,OSError): continue  # Retain suggestion; never fail saved text or retry.
        return self.list(task)


def publish(data, metadata, root):
    """Content-addressed publication from P4-A _publish; no migration/attempt table."""
    root=Path(root)
    if root.is_symlink(): raise ValueError('unsafe_image_store')
    directory=root/'image-evidence'
    if directory.is_symlink(): raise ValueError('unsafe_image_store')
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=directory/(metadata['sha256']+{'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[metadata['mime']])
    if path.exists():
        if path.is_symlink() or sha(path.read_bytes())!=metadata['sha256']: raise ValueError('cached_image_content_invalid')
        return path.resolve()
    fd,temp=tempfile.mkstemp(prefix='.image-',dir=directory)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        try: os.link(temp,path)
        except FileExistsError:
            if path.is_symlink() or sha(path.read_bytes())!=metadata['sha256']: raise ValueError('cached_image_content_invalid')
        return path.resolve()
    finally: Path(temp).unlink(missing_ok=True)
