"""视觉模型辅助:拉取内网材料图片/PDF,编码成 OpenAI 兼容的 image_url data URI。

配合「模型管理」的 supports_vision 开关使用:仅当启用模型支持图片时才调用本模块。
所有失败都静默降级(跳过该图、不抛异常),保证一张图坏了不影响整次预约审查。
"""

from __future__ import annotations

import base64
import binascii
import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

_GS_BIN = shutil.which("gs") or "gs"

# 单张图片大小上限(超限跳过,避免把超大照片塞进请求);PDF 每页 150 DPI、最多 3 页。
MAX_IMAGE_BYTES = 6 * 1024 * 1024
PDF_DPI = 150
PDF_MAX_PAGES = 3

_EXT_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _normalize_storage_path(path: str | None) -> str:
    """去空白;内网返回的路径有的带前导 `/`(如证件照)、有的不带(如 word_url),统一补 `/`。"""
    p = (path or "").strip()
    if not p:
        return ""
    return p if p.startswith("/") else f"/{p}"


def _guess_mime(path: str, content_type: str | None) -> str:
    """优先响应 Content-Type,否则按扩展名推断;兜底 image/jpeg。"""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct and ct.startswith("image/"):
        return ct
    return _EXT_MIME.get(os.path.splitext(path)[1].lower(), "image/jpeg")


def _data_uri(mime: str, b64: str) -> str:
    return f"data:{mime};base64,{b64}"


def pdf_to_png_data_uris(
    pdf_bytes: bytes, *, dpi: int = PDF_DPI, max_pages: int = PDF_MAX_PAGES
) -> list[str]:
    """用系统 Ghostscript 把 PDF 逐页栅格化为 PNG,返回 data URI 列表;失败返回 []。

    零第三方依赖:环境无 Pillow/PyMuPDF/poppler,但预装了 `gs`(v10)。
    """
    if not pdf_bytes or max_pages <= 0:
        return []

    tmpdir: str | None = None
    try:
        tmpdir = tempfile.mkdtemp(prefix="pdf2png_")
        pdf_path = os.path.join(tmpdir, "input.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        out_pattern = os.path.join(tmpdir, "page-%d.png")
        cmd = [
            _GS_BIN,
            "-sDEVICE=png16m",
            f"-r{dpi}",
            "-dFirstPage=1",
            f"-dLastPage={max_pages}",
            "-dBATCH",
            "-dNOPAUSE",
            "-dQUIET",
            f"-sOutputFile={out_pattern}",
            pdf_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if proc.returncode != 0:
            logger.warning(
                "gs 转 PDF 失败: %s", proc.stderr.decode(errors="replace")[:200]
            )
            return []

        uris: list[str] = []
        for name in sorted(os.listdir(tmpdir)):
            if not name.endswith(".png"):
                continue
            with open(os.path.join(tmpdir, name), "rb") as f:
                data = f.read()
            uris.append(_data_uri("image/png", base64.b64encode(data).decode("ascii")))
        return uris
    except (OSError, subprocess.SubprocessError, binascii.Error) as exc:
        logger.warning("PDF 转图异常: %s", exc)
        return []
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


async def fetch_material_images(
    client: Any,
    images: list[dict],
    *,
    max_image_bytes: int = MAX_IMAGE_BYTES,
    dpi: int = PDF_DPI,
    max_pdf_pages: int = PDF_MAX_PAGES,
) -> list[dict]:
    """拉取并编码证件照片/PDF 为 image_url data URI。

    images 为 [{"label": 图说明, "path": 相对路径}]。拉取失败/超限/转图失败一律跳过,
    返回可用的 [{"label", "data_uri", "mime"}](PDF 逐页展开为多张 image/png)。
    """
    parts: list[dict] = []
    for img in images or []:
        label = img.get("label") or "材料图片"
        path = _normalize_storage_path(img.get("path"))
        if not path:
            continue
        try:
            resp = await client.get(path)
            resp.raise_for_status()
            content = resp.content
        except Exception as exc:  # httpx 网络/状态异常
            logger.warning("拉取材料图片失败 %s: %s", path, exc)
            continue
        if not content:
            continue

        # 大小限制对 PDF 同样生效:超大文件既撑爆内存,也让 gs 栅格化拖死进程。
        if len(content) > max_image_bytes:
            logger.warning("材料文件过大已跳过 %s (%d bytes)", path, len(content))
            continue

        if path.lower().endswith(".pdf"):
            # subprocess.run 是阻塞调用,挪到线程池,避免卡住事件循环(此前一张
            # PDF 最坏阻塞整个进程 60 秒,期间所有 API/后台同步停摆)。
            uris = await asyncio.to_thread(
                pdf_to_png_data_uris, content, dpi=dpi, max_pages=max_pdf_pages
            )
            for uri in uris:
                parts.append({"label": label, "data_uri": uri, "mime": "image/png"})
            continue

        mime = _guess_mime(path, resp.headers.get("content-type"))
        parts.append(
            {
                "label": label,
                "data_uri": _data_uri(mime, base64.b64encode(content).decode("ascii")),
                "mime": mime,
            }
        )
    return parts
