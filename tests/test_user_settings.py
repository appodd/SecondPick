from pathlib import Path

import pytest
from pydantic import ValidationError

from shopping_agent.config import load_effective_config
from shopping_agent.user_settings import UserSettings, load_user_settings, save_user_settings


def test_legacy_settings_default_to_basic_mode(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"setup_completed": true}', encoding="utf-8")
    settings = load_user_settings(path)
    assert settings.setup_completed
    assert settings.setup_mode == "basic"


@pytest.mark.parametrize("mode", ["basic", "ai"])
def test_setup_mode_survives_reload(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "settings.json"
    save_user_settings(path, UserSettings(setup_completed=True, setup_mode=mode))
    assert load_user_settings(path).setup_mode == mode


def test_unknown_setup_mode_is_invalid() -> None:
    with pytest.raises(ValidationError):
        UserSettings(setup_mode="automatic")


def test_user_settings_round_trip_and_ignore_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_user_settings(
        path,
        UserSettings(
            setup_completed=True,
            default_city="鏉窞",
            platforms=["xianyu"],
            allow_ocr=False,
        ),
    )

    assert load_user_settings(path) == UserSettings(
        setup_completed=True,
        default_city="鏉窞",
        platforms=["xianyu"],
        allow_ocr=False,
    )


def test_effective_config_overlays_only_user_editable_fields(tmp_path: Path) -> None:
    defaults = tmp_path / "default.toml"
    defaults.write_text(
        'default_city = "涓婃捣"\ndatabase_path = "private.sqlite"\nplatforms = ["xianyu"]\nallow_ocr = true\n',
        encoding="utf-8",
    )
    settings = tmp_path / "settings.json"
    settings.write_text(
        '{"default_city":"鏉窞","database_path":"outside.sqlite","allow_ocr":false}',
        encoding="utf-8",
    )

    config = load_effective_config(defaults, settings)

    assert config.default_city == "鏉窞"
    assert config.allow_ocr is False
    assert config.database_path == Path("private.sqlite")
