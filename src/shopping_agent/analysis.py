from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_ocr_result,
    connect,
    fetch_downloaded_media,
    fetch_downloaded_media_for_listing,
    fetch_downloaded_media_for_run,
    fetch_downloaded_media_pending_ocr,
    fetch_downloaded_media_pending_ocr_for_listing,
    fetch_downloaded_media_pending_ocr_for_run,
    initialize,
)
from shopping_agent.extraction.image_ocr import analyze_with_optional_ocr
from shopping_agent.extraction.spec_parser import parse_imac_specs


@dataclass
class ImageAnalysisRecord:
    media_id: int
    local_path: Path
    status: str
    backend: str
    width: int
    height: int
    ocr_chars: int
    error: str | None


def analyze_downloaded_images(
    config: AppConfig,
    media_type: str = "product_image_url",
    limit: int = 20,
    backend: str = "auto",
    include_existing: bool = False,
    run_id: int | None = None,
    listing_id: int | None = None,
) -> list[ImageAnalysisRecord]:
    initialize(config.database_path)
    records: list[ImageAnalysisRecord] = []
    with connect(config.database_path) as conn:
        if include_existing and listing_id is not None:
            rows = fetch_downloaded_media_for_listing(
                conn,
                listing_id=listing_id,
                media_type=media_type,
                limit=limit,
            )
        elif include_existing and run_id is not None:
            rows = fetch_downloaded_media_for_run(
                conn,
                run_id=run_id,
                media_type=media_type,
                limit=limit,
            )
        elif include_existing:
            rows = fetch_downloaded_media(conn, media_type=media_type, limit=limit)
        elif listing_id is not None:
            rows = fetch_downloaded_media_pending_ocr_for_listing(
                conn,
                listing_id=listing_id,
                media_type=media_type,
                limit=limit,
            )
        elif run_id is not None:
            rows = fetch_downloaded_media_pending_ocr_for_run(
                conn,
                run_id=run_id,
                media_type=media_type,
                limit=limit,
            )
        else:
            rows = fetch_downloaded_media_pending_ocr(conn, media_type=media_type, limit=limit)
        for row in rows:
            local_path = Path(row["local_path"])
            result = analyze_with_optional_ocr(local_path, backend=backend)
            detected_specs = {
                "width": result.width,
                "height": result.height,
            }
            if result.ocr_text:
                detected_specs.update(parse_imac_specs(result.ocr_text))
            add_ocr_result(
                conn,
                media_asset_id=int(row["id"]),
                ocr_text=result.ocr_text,
                detected_specs_json=json.dumps(detected_specs, ensure_ascii=False),
                backend=result.backend,
                status=result.status,
                error=result.error,
            )
            records.append(
                ImageAnalysisRecord(
                    media_id=int(row["id"]),
                    local_path=local_path,
                    status=result.status,
                    backend=result.backend,
                    width=result.width,
                    height=result.height,
                    ocr_chars=len(result.ocr_text),
                    error=result.error,
                )
            )
    return records
