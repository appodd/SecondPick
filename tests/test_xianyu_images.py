from __future__ import annotations

from shopping_agent.platforms.xianyu_images import select_xianyu_product_images


def test_select_xianyu_product_images_keeps_high_quality_fleamarket_detail_images() -> None:
    urls = [
        "https://gw.alicdn.com/bao/uploaded/i3/123456789/O1CN01avatar_!!123456789-userheader.jpg_110x10000Q90.jpg_.webp",
        "https://gw.alicdn.com/bao/uploaded/i3/123456789/O1CN01thumb-0-fleamarket.jpg_450x10000Q90.jpg_.webp",
        "https://gw.alicdn.com/bao/uploaded/i3/123456789/O1CN01MockImageOne_!!123456789-0-fleamarket.jpg_790x10000Q90.jpg_.webp",
        "https://gw.alicdn.com/bao/uploaded/i3/123456789/O1CN01MockImageTwo_!!123456789-0-fleamarket.jpg_Q90.jpg_.webp",
    ]

    selected = select_xianyu_product_images(urls)

    assert urls[2] in selected
    assert urls[3] in selected
    assert urls[0] not in selected
    assert urls[1] not in selected
