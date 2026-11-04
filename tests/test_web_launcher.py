from pathlib import Path

import pytest

from shopping_agent.web import cli


@pytest.mark.parametrize('local,explicit,expected', [
    (False, None, 'config/default.toml'),
    (True, None, 'config/monitor.local.toml'),
    (True, 'custom.toml', 'custom.toml'),
    (True, 'config/default.toml', 'config/default.toml'),
])
def test_launcher_configuration_precedence(tmp_path, monkeypatch, local, explicit, expected):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'config').mkdir()
    for name in ['config/default.toml', 'custom.toml'] + (['config/monitor.local.toml'] if local else []):
        Path(name).write_text('')
    used = []
    monkeypatch.setattr(cli, 'create_app', lambda config, settings: used.append(config))
    monkeypatch.setattr(cli.uvicorn, 'run', lambda *a, **kw: None)
    cli.main(['--config', explicit] if explicit else [])
    assert used == [Path(expected)]


def test_explicit_missing_configuration_cannot_fall_back(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, 'create_app', lambda *a: pytest.fail('must not start with defaults'))
    with pytest.raises(SystemExit):
        cli.main(['--config', 'missing.toml'])
