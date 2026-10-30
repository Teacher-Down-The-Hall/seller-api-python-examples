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
    def __init__(self, payload: dict, *, status: int = 200):
        self.payload = payload
        self.status = status

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


def test_merchandising_methods_use_public_routes_and_exact_request_bodies():
    responses = [
        FakeResponse({"items": []}),
        FakeResponse({"id": "filter", "name": "Grade", "position": 0}),
        FakeResponse({"id": "filter", "name": "Updated", "position": 0}),
        FakeResponse({}, status=204),
        FakeResponse({"items": []}),
        FakeResponse({"product_id": "product", "filter_ids": [], "revision": 2}),
        FakeResponse({"product_id": "product", "filter_ids": ["filter"], "revision": 3}),
        FakeResponse({"product_id": "product", "related_products": [], "revision": 3}),
        FakeResponse({"product_id": "product", "related_products": [{"id": "related", "position": 0}], "revision": 4}),
    ]
    opener = Mock(side_effect=responses)
    with patch("tdth_client.urlopen", opener):
        client = TDTHSellerClient(token="token")
        client.list_buyer_filters()
        client.create_buyer_filter("Grade")
        client.update_buyer_filter("filter", "Updated")
        assert client.delete_buyer_filter("filter", confirm=True) == {}
        client.order_buyer_filters(["filter"])
        client.get_product_buyer_filters("product")
        client.set_product_buyer_filters("product", expected_revision=2, filter_ids=["filter"])
        client.get_product_related_resources("product")
        client.set_product_related_resources("product", expected_revision=3, related_product_ids=["related"])

    requests = [call.args[0] for call in opener.call_args_list]
    assert [request.method for request in requests] == ["GET", "POST", "PATCH", "DELETE", "PUT", "GET", "PUT", "GET", "PUT"]
    assert json.loads(requests[1].data) == {"name": "Grade"}
    assert json.loads(requests[3].data) == {"confirm": True}
    assert json.loads(requests[4].data) == {"filter_ids": ["filter"]}
    assert json.loads(requests[6].data) == {"expected_revision": 2, "filter_ids": ["filter"]}
    assert json.loads(requests[8].data) == {"expected_revision": 3, "related_product_ids": ["related"]}
    assert requests[0].full_url.endswith("/api/v1/seller/store/buyer-filters")
    assert requests[5].full_url.endswith("/api/v1/seller/products/product/buyer-filters")
    assert requests[7].full_url.endswith("/api/v1/seller/products/product/related-resources")


def test_merchandising_writes_require_positive_revision_before_network():
    opener = Mock()
    client = TDTHSellerClient(token="token")
    with patch("tdth_client.urlopen", opener), pytest.raises(ValueError):
        client.set_product_buyer_filters("product", expected_revision=0, filter_ids=[])
    with patch("tdth_client.urlopen", opener), pytest.raises(ValueError):
        client.set_product_related_resources("product", expected_revision=0, related_product_ids=[])
    opener.assert_not_called()


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


def test_merchandising_write_example_is_dry_run_without_network_requests(monkeypatch, capsys):
    import runpy

    examples = Path(__file__).parents[1]
    opener = Mock(side_effect=AssertionError("dry-run must not access the network"))
    with patch("tdth_client.urlopen", opener):
        monkeypatch.setattr(sys, "argv", ["10_product_merchandising.py", "product-id", "--filter-id", "filter-id"])
        result = runpy.run_path(str(examples / "10_product_merchandising.py"), run_name="dry_run_merchandising")['main']()
    assert result == 0
    assert "DRY RUN" in capsys.readouterr().out
    opener.assert_not_called()


class BuyerFilterExampleClient:
    def __init__(self, *, fail_create: bool = False):
        self.calls = []
        self.filter_ids = ["existing-filter"]
        self.fail_create = fail_create

    def list_buyer_filters(self):
        self.calls.append(("list",))
        return {"items": [{"id": item_id, "name": item_id, "position": position} for position, item_id in enumerate(self.filter_ids)]}

    def create_buyer_filter(self, name):
        self.calls.append(("create", name))
        if self.fail_create:
            raise RuntimeError("simulated create failure")
        self.filter_ids.append("temporary-filter")
        return {"id": "temporary-filter", "name": name, "position": len(self.filter_ids) - 1}

    def update_buyer_filter(self, filter_id, name):
        self.calls.append(("update", filter_id, name))
        return {"id": filter_id, "name": name, "position": 0}

    def order_buyer_filters(self, filter_ids):
        self.calls.append(("order", filter_ids))
        self.filter_ids = list(filter_ids)
        return {"items": [{"id": item_id, "position": position} for position, item_id in enumerate(self.filter_ids)]}

    def delete_buyer_filter(self, filter_id, *, confirm):
        self.calls.append(("delete", filter_id, confirm))
        self.filter_ids.remove(filter_id)
        return {}


def _run_buyer_filter_example(monkeypatch, fake_client, *arguments):
    import runpy

    examples = Path(__file__).parents[1]
    monkeypatch.setattr(sys, "argv", ["09_buyer_filters.py", *arguments])
    with patch("tdth_client.TDTHSellerClient.from_environment", return_value=fake_client):
        return runpy.run_path(str(examples / "09_buyer_filters.py"), run_name="buyer_filter_example")['main']()


def test_buyer_filter_example_default_invocation_reads_only(monkeypatch, capsys):
    fake_client = BuyerFilterExampleClient()
    assert _run_buyer_filter_example(monkeypatch, fake_client) == 0
    assert fake_client.calls == [("list",)]
    assert "completed" not in capsys.readouterr().out.lower()


def test_buyer_filter_example_mutations_require_execute_and_confirm(monkeypatch):
    fake_client = BuyerFilterExampleClient()
    assert _run_buyer_filter_example(monkeypatch, fake_client, "--execute") == 2
    assert fake_client.calls == []

    fake_client = BuyerFilterExampleClient()
    assert _run_buyer_filter_example(monkeypatch, fake_client, "--confirm") == 0
    assert fake_client.calls == [("list",)]


def test_buyer_filter_example_confirmed_flow_creates_updates_orders_and_deletes(monkeypatch, capsys):
    fake_client = BuyerFilterExampleClient()
    assert _run_buyer_filter_example(monkeypatch, fake_client, "--execute", "--confirm") == 0
    operation_names = [call[0] for call in fake_client.calls]
    assert operation_names == ["list", "create", "update", "list", "order", "delete", "list"]
    assert fake_client.calls[-2] == ("delete", "temporary-filter", True)
    assert "completed" in capsys.readouterr().out.lower()


def test_buyer_filter_example_failure_is_nonzero_without_success_message(monkeypatch, capsys):
    fake_client = BuyerFilterExampleClient(fail_create=True)
    assert _run_buyer_filter_example(monkeypatch, fake_client, "--execute", "--confirm") == 1
    output = capsys.readouterr()
    assert "completed" not in output.out.lower()
    assert "simulated create failure" in output.err
