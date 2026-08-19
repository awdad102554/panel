"""视觉辅助模块单测:路径归一化 / PDF 转图(Ghostscript) / 视觉消息构造。"""

import base64
import os
import subprocess
import tempfile

from app.ai.vision import _data_uri, _normalize_storage_path, pdf_to_png_data_uris
from app.services.reserve_review import build_vision_messages


def test_normalize_storage_path_adds_slash():
    # word_url 的路径无前导 `/`,需补上。
    assert _normalize_storage_path("storage/temporary/word/a.pdf") == "/storage/temporary/word/a.pdf"


def test_normalize_storage_path_keeps_slash_and_strips():
    assert _normalize_storage_path("  /storage/uploads/a.jpg ") == "/storage/uploads/a.jpg"


def test_normalize_storage_path_empty():
    assert _normalize_storage_path(None) == ""
    assert _normalize_storage_path("") == ""


def test_data_uri():
    assert _data_uri("image/png", "aGk=") == "data:image/png;base64,aGk="


def test_pdf_to_png_data_uris_roundtrip():
    # 用 gs 现生成一张 1 页 PDF,再走 pdf_to_png_data_uris 转回 PNG,验证管道可用。
    tmp = tempfile.mkdtemp(prefix="testpdf_")
    pdf_path = os.path.join(tmp, "one.pdf")
    ps = (
        b"%!PS\n"
        b"/Helvetica findfont 20 scalefont setfont\n"
        b"72 720 moveto (hello) show\n"
        b"showpage\n"
    )
    proc = subprocess.run(
        ["gs", "-sDEVICE=pdfwrite", "-o", pdf_path, "-"],
        input=ps,
        capture_output=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    uris = pdf_to_png_data_uris(pdf_bytes)
    assert len(uris) == 1
    assert uris[0].startswith("data:image/png;base64,")
    raw = base64.b64decode(uris[0].split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"  # PNG 魔数


def test_pdf_to_png_data_uris_bad_bytes():
    assert pdf_to_png_data_uris(b"not a pdf") == []
    assert pdf_to_png_data_uris(b"") == []


def test_build_vision_messages_shape():
    parts = [
        {
            "label": "申请人身份证正面",
            "data_uri": "data:image/jpeg;base64,xxx",
            "mime": "image/jpeg",
        }
    ]
    msgs = build_vision_messages({"案件基本信息": {"案由": "劳动报酬争议"}}, parts)
    assert msgs[0]["role"] == "system"
    assert "图片核对" in msgs[0]["content"]

    user = msgs[1]
    assert user["role"] == "user"
    assert isinstance(user["content"], list)
    text_part = user["content"][0]
    assert text_part["type"] == "text"
    assert "劳动报酬争议" in text_part["text"]
    img_part = user["content"][1]
    assert img_part == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,xxx"}}
