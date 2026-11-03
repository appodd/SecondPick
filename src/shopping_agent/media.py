from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    connect,
    delete_legacy_media,
    fetch_media_assets,
    fetch_pending_media,
    fetch_pending_media_for_listing,
    fetch_pending_media_for_run,
    initialize,
    update_media_local_path,
)


@dataclass
class MediaDownloadResult:
    media_id: int
    source_url: str
    local_path: Path
    ok: bool
    error: str | None = None


def download_pending_media(
    config: AppConfig,
    limit: int = 10,
    media_type: str = "product_image_url",
    run_id: int | None = None,
    listing_id: int | None = None,
) -> list[MediaDownloadResult]:
    initialize(config.database_path)
    results: list[MediaDownloadResult] = []
    with connect(config.database_path) as conn:
        if listing_id is not None:
            rows = fetch_pending_media_for_listing(
                conn,
                listing_id=listing_id,
                limit=limit,
                media_type=media_type,
            )
        elif run_id is None:
            rows = fetch_pending_media(conn, limit=limit, media_type=media_type)
        else:
            rows = fetch_pending_media_for_run(conn, run_id=run_id, limit=limit, media_type=media_type)
        for row in rows:
            source_url = row["source_url"]
            local_path = _media_path(config.media_dir, int(row["listing_id"]), source_url)
            try:
                _download(source_url, local_path)
            except Exception as exc:
                results.append(
                    MediaDownloadResult(
                        media_id=int(row["id"]),
                        source_url=source_url,
                        local_path=local_path,
                        ok=False,
                        error=str(exc),
                    )
                )
                continue
            update_media_local_path(conn, int(row["id"]), local_path)
            results.append(
                MediaDownloadResult(
                    media_id=int(row["id"]),
                    source_url=source_url,
                    local_path=local_path,
                    ok=True,
                )
            )
    return results


def cleanup_legacy_media(config: AppConfig, media_type: str = "image_url") -> int:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        deleted = delete_legacy_media(conn, media_type=media_type)
    return deleted


def list_media_assets(config: AppConfig, media_type: str = "product_image_url", limit: int = 50):
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        return fetch_media_assets(conn, media_type=media_type, limit=limit)


def _media_path(media_dir: Path, listing_id: int, source_url: str) -> Path:
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]
    suffix = _guess_suffix(source_url)
    return media_dir / f"listing-{listing_id}" / f"{digest}{suffix}"


def _guess_suffix(source_url: str) -> str:
    lowered = source_url.lower()
    for suffix in (".webp", ".jpg", ".jpeg", ".png", ".heic", ".gif"):
        if suffix in lowered:
            return suffix
    guessed = mimetypes.guess_extension(mimetypes.guess_type(source_url)[0] or "")
    return guessed or ".img"


def _download(source_url: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        source_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.goofish.com/",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            local_path.write_bytes(response.read())
    except URLError as exc:
        raise RuntimeError(exc.reason) from exc
