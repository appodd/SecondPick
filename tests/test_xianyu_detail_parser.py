from __future__ import annotations

from shopping_agent.platforms.xianyu_detail_parser import parse_xianyu_detail_text


def test_detail_description_stops_before_split_attribute_block() -> None:
    parsed = parse_xianyu_detail_text(
        "\n".join(
            [
                "卖家甲",
                "上海",
                "¥",
                "6188",
                "范围内完整详情描述",
                "成",
                "色",
                "：",
                "明显磕碰划痕",
                "拆",
                "修",
                "：",
                "更换过屏幕",
            ]
        )
    )

    assert parsed.description == "范围内完整详情描述"
    assert parsed.attributes == {
        "成色": "明显磕碰划痕",
        "拆修": "更换过屏幕",
    }
