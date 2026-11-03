"""Prepare a dedicated interpreter; never enables or starts platform collection."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import venv


def main():
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", type=Path, default=repository / ".monitor-venv")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise SystemExit("Monitoring setup requires Python 3.11 or newer.")
    directory = args.venv.resolve()
    if directory == Path(sys.prefix).resolve():
        raise SystemExit("Choose a separate virtual environment; current interpreter is unchanged.")
    python = directory / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if directory.exists() and not (directory / "pyvenv.cfg").is_file():
        raise SystemExit("Target exists and is not a virtual environment; nothing changed.")
    if not args.check_only:
        if not directory.exists():
            venv.EnvBuilder(with_pip=True).create(directory)
        requirements = "monitor-engine-windows-py312.lock.txt" if sys.platform == "win32" and sys.version_info[:2] == (3, 12) else "monitor-engine.txt"
        subprocess.run([str(python), "-m", "pip", "--isolated", "install", "--disable-pip-version-check", "--only-binary=:all:",
            "--index-url", "https://pypi.org/simple", "-r", str(repository / "requirements" / requirements)], check=True)
        # System Chrome is used by the pinned native runtime; no browser profile
        # or credentials are copied, and no extra browser download is necessary.
        frozen = subprocess.run([str(python), "-m", "pip", "freeze"], capture_output=True, text=True, check=True)
        (directory / "installed-packages.txt").write_text(frozen.stdout, encoding="utf-8")
    if not python.is_file():
        raise SystemExit("Dedicated interpreter is missing; run setup without --check-only.")
    result = subprocess.run([sys.executable, "-X", "utf8", "-m", "shopping_agent.monitor_environment", "--root",
        str(repository / "data/research/ai-goofish-monitor"), "--python", str(python)], cwd=repository).returncode
    if result == 0 and not args.check_only:
        output = repository / "config/monitor.local.toml"
        if not output.exists():
            source = (repository / "config/default.toml").read_text(encoding="utf-8")
            prefix, monitor = source.split("[monitor_engine]", 1)
            monitor = re.sub(r"(?m)^python\s*=.*$", "python = " + json.dumps(python.as_posix(), ensure_ascii=False), monitor)
            # Local configuration only; it is not loaded by the default launcher.
            with output.open("x", encoding="utf-8") as stream:
                stream.write(prefix + "[monitor_engine]" + monitor.replace("enabled = false", "enabled = true", 1))
        print("Local configuration ready: config/monitor.local.toml; no service or collection started.")
    return result


if __name__ == "__main__":
    sys.exit(main())
