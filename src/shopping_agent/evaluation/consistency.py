from __future__ import annotations

from dataclasses import dataclass, field

from shopping_agent.evidence import EvidenceFlag, ListingEvidenceBundle


@dataclass
class ListingConsistencyReport:
    listing_id: int
    description_specs: dict[str, str]
    image_specs: dict[str, str]
    flags: list[EvidenceFlag] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)


def evaluate_listing_consistency(bundle: ListingEvidenceBundle) -> ListingConsistencyReport:
    """Temporary local interpreter for evidence flags.

    This is intentionally not the final buyer recommendation engine. The durable
    contract is the evidence bundle; an LLM evaluator should later use that
    bundle plus reference material to make product-specific judgments.
    """
    risks: list[str] = []
    questions: list[str] = []
    for flag in bundle.flags:
        _interpret_flag(flag, risks, questions)

    return ListingConsistencyReport(
        listing_id=bundle.listing_id,
        description_specs=bundle.description_specs,
        image_specs=bundle.image_specs,
        flags=bundle.flags,
        risks=_dedupe(risks),
        questions=_dedupe(questions),
    )


def _interpret_flag(flag: EvidenceFlag, risks: list[str], questions: list[str]) -> None:
    if flag.code == "mentions_screen_redness":
        risks.append("描述提到屏幕泛红/红边；如果商品是老款 iMac，需要重点验屏。")
        questions.append("请卖家提供纯白、纯灰、纯黑背景下的全屏照片，确认红边和漏光程度。")
    elif flag.code == "mentions_cosmetic_damage":
        risks.append("描述提到外观或屏幕瑕疵，需要结合图片确认影响程度。")
        questions.append("请卖家单独拍摄划痕、磕碰位置的近景和正常使用距离照片。")
    elif flag.code == "mentions_missing_accessories":
        risks.append("描述提到配件或包装不完整，可能影响运输安全和后续转卖价值。")
    elif flag.code == "mentions_no_returns":
        risks.append("卖家声明不退不换，交易前需要更充分验机。")
    elif flag.code == "mentions_upgrade_or_replacement":
        risks.append("描述出现升级/更换/改装线索，需要结合具体商品判断是否影响原装性或保修。")
        questions.append("请卖家说明升级/更换项目、时间、是否保留原件，并提供相关截图或检测报告。")
    elif flag.code == "mentions_fusion_drive":
        risks.append("描述提到 Fusion Drive/Fusion HD；这对 Intel iMac 等老机型是高价值硬盘类型线索。")
        questions.append("请卖家确认硬盘是否为 Fusion Drive，并提供“系统报告 > 存储/ SATA/NVMe”截图。")
    elif flag.code == "mixed_storage_wording":
        risks.append("描述同时出现 Fusion 和固态，硬盘类型表述可能混淆。")
        questions.append("请卖家确认硬盘类型，说明是纯 SSD、Fusion Drive，还是后期改装。")
    elif flag.code.endswith("_mismatch"):
        risks.append(f"{flag.message} {flag.evidence}")
        questions.append("请卖家提供清晰的“关于本机”或系统报告截图确认该字段。")
    elif flag.code == "storage_type_mismatch":
        risks.append(f"{flag.message} {flag.evidence}")
        questions.append("请卖家拍摄磁盘工具或系统报告，确认硬盘类型和是否更换过。")
    elif flag.code == "ocr_text_without_specs":
        risks.append("图片有 OCR 文本但未抽取出明确配置，需要人工看图确认关键参数。")
def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
