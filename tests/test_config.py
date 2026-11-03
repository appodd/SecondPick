from shopping_agent.config import AppConfig, load_config


def test_default_platform_scope_is_xianyu_only() -> None:
    assert AppConfig().platforms == ["xianyu"]
    assert load_config().platforms == ["xianyu"]


def test_default_config_disables_favorites() -> None:
    assert AppConfig().allow_favorite is False
    assert load_config().allow_favorite is False


def test_default_xianyu_search_interval_is_1800_seconds() -> None:
    assert AppConfig().safety.xianyu_min_search_interval_seconds == 1800
    assert load_config().safety.xianyu_min_search_interval_seconds == 1800
