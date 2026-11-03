from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    connect,
    fetch_latest_detail_snapshot_for_listing,
    fetch_latest_listing_snapshot,
    fetch_latest_ocr_results_for_listing,
    initialize,
)
from shopping_agent.extraction.spec_parser import parse_imac_specs


@dataclass
class OcrEvidence:
    media_asset_id: int
    local_path: str
    ocr_text: str
    detected_specs: dict[str, str]


@dataclass
class EvidenceFlag:
    code: str
    severity: str
    source: str
    message: str
    evidence: dict[str, str] = field(default_factory=dict)


@dataclass
class ListingEvidenceBundle:
    listing_id: int
    url: str
    platform: str
    source_type: str
    source_label: str
    price_text: str | None
    location: str | None
    seller_name: str | None
    description: str
    description_specs: dict[str, str]
    image_specs: dict[str, str]
    seller_signals: dict[str, object]
    ocr_evidence: list[OcrEvidence]
    flags: list[EvidenceFlag]


def build_listing_evidence(config: AppConfig, listing_id: int) -> ListingEvidenceBundle:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        listing = fetch_latest_listing_snapshot(conn, listing_id)
        if listing is None:
            raise ValueError(f"No detail snapshot found for listing {listing_id}.")
        ocr_rows = fetch_latest_ocr_results_for_listing(conn, listing_id)
        detail_snapshot = fetch_latest_detail_snapshot_for_listing(conn, listing_id)

    description = str(listing["description"] or "")
    description_specs = parse_imac_specs(description)
    detail_text = _read_detail_text(detail_snapshot)
    seller_signals = collect_seller_signals(
        description=description,
        seller_name=listing["seller_name"],
        detail_text=detail_text,
    )
    ocr_evidence = _build_ocr_evidence(ocr_rows)
    image_specs = _merge_specs([item.detected_specs for item in ocr_evidence])
    flags = collect_evidence_flags(
        description=description,
        description_specs=description_specs,
        image_specs=image_specs,
        ocr_evidence=ocr_evidence,
    )

    return ListingEvidenceBundle(
        listing_id=listing_id,
        url=str(listing["url"]),
        platform=str(listing["platform"]),
        source_type=str(listing["source_type"] or "unknown"),
        source_label=str(listing["source_label"] or "未知来源"),
        price_text=listing["price_text"],
        location=listing["location"],
        seller_name=listing["seller_name"],
        description=description,
        description_specs=description_specs,
        image_specs=image_specs,
        seller_signals=seller_signals,
        ocr_evidence=ocr_evidence,
        flags=flags,
    )


def collect_seller_signals(
    description: str,
    seller_name: str | None = None,
    detail_text: str | None = None,
) -> dict[str, object]:
    """Extract seller-related evidence without deciding the seller type."""

    text = "\n".join(part for part in (seller_name or "", description, detail_text or "") if part)
    return {
        "extraction_note": (
            "Tool-extracted seller evidence only. The LLM must decide seller type, confidence, "
            "and buying impact from these signals plus page/profile evidence."
        ),
        "seller_name_present": bool(seller_name),
        "sold_count": _extract_count(text, r"卖出\s*(\d+)\s*件"),
        "wanted_count": _extract_count(text, r"(\d+)\s*人想要"),
        "view_count": _extract_count(text, r"(\d+)\s*浏览"),
        "merchant_keyword_hits": _matched_terms(
            text,
            (
                "卖出",
                "大量现货",
                "批发",
                "库存",
                "门店",
                "实体店",
                "店铺",
                "售后",
                "质保",
                "保修",
                "可开发票",
                "回收",
                "公司回购",
                "公司更新",
                "工作机",
                "同配置还有",
                "总共",
                "多台",
                "可装系统",
                "安装双系统",
            ),
        ),
        "personal_keyword_hits": _matched_terms(
            text,
            (
                "自用",
                "闲置",
                "个人闲置",
                "换新",
                "换机",
                "搬家",
                "毕业",
                "吃灰",
                "很少用",
                "仅自提",
                "不邮寄",
                "发票",
                "订单截图",
            ),
        ),
        "trust_keyword_hits": _matched_terms(
            text,
            (
                "验货宝",
                "验号担保",
                "信用极好",
                "信用优秀",
                "百分百好评",
                "回复超快",
                "担保交易",
            ),
        ),
        "risk_keyword_hits": _matched_terms(
            text,
            (
                "不退不换",
                "不退",
                "不换",
                "公司回购",
                "工作机",
                "批量",
                "拆修",
                "维修",
                "翻新",
                "改装",
            ),
        ),
        "evidence_excerpt": _truncate(text, 500),
    }


