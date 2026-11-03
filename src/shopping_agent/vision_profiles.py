"""Multiple configurations inside the existing vision store; no research jobs or DDL."""
import copy
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

from shopping_agent.vision_settings import VisionSettings


class ProfileError(ValueError):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class EffectiveVisionSettings(VisionSettings):
    profile_id: str | None = None
    profile_revision: int = 0


def now():
    return datetime.now(timezone.utc).isoformat()


def configuration(value):
    from shopping_agent.vision import provider_for
    model = VisionSettings.model_validate(dict(value, enabled=False))
    provider_for(model.provider)
    return model.model_dump(exclude={'enabled'})


def validate_key(key):
    if not isinstance(key, str) or not 8 <= len(key) <= 4096 or any(c.isspace() for c in key):
        raise ProfileError('invalid_key', '密钥格式不符合本地要求。', 400)


class VisionProfiles:
    def __init__(self, store):
        self.store = store
        self.busy = None

    @property
    def path(self):
        return self.store.target('vision-profiles.json')

    def document(self):
        if self.path.exists():
            d = json.loads(self.path.read_text('utf-8'))
            if d.get('version') != 1 or not isinstance(d.get('profiles'), list):
                raise ProfileError('invalid_catalog', '无法读取视觉配置索引，请恢复配置备份。')
            return d
        old = self.store._legacy_read()
        exists = self.store.target('vision-model.json').exists() or self.store._legacy_has_key(old.provider)
        profiles = []
        if exists:
            profiles.append(dict(id='legacy-default', revision=1, config=old.model_dump(exclude={'enabled'}),
                key_ref='legacy:'+old.provider if self.store._legacy_has_key(old.provider) else None,
                verification=dict(state='unverified', checked_at=None), imported=True))
        # Preserve parameters and ciphertext, but never infer a verified connection
        # from the old optional enabled flag. Explicit re-enable must validate.
        return dict(version=1, revision=0, enabled=False, current_id='legacy-default' if profiles else None,
                    profiles=profiles, used_requests=[], operation=None, legacy_enabled=old.enabled)

    def find(self, d, ident):
        item = next((p for p in d['profiles'] if p['id'] == ident), None)
        if item is None:
            raise ProfileError('profile_missing', '该模型配置已不存在，请刷新列表。', 404)
        return item

    def write(self, d):
        self.store._write(self.path, json.dumps(d, ensure_ascii=False, indent=2).encode())

    def key_present(self, p):
        ref = p.get('key_ref')
        if not ref:
            return False
        if ref.startswith('legacy:'):
            return self.store._legacy_has_key(ref.split(':', 1)[1])
        return ref in self.store._memory or self.store.target(ref).is_file()

    def secret(self, p):
        ref = p.get('key_ref')
        if not self.key_present(p):
            raise ProfileError('key_missing', '缺少该配置的密钥，请修改配置。', 400)
        if ref.startswith('legacy:'):
            return self.store._legacy_credential(p['config']['provider'])
        if ref in self.store._memory:
            return self.store._memory[ref]
        try:
            from shopping_agent.browser.auth_state import _protect
            data = json.loads(_protect(self.store.target(ref).read_bytes(), decrypt=True))
            if data['provider'] != p['config']['provider']:
                raise ValueError
            return data['key']
        except Exception:
            raise ProfileError('key_unreadable', '无法读取此配置的安全密钥，请重新填写。', 400) from None

    def new_secret(self, provider, key):
        validate_key(key)
        ref = 'vision-profile-'+uuid.uuid4().hex+'.dpapi'
        if os.name == 'nt':
            from shopping_agent.browser.auth_state import _protect
            self.store._write(self.store.target(ref), _protect(json.dumps(dict(provider=provider, key=key)).encode()))
        else:
            self.store._memory[ref] = key
        return ref

    def discard(self, ref):
        # Legacy ciphertext is never copied, decrypted for migration, or removed
        # as an incidental cleanup; it remains available for legacy rollback.
        if ref and re.fullmatch(r'vision-profile-[0-9a-f]{32}\.dpapi', ref):
            if any(p.get('key_ref') == ref for p in self.document()['profiles']):
                return
            self.store._memory.pop(ref, None)
            self.store.target(ref).unlink(missing_ok=True)

    def effective(self):
        with self.store.lock:
            d = self.document()
            p = next((p for p in d['profiles'] if p['id'] == d['current_id']), None)
            if p is None:
                return EffectiveVisionSettings(enabled=False)
            valid = p.get('verification', {}).get('state') == 'verified' and p['verification'].get('revision') == p['revision']
            return EffectiveVisionSettings(**p['config'], enabled=bool(d['enabled'] and valid and self.key_present(p)),
                                          profile_id=p['id'], profile_revision=p['revision'])

    def status(self):
        from shopping_agent.vision import provider_for, provider_catalog
        with self.store.lock:
            d = self.document()
            items = []
            for p in d['profiles']:
                verification = copy.deepcopy(p.get('verification') or dict(state='unverified', checked_at=None))
                if self.busy and self.busy['target'] == p['id'] and (d.get('operation') or {}).get('state') == 'running':
                    verification = dict(verification, state='verifying')
                items.append(dict(id=p['id'], revision=p['revision'], **p['config'],
                    key_configured=self.key_present(p), current=p['id'] == d['current_id'],
                    capability_declared=provider_for(p['config']['provider']).supports(p['config']['model']),
                    verification=verification, imported=p.get('imported', False)))
            operation = copy.deepcopy(d.get('operation'))
            if operation and operation['state'] == 'running' and not self.busy:
                operation['state'] = 'interrupted'  # No implicit replay after restart.
            return dict(revision=d['revision'], enabled=self.effective().enabled, current_id=d['current_id'],
                profiles=items, providers=provider_catalog(), operation=operation,
                storage='windows_dpapi' if os.name == 'nt' else 'memory_until_restart',
                legacy_requires_verification=bool(d.get('legacy_enabled') and not self.effective().enabled))

    def begin(self, expected, request_key, kind, ident):
        with self.store.lock:
            d = self.document()
            if type(expected) is not int or expected != d['revision']:
                raise ProfileError('revision_changed', '配置已发生变化，请刷新后重新操作。')
            if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', request_key):
                raise ProfileError('invalid_request', '缺少有效的单次操作标识。', 400)
            if request_key in d['used_requests']:
                raise ProfileError('request_used', '本次操作已提交，不会重复执行。请刷新状态。')
            if self.busy:
                raise ProfileError('operation_busy', '另一项配置操作正在进行，请稍后再试。')
            token = dict(id=uuid.uuid4().hex, kind=kind, target=ident, state='running', started_at=now())
            d['revision'] += 1
            d['used_requests'] = (d['used_requests']+[request_key])[-256:]
            d['operation'] = token
            self.write(d)  # Durable reservation before reading credentials/network.
            self.busy = token
            return copy.deepcopy(d), token

    def commit(self, base, token, update, *, error=None):
        with self.store.lock:
            current = self.document()
            if current['revision'] != base['revision'] or (current.get('operation') or {}).get('id') != token['id']:
                raise ProfileError('operation_superseded', '本次操作已失效；保留最新配置，不会自动重试。')
            update(current)
            current['revision'] += 1
            current['operation'] = dict(token, state='failed' if error else 'completed', finished_at=now(), error=error)
            self.write(current)

    async def checked(self, profile, validator):
        from shopping_agent.vision import provider_for
        if not self.key_present(profile):
            return dict(state='failed', revision=profile['revision'], checked_at=now(), reason='missing_key', message='缺少密钥，请修改配置后重试。')
        if not provider_for(profile['config']['provider']).supports(profile['config']['model']):
            return dict(state='failed', revision=profile['revision'], checked_at=now(), reason='unsupported_model', message='此模型尚无图片输入适配支持，请选择已支持的模型。')
        try:
            result = await validator(profile['config'], self.secret(profile))
            if result.get('state') != 'verified':
                raise ValueError
            return dict(result, revision=profile['revision'], checked_at=now())
        except ProfileError as exc:
            return dict(state='failed', revision=profile['revision'], checked_at=now(), reason=exc.code, message=exc.message)
        except Exception:
            return dict(state='failed', revision=profile['revision'], checked_at=now(), reason='verification_failed', message='连接验证未通过，请检查模型、密钥与服务状态。')

    async def upsert(self, value, key, expected, request_key, validator, ident=None):
        cfg = configuration(value)
        if key not in (None, ''):
            validate_key(key)
        base, token = self.begin(expected, request_key, 'edit' if ident else 'add', ident)
        staged = None
        try:
            old = self.find(base, ident) if ident else None
            if (not old or old['config']['provider'] != cfg['provider'] or not self.key_present(old)) and not key:
                raise ProfileError('key_required', '添加配置或更换服务商时必须填写 API Key。', 400)
            ref = old.get('key_ref') if old else None
            if key:
                ref = staged = self.new_secret(cfg['provider'], key)
            candidate = dict(id=ident or uuid.uuid4().hex, revision=(old['revision']+1 if old else 1),
                config=cfg, key_ref=ref, verification=dict(state='unverified', checked_at=None))
            if old and old['config'] == cfg and not key:
                candidate = copy.deepcopy(old)
            if old and base['enabled'] and base['current_id'] == ident and candidate != old:
                candidate['verification'] = await self.checked(candidate, validator)
                if candidate['verification']['state'] != 'verified':
                    raise ProfileError(candidate['verification']['reason'], candidate['verification']['message'], 400)
            def update(d):
                d['profiles'] = [candidate if p['id'] == ident else p for p in d['profiles']] if old else d['profiles']+[candidate]
                if d['current_id'] is None:
                    d['current_id'] = candidate['id']  # First configuration, never auto-enable.
            self.commit(base, token, update)
            if old and old.get('key_ref') != ref:
                self.discard(old.get('key_ref'))
            return self.status()
        except Exception as exc:
            try:
                self.commit(base, token, lambda d: None, error=exc.code if isinstance(exc, ProfileError) else 'save_failed')
            except ProfileError:
                pass
            if isinstance(exc, ProfileError):
                raise
            raise ProfileError('save_failed', '无法安全保存配置，原有配置保持不变。', 400) from None
        finally:
            with self.store.lock:
                if self.busy and self.busy['id'] == token['id']:
                    self.busy = None
                self.discard(staged)

    async def action(self, kind, ident, expected, request_key, validator):
        base, token = self.begin(expected, request_key, kind, ident)
        try:
            p = self.find(base, ident)
            if kind == 'enable' and ident != base['current_id']:
                raise ProfileError('current_changed', '当前模型已变化，请重新核对。')
            verification = None
            if kind in ('enable', 'verify') or kind == 'select' and base['enabled']:
                verification = await self.checked(p, validator)
            def update(d):
                if verification is not None:
                    self.find(d, ident)['verification'] = verification
                if verification and verification['state'] != 'verified':
                    if kind == 'enable' or kind == 'verify' and d['current_id'] == ident:
                        d['enabled'] = False
                    return
                if kind == 'enable':
                    d['enabled'] = True
                elif kind == 'select':
                    d['current_id'] = ident
            failed = verification is not None and verification['state'] != 'verified'
            self.commit(base, token, update, error=verification['reason'] if failed else None)
            if failed:
                raise ProfileError(verification['reason'], verification['message'], 400)
        except Exception as exc:
            # Also persist failures before a transport was possible, without retry.
            try:
                self.commit(base, token, lambda d: None, error=exc.code if isinstance(exc, ProfileError) else 'operation_failed')
            except ProfileError:
                pass
            raise
        finally:
            with self.store.lock:
                if self.busy and self.busy['id'] == token['id']:
                    self.busy = None
        return self.status()

    def disable(self, expected):
        with self.store.lock:
            d = self.document()
            if type(expected) is not int or expected != d['revision']:
                raise ProfileError('revision_changed', '配置已发生变化，请刷新后再关闭。')
            d['enabled'] = False
            d['revision'] += 1
            d['operation'] = dict(id=uuid.uuid4().hex, kind='disable', state='completed', finished_at=now())
            self.write(d)  # Invalidates any in-flight enable/select/edit commit.
            return self.status()

    def delete(self, ident, expected, request_key, confirmed):
        if confirmed is not True:
            raise ProfileError('confirmation_required', '请明确确认删除此配置。', 400)
        base, token = self.begin(expected, request_key, 'delete', ident)
        try:
            p = self.find(base, ident)
            if base['current_id'] == ident and base['enabled']:
                raise ProfileError('current_enabled', '请先关闭视觉研究或切换当前模型，再删除此配置。')
            def update(d):
                d['profiles'] = [p for p in d['profiles'] if p['id'] != ident]
                if d['current_id'] == ident:
                    d.update(current_id=None, enabled=False)
            self.commit(base, token, update)
            self.discard(p.get('key_ref'))
        except ProfileError as exc:
            try:
                self.commit(base, token, lambda d: None, error=exc.code)
            except ProfileError:
                pass
            raise
        finally:
            self.busy = None
        return self.status()

    def credential(self, provider, expected=None):
        with self.store.lock:
            config = self.effective()
            if expected is not None and config != expected:
                raise ProfileError('configuration_changed', '当前模型配置已改变，请重新确认研究范围。')
            d = self.document()
            p = self.find(d, d['current_id'])
            if p['config']['provider'] != provider:
                raise ProfileError('provider_changed', '当前服务商与已批准范围不一致。')
            return self.secret(p)
