from __future__ import annotations

from shopping_agent.platforms.xianyu_detail_parser import parse_xianyu_detail_api


def test_parse_xianyu_detail_api_extracts_structured_fields():
    api_detail = {
        "item": {
            "itemId": "1071269061272",
            "title": "MacBook Pro 2020款 M1芯片",
            "desc": "8+512G高配，成色一般，电池还84",
            "soldPrice": "2655",
            "wantCnt": 10,
            "wantCntUnit": "人想要",
            "browseCnt": 577,
            "itemLabelExtList": [
                {"propertyText": "分类", "text": "笔记本电脑"},
                {"propertyText": "品牌", "text": "Apple/苹果"},
            ],
        },
        "seller": {
            "nick": "条条大王",
            "city": "武汉",
            "hasSoldNumInteger": 22,
            "replyRatio24h": "52%",
            "zhimaLevelInfo": {"levelName": "信用良好"},
            "xianyuSummary": "卖出过22件宝贝。女生。",
        },
    }
    parsed = parse_xianyu_detail_api(api_detail)
    assert parsed is not None
    assert parsed.price_text == "¥2655"
    assert parsed.seller_name == "条条大王"
    assert parsed.seller_location == "武汉"
    assert parsed.wanted_text == "10人想要"
    assert parsed.view_text == "577浏览"
    assert "8+512G" in parsed.description
    assert parsed.attributes["分类"] == "笔记本电脑"
    assert parsed.attributes["品牌"] == "Apple/苹果"
    assert any("22" in s for s in parsed.seller_stats)


def test_parse_xianyu_detail_api_none_and_empty():
    assert parse_xianyu_detail_api(None) is None
    assert parse_xianyu_detail_api({}) is None
    assert parse_xianyu_detail_api({"item": {}, "seller": {}}) is None
    assert parse_xianyu_detail_api({"item": {"itemId": None}, "seller": {}}) is None
