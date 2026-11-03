from __future__ import annotations

import inspect

from shopping_agent.cli import build_parser
from shopping_agent.prepare_evidence import (
    _compact_evidence_bundle,
    _ready_listing_ids,
    prepare_run_evidence,
)


def test_ready_listing_ids_requires_detail_only() -> None:
    summary = {
        "listings": [
            {
                "listing_id": 1,
                "collection_state": {
                    "has_detail": True,
                    "has_downloaded_images": True,
                    "has_ocr": True,
                },
            },
            {
                "listing_id": 2,
                "collection_state": {
                    "has_detail": True,
                    "has_downloaded_images": False,
                    "has_ocr": False,
                },
            },
            {
                "listing_id": 3,
                "collection_state": {
                    "has_detail": False,
                    "has_downloaded_images": True,
                    "has_ocr": True,
                },
            },
        ]
    }

    assert _ready_listing_ids(summary, limit=1) == [1]
    assert _ready_listing_ids(summary, limit=3) == [1, 2]


def test_prepare_evidence_defaults_skip_media_and_ocr() -> None:
    parser = build_parser()
    args = parser.parse_args(["prepare-evidence", "--run-id", "1"])
    parameters = inspect.signature(prepare_run_evidence).parameters

    assert args.media_limit == 0
    assert args.ocr_limit == 0
    assert parameters["media_limit"].default == 0
    assert parameters["ocr_limit"].default == 0


def test_compact_evidence_bundle_truncates_ocr_text() -> None:
    ocr_text = "关于本机 2019 iMac 27 寸"
    bundle = {
        "listing_id": 1,
        "ocr_evidence": [
            {
                "media_asset_id": 10,
                "ocr_text": ocr_text,
                "detected_specs": {"year": "2019"},
            }
        ],
    }

    compact = _compact_evidence_bundle(bundle, ocr_chars=6)

    assert compact["ocr_evidence"][0]["ocr_text_chars"] == len(ocr_text)
    assert compact["ocr_evidence"][0]["ocr_text"] == "关于本机 ..."
