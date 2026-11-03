from __future__ import annotations

from shopping_agent.platforms.xianyu_parser import parse_xianyu_html_cards
from shopping_agent.spike import _listing_records_to_save

def _require_fixture() -> str:
    """Synthetic adjacent cards; never load personal browser capture artifacts."""
    return '''<a href="https://www.goofish.com/item?id=101&amp;categoryId=123">
      <span title="示例笔记本 16+512">示例笔记本 16+512</span>
      <span>¥</span><span>4800</span><span>上海</span></a>
      <a href="https://www.goofish.com/item?id=102">
      <span title="另一件模拟笔记本">另一件模拟笔记本</span>
      <span>¥</span><span>5888</span><span>广东</span></a>'''


def test_parse_xianyu_html_cards_keeps_link_and_summary_in_same_card() -> None:
    html = _require_fixture()

    listings = parse_xianyu_html_cards(html)
    by_url = {listing.url: listing for listing in listings}
    target = by_url["https://www.goofish.com/item?id=101&categoryId=123"]

    assert target.price_text == "¥4800"
    assert target.location == "上海"
    assert "16+512" in target.description
    assert "广东" not in target.description
    assert "¥5888" not in target.description


def test_spike_prefers_html_card_records_over_index_pairing() -> None:
    parsed = parse_xianyu_html_cards(_require_fixture())
    candidate_links = [
        "https://www.goofish.com/item?id=101&categoryId=123",
        "https://www.goofish.com/item?id=other&categoryId=123",
    ]

    records = _listing_records_to_save(
        platform="xianyu",
        parsed_listings=parsed,
        candidate_links=candidate_links,
        page_title="MacBook Pro 14 M1 Pro_闲鱼",
        query="MacBook Pro 14 M1 Pro",
    )
    by_url = {record.url: record for record in records}

    assert by_url["https://www.goofish.com/item?id=101&categoryId=123"].price_text == "¥4800"
    assert "个人闲置 2021款MacBook Pro 14寸" not in by_url[
        "https://www.goofish.com/item?id=101&categoryId=123"
    ].description


def test_parse_xianyu_api_items_extracts_structured_fields():
    from shopping_agent.platforms.xianyu_parser import parse_xianyu_api_items

    api_json = {
        "data": {
            "resultList": [
                {
                    "data": {
                        "item": {
                            "main": {
                                "exContent": {
                                    "itemId": "103",
                                    "title": "MacBook Pro 13.3寸 M1芯片 2020年款",
                                    "area": "北京",
                                    "price": [
                                        {"text": "¥", "type": "sign"},
                                        {"text": "2599", "type": "integer"},
                                    ],
                                    "fishTags": {
                                        "r3": {"tagList": [{"data": {"content": "几乎全新"}}]}
                                    },
                                    "want": "12人想要",
                                }
                            }
                        }
                    }
                },
                {
                    "data": {
                        "item": {
                            "main": {
                                "exContent": {
                                    "itemId": "103",
                                    "title": "duplicate should be skipped",
                                    "price": [{"text": "1", "type": "integer"}],
                                }
                            }
                        }
                    }
                },
                {
                    "data": {
                        "item": {
                            "main": {
                                "exContent": {"itemId": None}
                            }
                        }
                    }
                },
            ]
        }
    }
    listings = parse_xianyu_api_items(api_json)
    assert len(listings) == 1
    item = listings[0]
    assert item.url == "https://www.goofish.com/item?id=103"
    assert item.price_text == "¥2599"
    assert item.location == "北京"
    assert item.condition == "几乎全新"
    assert "M1芯片" in item.description
    assert item.interest_text == "12人想要"


def test_parse_xianyu_api_items_empty_and_malformed():
    from shopping_agent.platforms.xianyu_parser import parse_xianyu_api_items

    assert parse_xianyu_api_items({}) == []
    assert parse_xianyu_api_items({"data": {}}) == []
    assert parse_xianyu_api_items({"data": {"resultList": []}}) == []
    assert parse_xianyu_api_items({"data": {"resultList": [{"data": {}}]}}) == []


def test_parse_xianyu_api_items_keeps_search_card_fields_separate() -> None:
    from shopping_agent.platforms.xianyu_parser import parse_xianyu_api_items

    api_json = {
        "data": {
            "resultList": [
                {
                    "data": {
                        "item": {
                            "main": {
                                "exContent": {
                                    "itemId": "123",
                                    "title": "R9000P 2023",
                                    "price": [{"text": "¥"}, {"text": "5299"}],
                                    "area": "上海",
                                    "userNickName": "示例卖家",
                                    "fishTags": {
                                        "r1": {
                                            "tagList": [
                                                {"data": {"content": "几乎全新"}}
                                            ]
                                        }
                                    },
                                }
                            }
                        }
                    }
                }
            ]
        }
    }

    item = parse_xianyu_api_items(api_json)[0]

    assert item.title == "R9000P 2023"
    assert item.description == "R9000P 2023"
    assert item.seller_name == "示例卖家"
    assert item.condition == "几乎全新"
