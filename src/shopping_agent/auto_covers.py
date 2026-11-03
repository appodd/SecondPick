"""One bounded image-I/O worker, not an Agent/study or visual investigation.

Durable non-secret metadata uses the existing atomic JSON + OS lease pattern.
Only the importer admits items; reading a page never discovers/enqueues old items.
"""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,os,sqlite3,threading,time,uuid,logging
from shopping_agent.service_lease import ServiceLease
from shopping_agent.image_safety import checked_url,ImageLimits

_lock=threading.RLock()
PENDING_LIMIT=100
TRACKED_LIMIT=1000


def cover_root(config):return Path(config.database_path).with_suffix('.cover-cache')


def load_state(config):
    root=cover_root(config);p=root/'state.json'
    if root.is_symlink() or p.is_symlink():raise ValueError('unsafe_cover_state')
    if not p.exists():return None
    if p.stat().st_size>12*1024*1024:raise ValueError('cover_state_too_large')
    value=json.loads(p.read_text('utf-8'))
    if value.get('version')!=1:raise ValueError('invalid_cover_state')
    return value


@contextmanager
def state_edit(config):
    root=cover_root(config);root.mkdir(parents=True,exist_ok=True)
    if root.is_symlink() or (root/'state.service.lock').is_symlink():raise ValueError('unsafe_cover_state')
    with _lock,ServiceLease(root/'state'):
        value=load_state(config)
        yield value
        if value is not None:
            tmp=root/(uuid.uuid4().hex+'.tmp')
            try:
                tmp.write_text(json.dumps(value,separators=(',',':')),encoding='utf-8')
                os.replace(tmp,root/'state.json')
            finally:tmp.unlink(missing_ok=True)


@contextmanager
def source_db(config):
    c=sqlite3.connect(config.database_path,timeout=.5);c.row_factory=sqlite3.Row
    try:
        with c:yield c
    finally:c.close()


