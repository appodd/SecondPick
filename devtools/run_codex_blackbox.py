from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def resolve_codex_bin(codex_bin: str) -> str:
    if os.name == "nt" and Path(codex_bin).name == codex_bin and not Path(codex_bin).suffix:
        return shutil.which(f"{codex_bin}.cmd") or codex_bin
    return codex_bin


def build_codex_command(
    codex_bin: str,
    project_root: Path,
    last_message_path: Path,
    session_id: Optional[str],
    model: str,
    sandbox_mode: str = "workspace-write",
) -> list[str]:
    sandbox_args = ["-s", sandbox_mode]
    if session_id:
        return [
            codex_bin,
            "exec",
            *sandbox_args,
            "resume",
            "-m",
            model,
            "--json",
            "-o",
            str(last_message_path),
            session_id,
            "-",
        ]
    return [
        codex_bin,
        "exec",
        *sandbox_args,
        "-m",
        model,
        "--json",
        "-C",
        str(project_root),
        "-o",
        str(last_message_path),
        "-",
    ]


def run_codex_prompt(
    prompt_path: Path,
    events_path: Path,
    stderr_path: Path,
    last_message_path: Path,
    project_root: Path,
    model: str,
    codex_bin: str = "codex",
    session_id: Optional[str] = None,
    timeout_seconds: int = 300,
    sandbox_mode: str = "workspace-write",
    metadata_path: Path | None = None,
) -> int:
    prompt = prompt_path.read_text(encoding="utf-8")
    events_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    last_message_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_codex_command(
        resolve_codex_bin(codex_bin),
        project_root.resolve(),
        last_message_path.resolve(),
        session_id,
        model,
        sandbox_mode,
    )
    metadata_path = metadata_path or events_path.with_name(
        f"{events_path.stem}.metadata.json"
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(
            {
                "model": model,
                "sandbox_mode": sandbox_mode,
                "timeout_seconds": timeout_seconds,
                "project_root": str(project_root.resolve()),
                "session_id": session_id,
                "command": command,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str((project_root / "src").resolve()), str(project_root.resolve()))
    )
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    with events_path.open("w", encoding="utf-8", newline="\n") as events_file:
        with stderr_path.open("w", encoding="utf-8", newline="\n") as stderr_file:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=events_file,
                stderr=stderr_file,
                cwd=project_root,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            try:
                process.communicate(input=prompt, timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process.pid)
                process.wait(timeout=10)
                stderr_file.write(f"\nCodex black-box runner timed out after {timeout_seconds} seconds.\n")
                return 124
    return process.returncode


def _terminate_process_tree(process_id: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process_id), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    os.kill(process_id, 15)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--stderr", type=Path, required=True)
    parser.add_argument("--last-message", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--model", required=True)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument(
        "--sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="workspace-write",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_codex_prompt(
        args.prompt,
        args.events,
        args.stderr,
        args.last_message,
        args.cwd,
        model=args.model,
        codex_bin=args.codex_bin,
        session_id=args.session_id,
        timeout_seconds=args.timeout_seconds,
        sandbox_mode=args.sandbox,
        metadata_path=args.metadata,
    )


if __name__ == "__main__":
    raise SystemExit(main())
