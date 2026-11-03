from __future__ import annotations

import re


def parse_imac_specs(text: str) -> dict[str, str]:
    normalized = _normalize(text)
    lines = _non_empty_lines(normalized)
    specs: dict[str, str] = {}

    year = _first_match(normalized, r"(20\d{2})\s*年")
    if year:
        specs["year"] = year

    model = _first_match(normalized, r"iMac\s*[（(][^）)]*?(\d+\.?\d*)\s*英寸[^）)]*?[）)]")
    if model:
        specs["screen_size_inch"] = model
    elif "27英寸" in normalized or "27 英寸" in normalized or "27寸" in normalized or "27 寸" in normalized:
        specs["screen_size_inch"] = "27"

    cpu = _line_after_label(lines, "处理器") or _first_match(
        normalized,
        r"(\d+(?:\.\d+)?\s*GHz[^\n]*(?:Core\s*i\d|Corei\d|Xeon|六核i\d|八核i\d|十核i\d)[^\n]*)",
    )
    if cpu:
        specs["cpu"] = _normalize_cpu(_truncate_at_next_spec(cpu))

    gpu = _line_after_label(lines, "图形卡") or _first_match(
        normalized,
        r"(?:AMD\s+)?(Radeon\s+Pro\s+[A-Za-z0-9 ]+\s+\d+\s*(?:GB|G))",
    )
    if gpu:
        specs["gpu"] = gpu.strip().replace("  ", " ").replace("  ", " ").replace("  ", " ")

    memory = _valid_memory(_line_after_label(lines, "内存"))
    if not memory:
        memory = _first_match(normalized, r"(\d+\s*(?:GB|G)(?:\s+\d+\s*MHz)?\s+DDR\d)")
    if not memory:
        memory = _first_match(normalized, r"(?:内存|统一内存)[：:\s]*(\d+\s*(?:GB|G)\b)")
    if not memory:
        memory = _first_match(normalized, r"(\d+\s*(?:GB|G))\s*(?:统一)?内存")
    if memory:
        specs["memory"] = memory.strip().replace(" G ", " GB ")

    storage = _first_match(normalized, r"共\s*(\d+(?:\.\d+)?\s*(?:GB|TB))")
    if not storage:
        storage = _first_match(normalized, r"(?:Macintosh HD|储存空间|存储空间)[^\n]*(\d+(?:\.\d+)?\s*(?:GB|TB))")
    if not storage:
        storage = _first_match(
            normalized,
            r"(?:硬盘|硬碟|固态|存储|闪存|硬盘容量|存储容量)[：:\s]*(\d+(?:\.\d+)?\s*(?:GB|G|TB|T))",
        )
    if not storage:
        storage = _first_match(
            normalized,
            r"(?:SSD|NVMe|NVMExpress)[：:\s]*(\d+(?:\.\d+)?\s*(?:GB|G|TB|T))",
        )
    if not storage:
        storage = _first_match(
            normalized,
            r"(?:^|[^0-9])\d+\s*(?:GB|G)\s*(?:\+|/|／)\s*(\d+(?:\.\d+)?\s*(?:GB|G|TB|T))",
        )
    if not storage:
        storage = _first_match(
            normalized,
            r"(?:^|[^0-9])\d+\s*(?:GB|G)\s*(\d+(?:\.\d+)?\s*(?:TB|T))\b",
        )
    if not storage:
        storage = _first_match(
            normalized,
            r"(\d+(?:\.\d+)?\s*(?:GB|G|TB|T))[ \t]*(?:Fusion|SSD|固态|闪存|机械|硬盘|硬碟)",
        )
    if storage:
        specs["storage_capacity"] = _normalize_capacity(storage)

    macos = _first_match(normalized, r"(macOS\s+[A-Za-z ]+)")
    if macos:
        specs["macos"] = macos.strip()

    if "Fusion" in normalized or "融合硬盘" in normalized:
        specs["storage_type_hint"] = "Fusion Drive"
    elif "SSD" in normalized or "固态" in normalized:
        specs["storage_type_hint"] = "SSD"

    return specs


def _non_empty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _line_after_label(lines: list[str], label: str) -> str | None:
    for index, line in enumerate(lines):
        if line == label or line.startswith(label + ":"):
            inline = line.split(":", 1)[1].strip() if ":" in line else ""
            if inline:
                return inline
            for candidate in lines[index + 1 : index + 4]:
                if candidate not in {
                    "辅助功能",
                    "聚集",
                    "控制中心",
                    "?",
                    "屏幕保护程序",
                }:
                    return candidate
    return None


def _normalize_cpu(cpu: str) -> str:
    return cpu.replace("Corei", "Core i").strip()


def _valid_memory(value: str | None) -> str | None:
    if value and re.search(r"\d+\s*(?:GB|G)\b", value, flags=re.IGNORECASE):
        return value
    return None


def _normalize_capacity(capacity: str) -> str:
    value = capacity.strip()
    value = re.sub(r"(?i)(\d)\s*G\b", r"\1GB", value)
    value = re.sub(r"(?i)(\d)\s*T\b", r"\1TB", value)
    return value


def _truncate_at_next_spec(value: str) -> str:
    for marker in ("，AMD", ", AMD", "，Radeon", ", Radeon", "图形卡", "显卡", "内存", "硬盘", "储存"):
        if marker in value:
            value = value.split(marker, 1)[0]
    return value


def _normalize(text: str) -> str:
    return (
        text.replace("：", ":")
        .replace("（", "(")
        .replace("）", ")")
        .replace("Ｇ", "G")
        .replace("Ｂ", "B")
    )


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1) if match else None