def _read_detail_text(detail_snapshot) -> str:
    if detail_snapshot is None or not detail_snapshot["text_path"]:
        return ""
    try:
        from pathlib import Path

        path = Path(detail_snapshot["text_path"])
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return ""


def collect_evidence_flags(
    description: str,
    description_specs: dict[str, str],
    image_specs: dict[str, str],
    ocr_evidence: list[OcrEvidence],
) -> list[EvidenceFlag]:
    flags: list[EvidenceFlag] = []
    _append_keyword_flags(description, flags)
    _append_spec_flags(description_specs, image_specs, flags)
    if ocr_evidence and not image_specs:
        flags.append(
            EvidenceFlag(
                code="ocr_text_without_specs",
                severity="medium",
                source="ocr",
                message="商品图片有 OCR 文本，但未能抽取到明确配置。",
            )
        )
    return _dedupe_flags(flags)


def evidence_bundle_to_dict(bundle: ListingEvidenceBundle) -> dict:
    return {
        "listing_id": bundle.listing_id,
        "url": bundle.url,
        "platform": bundle.platform,
        "source_type": bundle.source_type,
        "source_label": bundle.source_label,
        "price_text": bundle.price_text,
        "location": bundle.location,
        "seller_name": bundle.seller_name,
        "description": bundle.description,
        "description_specs": bundle.description_specs,
        "image_specs": bundle.image_specs,
        "seller_signals": bundle.seller_signals,
        "ocr_evidence": [
            {
                "media_asset_id": item.media_asset_id,
                "local_path": item.local_path,
                "detected_specs": item.detected_specs,
                "ocr_text": item.ocr_text,
            }
            for item in bundle.ocr_evidence
        ],
        "flags": [
            {
                "code": flag.code,
                "severity": flag.severity,
                "source": flag.source,
                "message": flag.message,
                "evidence": flag.evidence,
            }
            for flag in bundle.flags
        ],
    }


def _build_ocr_evidence(ocr_rows) -> list[OcrEvidence]:
    evidence = []
    for row in ocr_rows:
        if row["status"] != "ok":
            continue
        ocr_text = str(row["ocr_text"] or "")
        stored_specs = json.loads(row["detected_specs_json"] or "{}")
        detected_specs = {
            key: value
            for key, value in stored_specs.items()
            if key in {"width", "height"}
        }
        if ocr_text:
            detected_specs.update(parse_imac_specs(ocr_text))
        if not ocr_text and not detected_specs:
            continue
        evidence.append(
            OcrEvidence(
                media_asset_id=int(row["media_asset_id"]),
                local_path=str(row["local_path"] or ""),
                ocr_text=ocr_text,
                detected_specs={str(key): str(value) for key, value in detected_specs.items()},
            )
        )
    return evidence


