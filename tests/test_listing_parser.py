from shopping_agent.extraction.listing_parser import parse_price_value


def test_parse_price_value_supports_xianyu_ten_thousand_unit() -> None:
    assert parse_price_value("¥1.07万") == 10_700
    assert parse_price_value("1.2 万元") == 12_000


def test_parse_price_value_preserves_regular_prices() -> None:
    assert parse_price_value("¥4,688") == 4_688
    assert parse_price_value("RMB 5800 起") == 5_800
    assert parse_price_value(None) is None
