from __future__ import annotations

from shopping_agent.extraction.spec_parser import parse_imac_specs


def test_parse_imac_about_this_mac_ocr_text() -> None:
    text = """关于本机
iMac（视网膜5K显示屏，
27英寸，2019年）
处理器
3.7GHz六核Intel Corei5
辅助功能
聚集
图形卡
Radeon Pro 580X 8 GB
控制中心
内存
32 GB 2667 MHz DDR4
储存空间
Macintosh HD
476.76GB可用（共499.96GB）
macOS Sequoia
版本15.7.7
"""

    specs = parse_imac_specs(text)

    assert specs["year"] == "2019"
    assert specs["screen_size_inch"] == "27"
    assert specs["cpu"] == "3.7GHz六核Intel Core i5"
    assert specs["gpu"] == "Radeon Pro 580X 8 GB"
    assert specs["memory"] == "32 GB 2667 MHz DDR4"
    assert specs["storage_capacity"] == "499.96GB"
    assert specs["macos"] == "macOS Sequoia"


def test_parse_storage_type_hints() -> None:
    assert parse_imac_specs("1TB Fusion Drive")["storage_type_hint"] == "Fusion Drive"
    assert parse_imac_specs("512GB 固态硬盘 SSD")["storage_type_hint"] == "SSD"


def test_parse_storage_does_not_cross_memory_line_into_disk_label() -> None:
    text = """14寸M1 Pro+32G+1T 灰色
内存：32G
硬盘：1T
屏幕：14.2寸视网膜原彩
"""

    specs = parse_imac_specs(text)

    assert specs["storage_capacity"] == "1TB"


def test_parse_storage_from_seller_compact_memory_storage_notation() -> None:
    assert parse_imac_specs("MacBook Pro M1 Pro 32G+512G")["storage_capacity"] == "512GB"
    assert parse_imac_specs("MacBook Pro M1 Pro 32G+1T")["storage_capacity"] == "1TB"


def test_parse_memory_ignores_ocr_label_noise() -> None:
    noisy = parse_imac_specs("内存\nap\n图形卡/显示器")
    valid = parse_imac_specs("内存\n16GB\n屏幕使用时间")

    assert "memory" not in noisy
    assert valid["memory"] == "16GB"
