from __future__ import annotations

from shopping_agent.platforms.xianyu_detail_parser import parse_xianyu_recommendation_links


def test_parse_xianyu_recommendation_links_excludes_current_and_dedupes() -> None:
    links = [
        "https://www.goofish.com/item?id=100",
        "https://www.goofish.com/item?id=101&categoryId=1",
        "https://www.goofish.com/item?id=101&categoryId=2",
        "https://www.goofish.com/search?q=iMac",
        "https://www.taobao.com/item?id=102",
        "https://www.goofish.com/item?id=abc",
    ]

    recommendations = parse_xianyu_recommendation_links(
        links,
        current_url="https://www.goofish.com/item?id=100&categoryId=1",
    )

    assert recommendations == ["https://www.goofish.com/item?id=101"]
