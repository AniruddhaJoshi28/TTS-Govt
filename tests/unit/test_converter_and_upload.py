import io
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image
import pytest
from fastapi.testclient import TestClient

from apps.api import main
from services.document_ingestion.converter import (
    ALLOWED_EXTENSIONS,
    ConversionError,
    UnsupportedFormat,
    detect_language,
    detect_type,
    to_pdf,
)
from services.document_ingestion.corpus import build_document, save
from tests.helpers import make_pdf
from tests.unit.test_corpus import FakeOcr, entry

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def isolated_corpus(tmp_path, monkeypatch):
    doc = build_document(
        entry(id="seed-doc"),
        make_pdf("महाराष्ट्र शासन निर्णय"),
        "aa" * 32,
        datetime(2026, 10, 19, tzinfo=timezone.utc),
        FakeOcr("महाराष्ट्र शासन निर्णय"),
    )
    save(doc, tmp_path)
    monkeypatch.setattr(main.rt, "corpus_dir", tmp_path)
    monkeypatch.setattr(main, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(main, "FEEDBACK_FILE", tmp_path / "feedback.jsonl")
    monkeypatch.setattr(main.rt, "llm", None)
    monkeypatch.setattr(main.rt, "tts", None)
    monkeypatch.delenv("API_KEY", raising=False)
    main.rt.reload()
    yield


# -- Converter unit tests -----------------------------------------------------

def test_detect_type_by_extension():
    assert detect_type("sample.pdf", b"%PDF-") == "pdf"
    assert detect_type("notes.txt", b"plain text") == "txt"
    assert detect_type("letter.docx", b"PK\x03\x04") == "docx"
    assert detect_type("memo.rtf", b"{\\rtf1") == "rtf"
    assert detect_type("scan.png", b"\x89PNG") == "image"
    assert detect_type("photo.jpg", b"\xff\xd8") == "image"
    assert detect_type("doc.odt", b"PK\x03\x04") == "odt"


def test_detect_type_sniffs_magic_bytes():
    assert detect_type("unknown_name", b"%PDF-1.7") == "pdf"
    assert detect_type("unknown_name", b"\x89PNG\r\n\x1a\n") == "image"
    assert detect_type("unknown_name", b"\xff\xd8\xff\xe0") == "image"


def test_detect_type_unsupported_format():
    with pytest.raises(UnsupportedFormat):
        detect_type("malware.exe", b"MZ\x90\x00")
    with pytest.raises(UnsupportedFormat):
        detect_type("data.bin", b"\x00\x01\x02\x03")


def test_txt_to_pdf_conversion():
    text = "महाराष्ट्र शासन\nसार्वजनिक आरोग्य विभाग\n\nनवीन आदेश दिनांक १५ ऑगस्ट २०२६."
    pdf_bytes = to_pdf("order.txt", text.encode("utf-8"))
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 200


def test_image_to_pdf_conversion():
    img = Image.new("RGB", (200, 200), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    pdf_bytes = to_pdf("scan.png", png_bytes)
    assert pdf_bytes.startswith(b"%PDF-")


def test_empty_content_rejected():
    with pytest.raises(ConversionError, match="empty"):
        to_pdf("empty.txt", b"")


def test_oversized_file_rejected():
    huge = b"x" * (51 * 1024 * 1024)
    with pytest.raises(ConversionError, match="too large"):
        to_pdf("huge.txt", huge)


def test_detect_language_marathi_vs_hindi():
    marathi = "महाराष्ट्र शासनाचा निर्णय आहे. कर्मचाऱ्यांना नवीन लाभ देण्यात येत आहेत."
    hindi = "मध्य प्रदेश सरकार का आदेश है। सभी कर्मचारियों को न्यूनतम वेतन दिया जाएगा।"
    odia = "ଓଡ଼ିଶା ସରକାରଙ୍କ ଆଦେଶ ଅନୁଯାୟୀ ଏହି ନିଷ୍ପତ୍ତି ନିଆଯାଇଛି।"
    english = "Government resolution regarding the revised minimum wages order 2026."

    assert detect_language(marathi) == "mr"
    assert detect_language(hindi) == "hi"
    assert detect_language(odia) == "or"
    assert detect_language(english) == "en"


# -- API upload endpoint integration tests ------------------------------------

def test_upload_formats_endpoint():
    res = client.get("/api/v1/upload/formats")
    assert res.status_code == 200
    data = res.json()["data"]
    assert ".pdf" in data["extensions"]
    assert ".docx" in data["extensions"]
    assert ".txt" in data["extensions"]
    assert data["max_size_mb"] == 50


def test_upload_txt_document_success():
    content = "Government Resolution on Minimum Wages 2026.\nAll workers shall receive revised rates."
    files = {"file": ("order.txt", io.BytesIO(content.encode("utf-8")), "text/plain")}
    res = client.post("/api/v1/upload", files=files)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["filename"] == "order.txt"
    assert data["original_format"] == "txt"
    assert data["pages"] >= 1
    assert data["passages"] >= 1
    assert data["state"] == "UP"

    # Verify the document is queryable in the documents list
    list_res = client.get("/api/v1/documents?state=UP")
    assert list_res.status_code == 200
    uploaded_docs = list_res.json()["data"]
    assert any(d["id"] == data["document_id"] for d in uploaded_docs)

    # Verify detail is retrievable
    detail_res = client.get(f"/api/v1/documents/{data['document_id']}")
    assert detail_res.status_code == 200
    detail = detail_res.json()["data"]
    assert len(detail["passages"]) >= 1


def test_upload_image_document_success():
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    files = {"file": ("order.jpg", io.BytesIO(buf.getvalue()), "image/jpeg")}
    res = client.post("/api/v1/upload", files=files)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["original_format"] == "image"
    assert data["pages"] == 1


def test_upload_duplicate_document_returns_existing():
    content = "A unique test document for checking duplicate detection idempotency."
    files = {"file": ("unique_order.txt", io.BytesIO(content.encode("utf-8")), "text/plain")}
    res1 = client.post("/api/v1/upload", files=files)
    assert res1.status_code == 200

    # Upload again with exact same content
    files2 = {"file": ("unique_order.txt", io.BytesIO(content.encode("utf-8")), "text/plain")}
    res2 = client.post("/api/v1/upload", files=files2)
    assert res2.status_code == 200
    assert "already uploaded" in res2.json()["data"]["message"]
    assert res2.json()["data"]["document_id"] == res1.json()["data"]["document_id"]


def test_upload_empty_file_rejected():
    files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
    res = client.post("/api/v1/upload", files=files)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "empty_file"


def test_upload_unsupported_file_rejected():
    files = {"file": ("executable.exe", io.BytesIO(b"MZ1234567890"), "application/octet-stream")}
    res = client.post("/api/v1/upload", files=files)
    assert res.status_code == 415
    assert res.json()["error"]["code"] == "unsupported_format"


def test_reload_endpoint():
    res = client.post("/api/v1/reload")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["reloaded"] is True
    assert data["documents"] >= 1
