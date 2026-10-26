from __future__ import annotations

import json
import socket
import sys
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest

from tdth_client import TDTHAPIError, TDTHSellerClient, TDTHTimeoutError
from upload_fixtures import make_pdf, make_png


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class EmptyResponse(FakeResponse):
    def read(self):
        return b""


def test_get_builds_bearer_request_and_parses_product_list():
    opener = Mock(return_value=FakeResponse({"items": [], "total": 0, "limit": 24, "offset": 0, "next_offset": None}))
    with patch("tdth_client.urlopen", opener):
        result = TDTHSellerClient(token="secret-pat").list_products(status="draft")
    request = opener.call_args.args[0]
    assert result["total"] == 0
    assert request.get_header("Authorization") == "Bearer secret-pat"
    assert "secret-pat" not in request.full_url
    assert "status=draft" in request.full_url


def test_taxonomy_response_is_parsed_without_extra_requests():
    opener = Mock(return_value=FakeResponse({"grade_levels": [], "subjects": [], "resource_types": []}))
    with patch("tdth_client.urlopen", opener):
        assert TDTHSellerClient(token="token").get_taxonomy()["subjects"] == []
    assert opener.call_count == 1


def test_create_draft_requires_idempotency_and_sends_exact_contract():
    opener = Mock(return_value=FakeResponse({"id": "product", "status": "draft", "revision": 1}))
    with patch("tdth_client.urlopen", opener):
        TDTHSellerClient(token="token").create_draft(idempotency_key="stable-001", fields={"title": "Draft", "is_free": True, "price_cents": 0})
    request = opener.call_args.args[0]
    assert request.method == "POST"
    assert request.get_header("Idempotency-key") == "stable-001"
    assert json.loads(request.data) == {"title": "Draft", "is_free": True, "price_cents": 0}


def test_update_requires_revision_and_never_publishes_or_deletes():
    opener = Mock(return_value=FakeResponse({"id": "product", "status": "draft", "revision": 2}))
    with patch("tdth_client.urlopen", opener):
        TDTHSellerClient(token="token").update_draft("product-id", expected_revision=1, fields={"title": "Updated"})
    request = opener.call_args.args[0]
    assert request.method == "PATCH"
    assert json.loads(request.data) == {"expected_revision": 1, "title": "Updated"}
    assert "/publish" not in request.full_url
    assert request.method != "DELETE"


def test_draft_write_rejects_missing_idempotency_before_network():
    opener = Mock()
    with patch("tdth_client.urlopen", opener):
        with pytest.raises(ValueError):
            TDTHSellerClient(token="token").create_draft(idempotency_key="", fields={"title": "Draft"})
    opener.assert_not_called()


def test_safe_http_error_never_contains_token_or_response_body():
    body = {"detail": {"code": "missing_scope", "message": "draft writes are disabled"}, "secret": "do-not-show"}
    error = HTTPError("https://api.example", 403, "Forbidden", {}, BytesIO(json.dumps(body).encode()))
    with patch("tdth_client.urlopen", side_effect=error):
        with pytest.raises(TDTHAPIError) as raised:
            TDTHSellerClient(token="do-not-leak").get_taxonomy()
    assert raised.value.status_code == 403
    assert "do-not-leak" not in str(raised.value)
    assert "do-not-show" not in str(raised.value)


def test_timeout_and_connection_errors_are_safe():
    with patch("tdth_client.urlopen", side_effect=socket.timeout()):
        with pytest.raises(TDTHTimeoutError):
            TDTHSellerClient(token="token", timeout=1).get_taxonomy()
    with patch("tdth_client.urlopen", side_effect=URLError("offline")):
        with pytest.raises(TDTHAPIError) as raised:
            TDTHSellerClient(token="token").get_taxonomy()
    assert "offline" not in str(raised.value)


def test_upload_lifecycle_uses_json_authorization_then_raw_put_without_bearer_on_storage():
    opener = Mock(side_effect=[FakeResponse({"id": "upload-id", "upload_url": "https://storage.invalid/signed", "scan_status": "not_required"}), EmptyResponse({})])
    with patch("tdth_client.urlopen", opener):
        client = TDTHSellerClient(token="secret-pat")
        session = client.create_upload_session(product_id="product-id", purpose="cover", filename="cover.png", content_type="image/png", size_bytes=len(make_png()), idempotency_key="image-001")
        client.upload_bytes(session["upload_url"], make_png(), content_type="image/png")
    create_request, storage_request = opener.call_args_list[0].args[0], opener.call_args_list[1].args[0]
    assert create_request.method == "POST"
    assert create_request.get_header("Authorization") == "Bearer secret-pat"
    assert create_request.get_header("Idempotency-key") == "image-001"
    assert json.loads(create_request.data)["purpose"] == "cover"
    assert storage_request.method == "PUT"
    assert storage_request.get_header("Authorization") is None
    assert storage_request.get_header("Content-type") == "image/png"
    assert storage_request.data == make_png()
    assert "signed" not in str(opener.call_args_list[0])


def test_resource_polling_returns_only_terminal_scan_states():
    client = TDTHSellerClient(token="token")
    with patch.object(client, "get_upload_status", side_effect=[{"scan_status": "pending"}, {"scan_status": "clean"}]), patch("tdth_client.time.sleep") as sleep:
        result = client.wait_for_resource_scan("upload-id", timeout=10, initial_delay=1, max_delay=2)
    assert result["scan_status"] == "clean"
    sleep.assert_called_once()


def test_storage_failure_is_sanitized_and_never_contains_signed_url_or_token():
    opener = Mock(side_effect=HTTPError("https://storage.invalid/signed", 403, "Forbidden", {}, BytesIO(b"private response")))
    with patch("tdth_client.urlopen", opener):
        with pytest.raises(TDTHAPIError) as raised:
            TDTHSellerClient(token="secret-pat").upload_bytes("https://storage.invalid/signed", b"bytes", content_type="application/pdf")
    assert raised.value.code == "storage_upload_failed"
    assert "storage.invalid" not in str(raised.value)
    assert "secret-pat" not in str(raised.value)


def test_synthetic_fixtures_have_expected_signatures():
    assert make_png().startswith(b"\x89PNG\r\n\x1a\n")
    assert len(make_png()) > 100
    assert make_pdf().startswith(b"%PDF-1.4")
    assert b"/Type /Page" in make_pdf()
    assert b"/Count 1" in make_pdf()
    assert b"startxref" in make_pdf()


@pytest.mark.skipif(shutil.which("gs") is None, reason="Ghostscript is not installed")
def test_synthetic_pdf_is_accepted_as_a_readable_one_page_document(tmp_path):
    fixture = tmp_path / "fixture.pdf"
    output = tmp_path / "normalized.pdf"
    fixture.write_bytes(make_pdf())
    result = subprocess.run(
        ["gs", "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite", f"-sOutputFile={output}", str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_bytes().startswith(b"%PDF")


def test_upload_examples_are_dry_run_without_network_requests(monkeypatch, capsys):
    import runpy

    examples = Path(__file__).parents[1]
    opener = Mock(side_effect=AssertionError("dry-run must not access the network"))
    with patch("tdth_client.urlopen", opener):
        for script in ("06_upload_product_image.py", "07_upload_resource.py"):
            monkeypatch.setattr(sys, "argv", [script, "--product-id", "product-id", "--idempotency-key", "example-001"])
            result = runpy.run_path(str(examples / script), run_name=f"dry_run_{script}")["main"]()
            assert result == 0
    assert "DRY RUN" in capsys.readouterr().out
    opener.assert_not_called()
