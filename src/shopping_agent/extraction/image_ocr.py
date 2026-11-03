from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from shopping_agent.models import ImageAnalysis


@dataclass
class LocalImageAnalysis:
    image_path: Path
    width: int
    height: int
    backend: str
    status: str
    ocr_text: str = ""
    error: str | None = None


class VisionAnalyzer:
    async def analyze_image(self, image_path: Path) -> ImageAnalysis:
        raise NotImplementedError("OCR/vision backend has not been selected yet.")


def analyze_local_image_metadata(image_path: Path) -> LocalImageAnalysis:
    with Image.open(image_path) as image:
        width, height = image.size
    return LocalImageAnalysis(
        image_path=image_path,
        width=width,
        height=height,
        backend="metadata",
        status="ok",
    )


def analyze_with_optional_ocr(image_path: Path, backend: str = "auto") -> LocalImageAnalysis:
    metadata = analyze_local_image_metadata(image_path)
    if backend not in {"auto", "pytesseract", "paddleocr"}:
        return LocalImageAnalysis(
            image_path=image_path,
            width=metadata.width,
            height=metadata.height,
            backend=backend,
            status="error",
            error=f"Unsupported OCR backend: {backend}",
        )

    if backend in {"auto", "paddleocr"}:
        paddle_result = _analyze_with_paddleocr(image_path, metadata.width, metadata.height)
        if paddle_result.status != "backend_missing" or backend == "paddleocr":
            return paddle_result

    if backend == "paddleocr":
        return LocalImageAnalysis(
            image_path=image_path,
            width=metadata.width,
            height=metadata.height,
            backend="paddleocr",
            status="backend_missing",
            error="paddleocr is not installed.",
        )

    try:
        import pytesseract  # type: ignore
    except ModuleNotFoundError:
        return LocalImageAnalysis(
            image_path=image_path,
            width=metadata.width,
            height=metadata.height,
            backend="none",
            status="backend_missing",
            error="No OCR backend installed. Install pytesseract+tesseract or add a vision backend.",
        )

    try:
        with Image.open(image_path) as image:
            text = pytesseract.image_to_string(image, lang="chi_sim+eng")
    except Exception as exc:  # pragma: no cover - backend/environment specific
        return LocalImageAnalysis(
            image_path=image_path,
            width=metadata.width,
            height=metadata.height,
            backend="pytesseract",
            status="error",
            error=str(exc),
        )

    return LocalImageAnalysis(
        image_path=image_path,
        width=metadata.width,
        height=metadata.height,
        backend="pytesseract",
        status="ok",
        ocr_text=text,
    )


def _analyze_with_paddleocr(image_path: Path, width: int, height: int) -> LocalImageAnalysis:
    _prepare_paddle_environment()
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except ModuleNotFoundError:
        return LocalImageAnalysis(
            image_path=image_path,
            width=width,
            height=height,
            backend="paddleocr",
            status="backend_missing",
            error="paddleocr is not installed.",
        )

    try:
        ocr = _create_paddle_ocr(PaddleOCR)
        result = ocr.ocr(str(image_path), cls=True)
        lines = []
        for page in result or []:
            for item in page or []:
                if len(item) >= 2 and isinstance(item[1], (list, tuple)):
                    text = item[1][0]
                    if text:
                        lines.append(str(text))
        text = "\n".join(lines)
    except Exception as exc:  # pragma: no cover - backend/environment specific
        return LocalImageAnalysis(
            image_path=image_path,
            width=width,
            height=height,
            backend="paddleocr",
            status="error",
            error=str(exc),
        )

    return LocalImageAnalysis(
        image_path=image_path,
        width=width,
        height=height,
        backend="paddleocr",
        status="ok",
        ocr_text=text,
    )


def _prepare_paddle_environment() -> None:
    cache_dir = Path("data/paddlex-cache").resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
    os.environ.setdefault("PADDLE_HOME", str(cache_dir / "paddle"))
    os.environ.setdefault("PADDLEX_HOME", str(cache_dir / "paddlex"))
    os.environ.setdefault("PADDLEOCR_HOME", str(cache_dir / "paddleocr"))


def _create_paddle_ocr(paddle_ocr_cls):
    model_base = Path("data/paddleocr-models")
    model_base.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "use_angle_cls": True,
        "lang": "ch",
        "show_log": False,
        "det_model_dir": str(model_base / "whl" / "det" / "ch" / "ch_PP-OCRv4_det_infer"),
        "rec_model_dir": str(model_base / "whl" / "rec" / "ch" / "ch_PP-OCRv4_rec_infer"),
        "cls_model_dir": str(model_base / "whl" / "cls" / "ch_ppocr_mobile_v2.0_cls_infer"),
    }
    try:
        return paddle_ocr_cls(**kwargs)
    except ValueError:
        kwargs.pop("show_log", None)
        return paddle_ocr_cls(**kwargs)
