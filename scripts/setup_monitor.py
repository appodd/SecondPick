"""Prepare the pinned collection runtime without login, collection or model calls."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import venv

from shopping_agent.config import load_config
from shopping_agent.monitor_engine import SUPPORTED_REVISION
from shopping_agent.monitor_environment import check_monitor_environment
from shopping_agent.service_lease import ServiceLease

ENGINE_URL = 'https://github.com/Usagi-org/ai-goofish-monitor.git'


class SetupError(RuntimeError):
    pass


def linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def run(command, *, cwd=None, capture=False):
    environment = dict(os.environ, PLAYWRIGHT_SKIP_BROWSER_GC='1')
    result = subprocess.run(command, cwd=cwd, check=True, text=True, encoding='utf-8', errors='replace',
                            stdout=subprocess.PIPE if capture else None, env=environment)
    return result.stdout.strip() if capture else None


def git(root, *args):
    return run(['git', '-C', str(root), *args], capture=True)


def validate_checkout(root):
    if linked(root) or not root.is_dir() or not (root / '.git').exists():
        raise SetupError(f'Unknown engine directory: {root}. Preserve it and choose a new --root.')
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root.resolve():
        raise SetupError('Engine path is not an independent checkout; nothing overwritten.')
    if git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise SetupError(f'Engine has local changes or untracked files: {root}. Preserve them; use a new --root.')
    if git(root, 'rev-parse', 'HEAD') != SUPPORTED_REVISION:
        raise SetupError(f'Engine revision mismatch. Required {SUPPORTED_REVISION}. Existing checkout unchanged; use a new --root or review it manually.')


def prepare_source(root):
    if root.exists() or linked(root):
        validate_checkout(root)
        return
    # Publish only a complete checkout. Failed fetches leave owned staging data.
    stage = root.with_name(root.name + '.secondpick-install')
    manifest = dict(url=ENGINE_URL, revision=SUPPORTED_REVISION, target=str(root))
    if linked(stage):
        raise SetupError(f'Unsafe staging directory: {stage}')
    marker = stage / 'owner.json'
    if stage.exists():
        if not marker.is_file() or marker.is_symlink() or json.loads(marker.read_text('utf-8')) != manifest:
            raise SetupError(f'Unknown staging contents: {stage}; preserve them and choose a new --root.')
        if set(p.name for p in stage.iterdir()) - {'owner.json', 'checkout'}:
            raise SetupError(f'Unexpected staging data: {stage}')
    else:
        stage.mkdir(parents=True)
        marker.write_text(json.dumps(manifest), encoding='utf-8')
    checkout = stage / 'checkout'
    if linked(checkout):
        raise SetupError('Staging checkout must not be a link.')
    if not checkout.exists():
        checkout.mkdir()
    if not (checkout / '.git').exists():
        if any(checkout.iterdir()):
            raise SetupError('Incomplete checkout contains unknown files; nothing overwritten.')
        run(['git', 'init', '--quiet', str(checkout)])
    if git(checkout, 'status', '--porcelain', '--untracked-files=all'):
        raise SetupError('Staged engine has local changes; nothing overwritten.')
    run(['git', '-C', str(checkout), 'fetch', '--depth', '1', ENGINE_URL, SUPPORTED_REVISION])
    run(['git', '-C', str(checkout), 'checkout', '--detach', SUPPORTED_REVISION])
    validate_checkout(checkout)
    checkout.rename(root)
    # Retain the small ownership marker for audit/retry; no recursive deletion.


def prepare_python(directory):
    if directory.resolve() == Path(sys.prefix).resolve():
        raise SetupError('Choose a separate --venv; the application environment must remain unchanged.')
    if linked(directory):
        raise SetupError('Refusing to modify a linked environment.')
    owner = directory.with_name(directory.name + '.secondpick-owner.json')
    owned = owner.is_file() and not linked(owner) and json.loads(owner.read_text('utf-8')) == {'target': str(directory)}
    if directory.exists() and not (directory / 'pyvenv.cfg').is_file() and not owned:
        raise SetupError(f'Unknown environment directory: {directory}; choose a new --venv.')
    python = directory / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not directory.exists() or owned and not python.is_file():
        if directory.exists() and set(p.name for p in directory.iterdir()) - {'Scripts', 'bin', 'Lib', 'lib', 'lib64', 'Include', 'include', 'pyvenv.cfg', '.gitignore'}:
            raise SetupError('Interrupted environment contains unknown files; choose a new --venv.')
        if not owner.exists():
            owner.parent.mkdir(parents=True, exist_ok=True)
            with owner.open('x', encoding='utf-8') as stream:
                json.dump({'target': str(directory)}, stream)
        venv.EnvBuilder(with_pip=True).create(directory)
    if not python.is_file():
        raise SetupError('Incomplete environment: interpreter missing. Preserve it and choose a new --venv.')
    version = json.loads(run([str(python), '-c', 'import json,sys; print(json.dumps(list(sys.version_info[:2])))'], capture=True))
    if version != list(sys.version_info[:2]):
        raise SetupError('Existing environment uses another Python version; preserve it and choose a new --venv.')
    return python


def write_config(output, source, root, python, channel):
    if output.exists():
        return
    text = source.read_text('utf-8')
    prefix, monitor = text.split('[monitor_engine]', 1)
    for name, value in {'enabled': 'true', 'root': json.dumps(root.as_posix(), ensure_ascii=False),
                        'python': json.dumps(python.as_posix(), ensure_ascii=False), 'browser_channel': json.dumps(channel)}.items():
        pattern = rf'(?m)^{name}\s*=.*$'
        monitor = re.sub(pattern, lambda _: f'{name} = {value}', monitor) if re.search(pattern, monitor) else monitor + f'\n{name} = {value}\n'
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.monitor-config-', dir=output.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(prefix + '[monitor_engine]' + monitor)
        os.link(temporary, output)  # Atomic exclusive publication; never replace.
    finally:
        Path(temporary).unlink()


def main(argv=None, *, repository=None):
    repository = Path(repository or Path(__file__).resolve().parents[1]).resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, help='Alternative checkout; existing directories are never reset')
    parser.add_argument('--venv', type=Path, help='Alternative isolated Python environment')
    parser.add_argument('--config', type=Path, default=repository / 'config/monitor.local.toml')
    parser.add_argument('--check-only', action='store_true', help='Check existing paths without installing or writing configuration')
    args = parser.parse_args(argv)
    stage = 'prerequisites'
    try:
        if sys.version_info < (3, 11):
            raise SetupError('Use Python 3.11+, preferably Windows Python 3.12.')
        if shutil.which('git') is None:
            raise SetupError('Git is required. Install Git, reopen the terminal, and retry.')
        output = args.config.absolute()
        if linked(output):
            raise SetupError('Refusing a linked configuration file.')
        config = load_config(output if output.exists() else repository / 'config/default.toml')
        cfg = config.monitor_engine
        def absolute(value):
            path = Path(value)
            return (repository / path).absolute() if not path.is_absolute() else path
        root = absolute(args.root or cfg.root or 'data/research/ai-goofish-monitor')
        directory = absolute(args.venv or (Path(cfg.python).parent.parent if cfg.python else '.monitor-venv'))
        python = directory / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        for target in (root, directory, output):
            if any(linked(path) for path in (target, *target.parents)):
                raise SetupError(f'Linked installation paths are not modified: {target}')
        channel = cfg.browser_channel if output.exists() else cfg.browser_channel or 'chromium'
        if output.exists() and (cfg.root is None or cfg.python is None or root != absolute(cfg.root) or python != absolute(cfg.python)):
            raise SetupError('Paths differ from existing configuration. Use a new --config; existing configuration is preserved.')
        probe = config.model_copy(update={'monitor_engine': cfg.model_copy(update={
            'root': root, 'python': python, 'browser_channel': channel})})
        if args.check_only:
            result = check_monitor_environment(probe)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['ready'] else 1
        stage = 'service and installation locks (stop the workbench before repair)'
        with ServiceLease(absolute(config.database_path)), ServiceLease(root.with_name('.secondpick-monitor-setup')), ServiceLease(directory.with_name(directory.name + '.setup')):
            stage = 'engine source'
            print(f'[{stage}] Required revision: {SUPPORTED_REVISION}', flush=True)
            prepare_source(root)
            stage = 'isolated Python'
            print(f'[{stage}] {directory}', flush=True)
            python = prepare_python(directory)
            stage = 'dependencies'
            print(f'[{stage}] Installing pinned runtime dependencies', flush=True)
            requirements = 'monitor-engine-windows-py312.lock.txt' if sys.platform == 'win32' and sys.version_info[:2] == (3, 12) else 'monitor-engine.txt'
            run([str(python), '-m', 'ensurepip', '--upgrade'])
            run([str(python), '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check', '--only-binary=:all:',
                 '--index-url', 'https://pypi.org/simple', '-r', str(repository / 'requirements' / requirements)])
            run([str(python), '-m', 'pip', 'check'])
            stage = 'browser'
            print(f'[{stage}] Preparing user-level Chromium; no system browser installation', flush=True)
            run([str(python), '-m', 'playwright', 'install', 'chromium'])
            run([sys.executable, '-m', 'playwright', 'install', 'chromium'])
            stage = 'environment check'
            result = check_monitor_environment(probe)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if not result['ready']:
                raise SetupError('Failed checks: ' + ', '.join(c['code'] for c in result['checks'] if not c['ok']) + '. Configuration unchanged; correct the condition and rerun.')
            stage = 'configuration'
            write_config(output, repository / 'config/default.toml', root, python, channel)
            print(f'Ready: {output}. Existing configuration preserved. No login, collection or research started.')
            print('Start from the repository root: shopping-agent-web' if output == repository / 'config/monitor.local.toml' else f'Start with explicit configuration: shopping-agent-web --config "{output}"')
            if not load_config(output).monitor_engine.enabled:
                print('Monitoring remains explicitly disabled in the existing configuration.')
        return 0
    except (SetupError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Installation failed [{stage}]: {error}', file=sys.stderr)
        print('Preserve existing data. Correct the reported condition and rerun this command.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