class AutoCovers:
    def __init__(self,config,*,resolver=None,transport=None,clock=time.time):
        self.config,self.resolver,self.transport,self.clock=config,resolver,transport,clock
        self.closed=threading.Event();self.thread=None

    def enabled(self):return self.config.safety.auto_cover_cache_enabled is True

    def activate(self):
        # The activation watermark excludes every pre-existing product, even on first load.
        root=cover_root(self.config);root.mkdir(parents=True,exist_ok=True)
        if root.is_symlink() or (root/'state.service.lock').is_symlink():raise ValueError('unsafe_cover_state')
        with _lock,ServiceLease(root/'state'):
            if load_state(self.config) is not None:return
            with source_db(self.config) as c:watermark=c.execute('SELECT COALESCE(MAX(id),0) FROM listing_snapshots').fetchone()[0]
            value=dict(version=1,watermark=watermark,policies={},jobs={},last_request=0,dropped=0)
            tmp=root/(uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(value),encoding='utf-8');os.replace(tmp,root/'state.json')

    def policy(self,task):
        with source_db(self.config) as c:
            if not c.execute('SELECT 1 FROM research_tasks WHERE id=?',(task,)).fetchone():raise ValueError('Research task not found: '+str(task))
        value=load_state(self.config)
        return dict(enabled=True,revision=0,watermark=value['watermark'] if value else None) if not value or str(task) not in value['policies'] else value['policies'][str(task)]

    def configure(self,task,enabled,expected_revision):
        if type(enabled) is not bool:raise ValueError('invalid_cover_setting')
        self.activate();self.policy(task)
        with state_edit(self.config) as value:
            current=value['policies'].get(str(task),dict(enabled=True,revision=0,watermark=value['watermark']))
            if current['revision']!=expected_revision:raise ValueError('cover_setting_changed_refresh_required')
            if current['enabled']!=enabled:
                with source_db(self.config) as c:watermark=c.execute('SELECT COALESCE(MAX(id),0) FROM listing_snapshots').fetchone()[0]
                current=dict(enabled=enabled,revision=current['revision']+1,watermark=watermark)
                value['policies'][str(task)]=current
                for j in value['jobs'].values():
                    if j['task']==task and j['state'] in ('queued','fetching'):j.update(state='cancelled',reason='setting_changed')
        return self.status(task)

    def admit(self,task,listings):
        # Called only after import commit. No network and no research/goal calls.
        self.activate();added=0
        with state_edit(self.config) as value,source_db(self.config) as c:
            policy=value['policies'].get(str(task),dict(enabled=True,revision=0,watermark=value['watermark']))
            if not policy['enabled']:return 0
            for listing in list(dict.fromkeys(listings))[:200]:
                key=f'{task}:{listing}'
                if key in value['jobs']:continue
                first=c.execute('SELECT MIN(s.id) FROM listing_snapshots s JOIN task_runs t ON t.run_id=s.run_id WHERE t.task_id=? AND s.listing_id=?',(task,listing)).fetchone()[0]
                if first is None or first<=policy['watermark']:continue
                if len(value['jobs'])>=TRACKED_LIMIT or sum(j['state'] in ('queued','fetching') for j in value['jobs'].values())>=PENDING_LIMIT:
                    value['dropped']+=1;continue
                media=c.execute("SELECT id,source_url FROM media_assets WHERE listing_id=? AND media_type='product_image_url' ORDER BY id LIMIT 20",(listing,)).fetchall()
                selected=None
                for m in media:
                    try:checked_url(m['source_url'],ImageLimits());selected=m;break
                    except (ValueError,TypeError):continue
                if selected is None:continue  # No URL now; later detail import may supply it.
                value['jobs'][key]=dict(task=task,listing=listing,media=selected['id'],url=selected['source_url'],revision=policy['revision'],state='queued',attempts=0,created_at=self.clock())
                added+=1
        return added

    def status(self,task):
        policy=self.policy(task);value=load_state(self.config) or dict(jobs={},dropped=0)
        counts={s:sum(j['task']==task and j['state']==s for j in value['jobs'].values()) for s in ('queued','fetching','cached','failed','cancelled')}
        return dict(**policy,server_enabled=self.enabled(),counts=counts,queue_limit=PENDING_LIMIT,tracked_limit=TRACKED_LIMIT,dropped=value['dropped'],max_attempts=1,images_per_listing=1,notice='只处理功能生效后新入库商品；不补抓历史，不调用AI。研究暂停不影响封面缓存，监控暂停不会产生新采集。')

    def _authorize(self,job):
        if self.closed.is_set() or not self.enabled():raise ValueError('cover_worker_disabled')
        value=load_state(self.config);policy=self.policy(job['task'])
        current=value['jobs'].get(f"{job['task']}:{job['listing']}") if value else None
        if not policy['enabled'] or policy['revision']!=job['revision'] or not current or current['state']!='fetching':raise ValueError('cover_setting_changed')
        with source_db(self.config) as c:
            from shopping_agent.product_media import belongs
            belongs(c,job['task'],job['listing'])
            media=c.execute('SELECT listing_id,source_url FROM media_assets WHERE id=?',(job['media'],)).fetchone()
            if media is None or tuple(media)!=(job['listing'],job['url']):raise ValueError('cover_binding_changed')

    def step(self):
        if self.closed.is_set() or not self.enabled():return False
        value=load_state(self.config)
        if not value or not any(j['state']=='queued' for j in value['jobs'].values()):return False
        if self.clock()-value['last_request']<max(3.,self.config.safety.xianyu_min_delay_ms/1000):return False
        # Do not compete with collection, browser jobs or interactive operations.
        with source_db(self.config) as c:
            horizon=(datetime.now(timezone.utc)+timedelta(seconds=ImageLimits().total_seconds+3)).isoformat()
            if c.execute("SELECT 1 FROM monitors WHERE state='running' OR (state='waiting' AND (next_run_at IS NULL OR next_run_at<=?))",(horizon,)).fetchone():return False
            if any(c.execute(sql).fetchone() for sql in ["SELECT 1 FROM browser_jobs WHERE state IN ('queued','running')","SELECT 1 FROM operations WHERE state IN ('queued','running')"]):return False
        from shopping_agent.detail import browser_profile_lock
        from shopping_agent.safety import SafetyError
        try:
            with browser_profile_lock(self.config.browser_profile_dir,timeout_seconds=0,stale_after_seconds=float('inf')):
                return self._once()
        except SafetyError:return False

    def _once(self):
        with state_edit(self.config) as value:
            if value is None:return False
            delay=max(3.,self.config.safety.xianyu_min_delay_ms/1000)
            if self.clock()-value['last_request']<delay:return False
            job=next((j for j in value['jobs'].values() if j['state']=='queued' and value['policies'].get(str(j['task']),{'enabled':True})['enabled']),None)
            if job is None:return False
            job.update(state='fetching',attempts=1);value['last_request']=self.clock();job=dict(job)
        try:
            self._authorize(job)
            from shopping_agent.image_cache import prepare_cached_image
            result=prepare_cached_image(self.config,job['media'],job['listing'],job['url'],authorize=lambda:self._authorize(job),connection=lambda:source_db(self.config),resolver=self.resolver,transport=self.transport)
            update=dict(state='cached',sha256=result['sha256'],cache_reused=result['cache_reused'])
        except Exception:
            update=dict(state='failed',reason='cover_preparation_failed')
        with state_edit(self.config) as value:
            current=value['jobs'][f"{job['task']}:{job['listing']}"]
            if current['state']=='fetching':current.update(update)
        return True

    def start(self):
        if self.thread is not None:return
        self.activate()
        with state_edit(self.config) as value:
            for j in value['jobs'].values():
                if j['state']=='fetching':j.update(state='failed',reason='interrupted_no_retry')
        if self.thread is None:
            self.thread=threading.Thread(target=self._loop,name='product-cover-io',daemon=True);self.thread.start()

    def _loop(self):
        while not self.closed.wait(1):
            try:self.step()
            except Exception:logging.getLogger(__name__).warning('Cover cache worker deferred; existing import/research retained')

    def shutdown(self):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=55)
            if self.thread.is_alive():raise RuntimeError('封面图片工作进程尚未退出')