def _append_keyword_flags(description: str, flags: list[EvidenceFlag]) -> None:
    keyword_groups = [
        ("mentions_screen_redness", "medium", ("泛红", "红边", "发红"), "描述提到屏幕泛红/红边。"),
        ("mentions_cosmetic_damage", "medium", ("划痕", "磕碰", "瑕疵"), "描述提到外观或屏幕瑕疵。"),
        ("mentions_missing_accessories", "low", ("单机", "无原包装", "无其它配件", "没有外包装"), "描述提到配件或包装不完整。"),
        ("mentions_no_returns", "medium", ("不退不换", "不退", "不换"), "描述提到不退不换。"),
        ("mentions_upgrade_or_replacement", "medium", ("升级", "更换", "换过", "改装"), "描述提到升级、更换或改装。"),
        ("mentions_fusion_drive", "medium", ("Fusion", "Fusion HD", "融合硬盘"), "描述提到 Fusion Drive/Fusion HD。"),
    ]
    for code, severity, terms, message in keyword_groups:
        matched = [term for term in terms if term in description]
        if matched:
            flags.append(
                EvidenceFlag(
                    code=code,
                    severity=severity,
                    source="description",
                    message=message,
                    evidence={"matched_terms": ", ".join(matched)},
                )
            )
    if "Fusion" in description and "固态" in description:
        flags.append(
            EvidenceFlag(
                code="mixed_storage_wording",
                severity="high",
                source="description",
                message="描述同时出现 Fusion 和固态，硬盘类型表述可能混淆。",
                evidence={"text": "Fusion + 固态"},
            )
        )


def _append_spec_flags(
    description_specs: dict[str, str],
    image_specs: dict[str, str],
    flags: list[EvidenceFlag],
) -> None:
    for key, label in (
        ("year", "年份"),
        ("screen_size_inch", "屏幕尺寸"),
        ("memory", "内存"),
        ("storage_capacity", "硬盘容量"),
    ):
        left = description_specs.get(key)
        right = image_specs.get(key)
        if left and right and not _specs_equivalent(key, left, right):
            flags.append(
                EvidenceFlag(
                    code=f"{key}_mismatch",
                    severity="high",
                    source="description_vs_ocr",
                    message=f"描述{label}和图片 OCR 识别结果不一致。",
                    evidence={"description": left, "ocr": right},
                )
            )
    description_type = description_specs.get("storage_type_hint")
    image_type = image_specs.get("storage_type_hint")
    if description_type and image_type and description_type != image_type:
        flags.append(
            EvidenceFlag(
                code="storage_type_mismatch",
                severity="high",
                source="description_vs_ocr",
                message="描述硬盘类型和图片 OCR 识别结果不一致。",
                evidence={"description": description_type, "ocr": image_type},
            )
        )


def _merge_specs(specs_list: list[dict[str, str]]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for specs in specs_list:
        for key, value in specs.items():
            if key in {"width", "height"}:
                continue
            if value and key not in merged:
                merged[key] = value
    return merged


def _specs_equivalent(key: str, left: str, right: str) -> bool:
    if key == "memory":
        return _first_number(left) == _first_number(right)
    if key == "storage_capacity":
        left_gb = _capacity_gb(left)
        right_gb = _capacity_gb(right)
        if left_gb is not None and right_gb is not None:
            return abs(left_gb - right_gb) <= max(20.0, left_gb * 0.08)
    return _canonical(left) == _canonical(right)


def _canonical(value: str) -> str:
    return "".join(value.upper().split()).replace("G", "GB").replace("T", "TB")


def _first_number(value: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def _capacity_gb(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*([GT]B?|GB|TB)", value, flags=re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).upper()
    if unit.startswith("T"):
        return number * 1000
    return number


def _dedupe_flags(flags: list[EvidenceFlag]) -> list[EvidenceFlag]:
    seen = set()
    result = []
    for flag in flags:
        key = (flag.code, flag.source, tuple(sorted(flag.evidence.items())))
        if key not in seen:
            seen.add(key)
            result.append(flag)
    return result


def _extract_count(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return int(match.group(1))


def _matched_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text]


def _truncate(value: str, max_chars: int) -> str:
    value = " ".join(value.split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + "..."
