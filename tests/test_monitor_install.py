import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import setup_monitor as setup
from shopping_agent.config import load_config
from shopping_agent.service_lease import ServiceLease


def local_engine(tmp_path, monkeypatch):
    upstream = tmp_path / 'upstream'
    upstream.mkdir()
    subprocess.run(['git', 'init', '--quiet', str(upstream)], check=True)
    (upstream / 'src').mkdir()
    (upstream / 'src/scraper.py').write_text('# synthetic engine\n')
    subprocess.run(['git', '-C', str(upstream), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(upstream), '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-qm', 'fixture'], check=True)
    revision = setup.git(upstream, 'rev-parse', 'HEAD')
    monkeypatch.setattr(setup, 'ENGINE_URL', str(upstream))
    monkeypatch.setattr(setup, 'SUPPORTED_REVISION', revision)
    return upstream, revision


def test_fetch_pins_revision_and_reuses_without_network(tmp_path, monkeypatch):
    _, revision = local_engine(tmp_path, monkeypatch)
    target = tmp_path / 'engine'
    setup.prepare_source(target)
    assert setup.git(target, 'rev-parse', 'HEAD') == revision
    monkeypatch.setattr(setup, 'run', lambda command, **kw: pytest.fail('must not fetch') if 'fetch' in command else subprocess.check_output(command, text=True).strip())
    setup.prepare_source(target)


def test_failed_fetch_resumes_owned_checkout(tmp_path, monkeypatch):
    local_engine(tmp_path, monkeypatch)
    target = tmp_path / 'engine'
    original = setup.run
    def fail(command, **kwargs):
        if 'fetch' in command:
            raise subprocess.CalledProcessError(1, command)
        return original(command, **kwargs)
    monkeypatch.setattr(setup, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        setup.prepare_source(target)
    assert not target.exists()
    monkeypatch.setattr(setup, 'run', original)
    setup.prepare_source(target)
    setup.validate_checkout(target)


@pytest.mark.parametrize('change', ['tracked', 'untracked', 'revision'])
def test_existing_changes_and_wrong_versions_are_preserved(tmp_path, monkeypatch, change):
    local_engine(tmp_path, monkeypatch)
    target = tmp_path / 'engine'
    setup.prepare_source(target)
    if change == 'tracked':
        (target / 'src/scraper.py').write_text('user work')
    elif change == 'untracked':
        (target / 'notes').write_text('user notes')
    else:
        monkeypatch.setattr(setup, 'SUPPORTED_REVISION', '0' * 40)
    before = {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file() and '.git' not in p.parts}
    with pytest.raises(setup.SetupError):
        setup.prepare_source(target)
    assert before == {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file() and '.git' not in p.parts}


def test_unknown_source_and_environment_are_not_overwritten(tmp_path):
    unknown = tmp_path / 'unknown'
    unknown.mkdir()
    (unknown / 'notes').write_text('keep')
    with pytest.raises(setup.SetupError):
        setup.prepare_source(unknown)
    with pytest.raises(setup.SetupError):
        setup.prepare_python(unknown)
    assert (unknown / 'notes').read_text() == 'keep'


def repository(tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/default.toml').write_text('database_path="data/test.sqlite"\n[monitor_engine]\nenabled=false\nroot="engine"\npython=".monitor-venv/Scripts/python.exe"\n')
    return tmp_path


def test_check_only_missing_source_is_read_only(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    before = sorted(str(p) for p in repo.rglob('*'))
    monkeypatch.setattr(setup, 'prepare_source', lambda *a: pytest.fail('must not install'))
    assert setup.main(['--check-only'], repository=repo) == 1
    assert before == sorted(str(p) for p in repo.rglob('*'))


def test_success_generates_config_and_repeat_preserves_user_settings(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    calls = []
    monkeypatch.setattr(setup, 'prepare_source', lambda root: calls.append(root))
    monkeypatch.setattr(setup, 'prepare_python', lambda directory: Path(sys.executable))
    monkeypatch.setattr(setup, 'run', lambda command, **kw: calls.append(command))
    monkeypatch.setattr(setup, 'check_monitor_environment', lambda cfg: {'ready': True, 'checks': []})
    assert setup.main([], repository=repo) == 0
    output = repo / 'config/monitor.local.toml'
    config = load_config(output)
    assert config.monitor_engine.enabled and config.monitor_engine.browser_channel == 'chromium'
    assert config.database_path == Path('data/test.sqlite')
    assert any(isinstance(c, list) and c[-2:] == ['install', 'chromium'] for c in calls)
    saved = output.read_bytes().replace(b'enabled = true', b'enabled = false')
    output.write_bytes(saved)
    assert setup.main([], repository=repo) == 0
    assert output.read_bytes() == saved


def test_failed_probe_does_not_publish_config(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    monkeypatch.setattr(setup, 'prepare_source', lambda root: None)
    monkeypatch.setattr(setup, 'prepare_python', lambda directory: None)
    monkeypatch.setattr(setup, 'run', lambda *a, **kw: None)
    monkeypatch.setattr(setup, 'check_monitor_environment', lambda cfg: {'ready': False, 'checks': [{'code': 'browser', 'ok': False}]})
    assert setup.main([], repository=repo) == 1
    assert not (repo / 'config/monitor.local.toml').exists()


def test_active_service_prevents_installation(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    monkeypatch.setattr(setup, 'prepare_source', lambda *a: pytest.fail('must not mutate active environment'))
    with ServiceLease(repo / 'data/test.sqlite'):
        assert setup.main([], repository=repo) == 1


def test_existing_config_is_never_replaced(tmp_path):
    output = tmp_path / 'existing.toml'
    output.write_bytes(b'user settings')
    setup.write_config(output, tmp_path / 'missing', tmp_path, Path(sys.executable), 'chromium')
    assert output.read_bytes() == b'user settings'


def test_legacy_browser_choice_is_not_replaced(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    output = repo / 'config/monitor.local.toml'
    output.write_bytes((repo / 'config/default.toml').read_bytes())
    observed = []
    monkeypatch.setattr(setup, 'check_monitor_environment', lambda cfg: observed.append(cfg.monitor_engine.browser_channel) or {'ready': False, 'checks': []})
    assert setup.main(['--check-only'], repository=repo) == 1
    assert observed == [None]


def test_browser_preparation_keeps_other_installations_cache(monkeypatch):
    commands = []
    def process(command, **kwargs):
        commands.append(command)
        assert kwargs['env']['PLAYWRIGHT_SKIP_BROWSER_GC'] == '1'
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(setup.subprocess, 'run', process)
    setup.run(['python', '-m', 'playwright', 'install', 'chromium'])
    assert len(commands) == 1


def test_interrupted_owned_environment_creation_can_resume(tmp_path, monkeypatch):
    directory = tmp_path / 'venv'
    count = []
    def create(self, target):
        count.append(True)
        target.mkdir(exist_ok=True)
        if len(count) == 1:
            raise OSError('interrupted')
        python = target / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        python.parent.mkdir()
        python.write_bytes(b'fixture')
        (target / 'pyvenv.cfg').write_text('fixture')
    monkeypatch.setattr(setup.venv.EnvBuilder, 'create', create)
    monkeypatch.setattr(setup, 'run', lambda *a, **kw: json.dumps(list(sys.version_info[:2])))
    with pytest.raises(OSError):
        setup.prepare_python(directory)
    assert setup.prepare_python(directory).is_file()
    assert len(count) == 2
