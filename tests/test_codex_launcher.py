from __future__ import annotations

from pathlib import Path

from shopping_agent.codex_launcher import (
    build_codex_launch_plan,
    format_interactive_launch_hint,
    write_prompt_file,
)


def test_goal_prompt_is_small_runtime_entrypoint() -> None:
    goal = "上海找一台索尼 A7C 一代机身"
    plan = build_codex_launch_plan(
        project_root=Path("C:/project"),
        goal=goal,
        city="上海",
        platforms=["xianyu"],
    )

    assert "skills/secondhand-shopping-research/SKILL.md" in plan.prompt
    assert "handoff.md" not in plan.prompt
    assert "SESSION_HANDOFF.md" not in plan.prompt
    assert "Goal-driven workflow:" not in plan.prompt
    assert "Mechanical query patterns include:" not in plan.prompt
    assert "Expected output:" not in plan.prompt
    assert len(plan.prompt) < 6_000


def test_goal_prompt_preserves_unicode_goal_city_without_eager_stage_commands() -> None:
    goal = "上海找一台索尼 A7C 一代机身"
    plan = build_codex_launch_plan(
        project_root=Path("C:/project"),
        goal=goal,
        city="上海",
        platforms=["xianyu"],
    )

    assert f"User shopping goal: {goal}" in plan.prompt
    assert "default/override city: 上海" in plan.prompt
    assert "Get-Content -Raw -Encoding UTF8" in plan.prompt
    for forbidden in (
        "task-summary",
        "candidate-index",
        "research-loop",
        "README",
        "source",
        "config",
        "handoff",
        "CLI help",
    ):
        assert forbidden not in plan.prompt
    assert "Do not message, favorite, negotiate, order, pay" in plan.prompt


def test_listing_prompt_uses_skill_and_listing_scope_without_eager_command() -> None:
    plan = build_codex_launch_plan(
        project_root=Path("C:/project"),
        listing_id=42,
    )

    assert "skills/secondhand-shopping-research/SKILL.md" in plan.prompt
    assert "Listing in scope: 42" in plan.prompt
    assert "evaluation-task" not in plan.prompt
    assert "save-report" not in plan.prompt
    assert "save-html-report" not in plan.prompt
    assert "Optional saved evidence report path" not in plan.prompt


def test_build_codex_launch_plan_forwards_extra_codex_args() -> None:
    plan = build_codex_launch_plan(
        project_root=Path("C:/project"),
        goal="找 2019 iMac 27 寸",
        codex_args=["--no-alt-screen", "-a", "never"],
    )

    assert plan.command[:4] == ["codex", "-C", "C:\\project", "--search"]
    assert plan.command[4:7] == ["--no-alt-screen", "-a", "never"]
    assert plan.command[-1] == plan.prompt


def test_build_codex_launch_plan_includes_city_and_platform_context() -> None:
    goal = "帮我找 2019 年 27 寸 iMac，上海优先"
    plan = build_codex_launch_plan(
        project_root=Path("C:/project"),
        goal=goal,
        city="上海",
        platforms=["xianyu"],
    )

    assert "Workflow context: default/override city: 上海; platform limit: xianyu" in plan.prompt
    assert "task-summary" not in plan.prompt


def test_goal_prompt_preserves_quoted_goal_without_shell_interpolation() -> None:
    plan = build_codex_launch_plan(
        project_root=Path("C:/project"),
        goal='找 "2019 iMac 27 寸"',
    )

    assert 'User shopping goal: 找 "2019 iMac 27 寸"' in plan.prompt


def test_interactive_launch_hint_uses_goal() -> None:
    hint = format_interactive_launch_hint(
        Path("C:/project"),
        goal="帮我找 2019 年 27 寸 iMac，上海优先",
    )

    assert (
        "python -m shopping_agent.cli codex-guide "
        "--goal '帮我找 2019 年 27 寸 iMac，上海优先' --run"
    ) in hint
    assert "<purchase goal>" not in hint


def test_interactive_launch_hint_includes_city_and_platform_context() -> None:
    hint = format_interactive_launch_hint(
        Path("C:/project"),
        goal="帮我找 2019 年 27 寸 iMac，上海优先",
        city="上海",
        platforms=["xianyu"],
    )

    assert "--city '上海'" in hint
    assert "--platform 'xianyu'" in hint


def test_interactive_launch_hint_includes_codex_args() -> None:
    hint = format_interactive_launch_hint(
        Path("C:/project"),
        goal="帮我找 2019 年 27 寸 iMac，上海优先",
        codex_args=["--no-alt-screen", "-a", "never"],
    )

    assert "--codex-arg '--no-alt-screen'" in hint
    assert "--codex-arg '-a'" in hint
    assert "--codex-arg 'never'" in hint


def test_interactive_launch_hint_can_use_research_entrypoint() -> None:
    hint = format_interactive_launch_hint(
        Path("C:/project"),
        goal="帮我找 2019 年 27 寸 iMac，上海优先",
        city="上海",
        platforms=["xianyu"],
        entrypoint="research",
    )

    assert "python -m shopping_agent.cli research '帮我找 2019 年 27 寸 iMac，上海优先' --run" in hint
    assert "--city '上海'" in hint
    assert "--platform 'xianyu'" in hint
    assert "codex-guide --goal" not in hint


def test_interactive_launch_hint_uses_listing_id() -> None:
    hint = format_interactive_launch_hint(Path("C:/project"), listing_id=42)

    assert "python -m shopping_agent.cli codex-guide --listing-id 42 --run" in hint
    assert "<purchase goal>" not in hint


def test_interactive_launch_hint_defaults_to_placeholder() -> None:
    hint = format_interactive_launch_hint(Path("C:/project"))

    assert 'python -m shopping_agent.cli codex-guide --goal "<purchase goal>" --run' in hint


def test_write_prompt_file() -> None:
    root = Path("data/test-codex-launcher")
    prompt_path = write_prompt_file(root, "hello")

    assert prompt_path.name == "latest-shopping-prompt.txt"
    assert prompt_path.read_text(encoding="utf-8") == "hello"
