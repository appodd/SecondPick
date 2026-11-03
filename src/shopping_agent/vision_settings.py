"""Non-secret configuration and OS-protected credentials, with legacy compatibility.

No environment lookup, credential-file import, network check or research trigger.
"""
import json
import os
from pathlib import Path
import tempfile
import threading

from pydantic import BaseModel, ConfigDict, Field


class VisionSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool = False
    provider: str = 'deepseek'
    model: str = Field(default='deepseek-flash', min_length=1, max_length=120, pattern=r'^[A-Za-z0-9._:-]+$')
    timeout_seconds: int = Field(default=300, ge=1, le=300)
    max_output_tokens: int = Field(default=3000, ge=128, le=4000)


class VisionSettingsStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.lock = threading.RLock()
        self._memory = {}
        from shopping_agent.vision_profiles import VisionProfiles
        self.profiles = VisionProfiles(self)

    def target(self, name):
        if self.directory.is_symlink():
            raise ValueError('视觉配置目录不可为符号链接')
        path = self.directory / name
        if path.is_symlink():
            raise ValueError('视觉配置文件不可为符号链接')
        return path

    def _legacy_read(self):
        with self.lock:
            path = self.target('vision-model.json')
            return VisionSettings.model_validate_json(path.read_text('utf-8')) if path.exists() else VisionSettings()

    def read(self):
        return self.profiles.effective()

    def _write(self, path, data):
        self.directory.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix='.vision-', delete=False) as stream:
                name = Path(stream.name)
                os.chmod(name, 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if name is not None and name.exists():
                name.unlink()

    def save(self, settings):
        from shopping_agent.vision import provider_for
        provider_for(settings.provider)  # Registry IDs only; no user-selected URL.
        with self.lock:
            if self.profiles.path.exists():
                raise ValueError('请使用多配置管理接口修改模型')
            self._write(self.target('vision-model.json'), settings.model_dump_json(indent=2).encode())

    def key_path(self, provider):
        from shopping_agent.vision import provider_for
        provider_for(provider)
        return self.target('vision-' + provider + '.dpapi')

    def _legacy_has_key(self, provider):
        with self.lock:
            return provider in self._memory or self.key_path(provider).is_file()

    def has_key(self, provider):
        with self.lock:
            d = self.profiles.document()
            p = next((p for p in d['profiles'] if p['id'] == d['current_id']), None)
            return bool(p and p['config']['provider'] == provider and self.profiles.key_present(p))

    def set_key(self, provider, value):
        if self.profiles.path.exists():
            raise ValueError('请在指定模型配置中更新密钥')
        # No key value appears in any validation message or model dump.
        if not isinstance(value, str) or not 8 <= len(value) <= 4096 or any(c.isspace() for c in value):
            raise ValueError('密钥格式不符合本地要求')
        with self.lock:
            path = self.key_path(provider)
            if os.name == 'nt':
                from shopping_agent.browser.auth_state import _protect
                encrypted = _protect(json.dumps({'provider': provider, 'key': value}).encode())
                self._write(path, encrypted)
            else:
                self._memory[provider] = value

    def clear_key(self, provider):
        if self.profiles.path.exists():
            raise ValueError('请在指定模型配置中移除密钥')
        with self.lock:
            self._memory.pop(provider, None)
            self.key_path(provider).unlink(missing_ok=True)

    def _legacy_credential(self, provider):
        """Explicit future execution only. Settings/check endpoints never decrypt."""
        with self.lock:
            if provider in self._memory:
                return self._memory[provider]
            if os.name != 'nt':
                raise ValueError('未配置视觉密钥')
            try:
                from shopping_agent.browser.auth_state import _protect
                value = json.loads(_protect(self.key_path(provider).read_bytes(), decrypt=True))
                if value['provider'] != provider:
                    raise ValueError
                return value['key']
            except Exception:
                raise ValueError('无法读取受保护的视觉密钥，请重新配置') from None

    def credential(self, provider, *, expected=None):
        return self.profiles.credential(provider, expected)

    def status(self, *, checked=False):
        from shopping_agent.vision import provider_for, provider_catalog
        settings = self.read()
        adapter = provider_for(settings.provider)
        key_present = self.has_key(settings.provider)
        capable = adapter.supports(settings.model)
        complete = key_present and capable
        catalog = self.profiles.document()
        current = next((p for p in catalog['profiles'] if p['id'] == catalog['current_id']), None)
        verified = bool(current and current.get('verification', {}).get('state') == 'verified'
                        and current['verification'].get('revision') == current['revision'])
        state = ('disabled' if not settings.enabled else
                 'not_configured' if not key_present else
                 'incomplete' if not complete else
                 'verified' if verified else 'local_checked' if checked else 'saved_unverified')
        return dict(settings=settings.model_dump(include=set(VisionSettings.model_fields)), state=state, key_configured=key_present,
                    storage='windows_dpapi' if os.name == 'nt' else 'memory_until_restart',
                    endpoint=adapter.endpoint, capability_declared=capable,
                    connection_verified=verified, providers=provider_catalog(),
                    local_check=dict(passed=complete, network_used=False) if checked else None)
