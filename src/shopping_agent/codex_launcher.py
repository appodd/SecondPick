from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodexLaunchPlan:
    command: list[str]
    prompt: str
    prompt_path: Path | None = None


def build_codex_launch_plan(
    project_root: Path,
    goal: str | None = None,
    listing_id: int | None = None,
    codex_bin: str = "codex",
    enable_search: bool = True,
    city: str | None = None,
    platforms: list[str] | None = None,
    codex_args: list[str] | None = None,
) -> CodexLaunchPlan:
    prompt = build_shopping_codex_prompt(
        goal=goal,
        listing_id=listing_id,
        city=city,
        platforms=platforms,
    )
    command = [codex_bin, "-C", str(project_root)]
    if enable_search:
        command.append("--search")
    command.extend(codex_args or [])
    command.append(prompt)
    return CodexLaunchPlan(command=command, prompt=prompt)


def write_prompt_file(project_root: Path, prompt: str) -> Path:
    prompt_dir = project_root / "data" / "codex-prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / "latest-shopping-prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path


def launch_codex(plan: CodexLaunchPlan) -> int:
    return subprocess.run(plan.command, check=False).returncode


def format_command(command: list[str]) -> str:
    return " ".join(_quote_part(part) for part in command)


def format_interactive_launch_hint(
    project_root: Path,
    *,
    goal: str | None = None,
    listing_id: int | None = None,
    city: str | None = None,
    platforms: list[str] | None = None,
    codex_args: list[str] | None = None,
    entrypoint: str = "codex-guide",
) -> str:
    if entrypoint == "research" and goal:
        invocation = f"python -m shopping_agent.cli research {_powershell_arg(goal)} --run"
    elif listing_id is not None:
        invocation = f"python -m shopping_agent.cli codex-guide --listing-id {listing_id} --run"
    elif goal:
        invocation = f"python -m shopping_agent.cli codex-guide --goal {_powershell_arg(goal)} --run"
    else:
        invocation = 'python -m shopping_agent.cli codex-guide --goal "<purchase goal>" --run'
    if city:
        invocation += f" --city {_powershell_arg(city)}"
    for platform in platforms or []:
        invocation += f" --platform {_powershell_arg(platform)}"
    for codex_arg in codex_args or []:
        invocation += f" --codex-arg {_powershell_arg(codex_arg)}"
    return "$env:PYTHONPATH='src'; " + invocation + f"\nRun from: {project_root}"


def build_shopping_codex_prompt(
    goal: str | None = None,
    listing_id: int | None = None,
    city: str | None = None,
    platforms: list[str] | None = None,
) -> str:
    goal_line = f"\nUser shopping goal: {goal}" if goal else ""
    context_line = _shopping_context_line(city=city, platforms=platforms)
    listing_line = f"\nListing in scope: {listing_id}" if listing_id is not None else ""
    return f"""Use this repository as an interactive secondhand-shopping evidence assistant.
Read `skills/secondhand-shopping-research/SKILL.md` as UTF-8 and use it as the only Runtime operating contract.
On Windows, use `Get-Content -Raw -Encoding UTF8 skills\\secondhand-shopping-research\\SKILL.md`.
Route autonomously from the user's current question and load only the stage reference that the Skill says is needed.{goal_line}{context_line}{listing_line}

Answer the user's current question conversationally from saved or newly collected evidence.
Do not message, favorite, negotiate, order, pay, change account settings, or bypass platform protection.
Stop on login invalidation, CAPTCHA, rate limiting, or access protection.
"""


def _shopping_context_line(*, city: str | None, platforms: list[str] | None) -> str:
    parts = []
    if city:
        parts.append(f"default/override city: {city}")
    if platforms:
        parts.append("platform limit: " + ", ".join(platforms))
    if not parts:
        return ""
    return "\nWorkflow context: " + "; ".join(parts)


def _powershell_arg(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _quote_part(part: str) -> str:
    if " " in part or "\n" in part or "\t" in part:
        return shlex.quote(part)
    return part
