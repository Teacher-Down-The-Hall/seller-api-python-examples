"""Small standard-library client used by the Seller API examples.

The client keeps the PAT in memory only. It never includes credentials in URLs,
error messages, or printed output, and it never retries requests automatically.
"""

from __future__ import annotations

import getpass
import time
import json
import os
import socket
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://api.teacherdownthehall.com"
JsonObject = dict[str, Any]


class TDTHAPIError(Exception):
    """Safe API error containing status and sanitized server detail only."""

    def __init__(self, status_code: int, message: str, *, code: str | None = None, retry_after: str | None = None):
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after
        suffix = f" ({code})" if code else ""
        super().__init__(f"Seller API request failed with HTTP {status_code}{suffix}: {message}")


class TDTHTimeoutError(TDTHAPIError):
    def __init__(self):
        super().__init__(0, "The Seller API request timed out.", code="timeout")


class TDTHConnectionError(TDTHAPIError):
    def __init__(self):
        super().__init__(0, "Could not connect to the Seller API.", code="connection_error")


def _error_from_response(status_code: int, payload: Any, retry_after: str | None, token: str) -> TDTHAPIError:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    code = detail.get("code") if isinstance(detail, dict) and isinstance(detail.get("code"), str) else None
    message = detail.get("message") if isinstance(detail, dict) and isinstance(detail.get("message"), str) else None
    if not message and isinstance(detail, str):
        message = detail
    if not message:
        message = "The Seller API returned an error."
    message = message.replace(token, "[redacted]")
    return TDTHAPIError(status_code, message, code=code, retry_after=retry_after)


class TDTHSellerClient:
    def __init__(self, *, token: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 15.0):
        if not token or not token.strip():
            raise ValueError("A Seller API token is required.")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("API base URL must be an absolute HTTP(S) URL without query parameters.")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero.")
        self._token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_environment(cls, *, timeout: float = 15.0, prompt: bool = True) -> "TDTHSellerClient":
        token = os.environ.get("TDTH_SELLER_API_TOKEN")
        if not token and prompt:
            token = getpass.getpass("TDTH Seller API token: ")
        if not token:
            raise ValueError("Set TDTH_SELLER_API_TOKEN or enter the token when prompted.")
        base_url = os.environ.get("TDTH_SELLER_API_BASE_URL") or os.environ.get("TDTH_API_BASE_URL") or DEFAULT_BASE_URL
        return cls(token=token, base_url=base_url, timeout=timeout)

    def list_products(self, *, limit: int = 24, offset: int = 0, search: str | None = None, status: str | None = None) -> JsonObject:
        query: dict[str, str | int] = {"limit": limit, "offset": offset}
        if search:
            query["search"] = search
        if status:
            query["status"] = status
        return self._request("GET", "/api/v1/seller/products", query=query)

    def get_taxonomy(self) -> JsonObject:
        return self._request("GET", "/api/v1/seller/taxonomy")

    def create_draft(self, *, idempotency_key: str, fields: Mapping[str, Any]) -> JsonObject:
        if not idempotency_key.strip():
            raise ValueError("An explicit idempotency key is required for draft creation.")
        return self._request("POST", "/api/v1/seller/products/drafts", body=fields, headers={"Idempotency-Key": idempotency_key})

    def update_draft(self, product_id: str, *, expected_revision: int, fields: Mapping[str, Any]) -> JsonObject:
        if expected_revision < 1:
            raise ValueError("expected_revision must be at least 1.")
        if "expected_revision" in fields:
            raise ValueError("Pass expected_revision separately.")
        return self._request("PATCH", f"/api/v1/seller/products/{product_id}", body={"expected_revision": expected_revision, **fields})

    def create_upload_session(self, *, product_id: str, purpose: str, filename: str, content_type: str, size_bytes: int, idempotency_key: str) -> JsonObject:
        if not product_id.strip():
            raise ValueError("An explicit product ID is required.")
        if not idempotency_key.strip():
            raise ValueError("An explicit idempotency key is required for upload creation.")
        return self._request(
            "POST",
            "/api/v1/seller/uploads",
            body={"product_id": product_id, "purpose": purpose, "filename": filename, "content_type": content_type, "size_bytes": size_bytes},
            headers={"Idempotency-Key": idempotency_key},
        )

    def upload_bytes(self, upload_url: str, data: bytes, *, content_type: str) -> None:
        """PUT bytes to the short-lived GCS URL without adding the PAT."""
        if not upload_url or not upload_url.startswith(("https://", "http://")):
            raise ValueError("The API did not return a valid upload destination.")
        request = Request(upload_url, data=data, headers={"Content-Type": content_type, "Content-Length": str(len(data))}, method="PUT")
        try:
            with urlopen(request, timeout=max(self.timeout, 900.0)):
                return
        except HTTPError as exc:
            raise TDTHAPIError(exc.code, "The storage upload failed.", code="storage_upload_failed") from None
        except (socket.timeout, TimeoutError):
            raise TDTHTimeoutError() from None
        except URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise TDTHTimeoutError() from None
            raise TDTHConnectionError() from None

    def complete_upload(self, upload_id: str) -> JsonObject:
        return self._request("POST", f"/api/v1/seller/uploads/{upload_id}/complete")

    def get_upload_status(self, upload_id: str) -> JsonObject:
        return self._request("GET", f"/api/v1/seller/uploads/{upload_id}")

    def wait_for_resource_scan(self, upload_id: str, *, timeout: float = 300.0, initial_delay: float = 2.0, max_delay: float = 20.0) -> JsonObject:
        if timeout <= 0 or initial_delay <= 0 or max_delay <= 0:
            raise ValueError("Polling timeout and delays must be positive.")
        deadline = time.monotonic() + timeout
        delay = initial_delay
        while True:
            status = self.get_upload_status(upload_id)
            scan_status = status.get("scan_status")
            if scan_status in {"clean", "rejected", "failed"}:
                return status
            if time.monotonic() >= deadline:
                raise TDTHTimeoutError()
            time.sleep(min(delay, max(0.0, deadline - time.monotonic())))
            delay = min(max_delay, delay * 2)

    def attach_product_asset(self, product_id: str, upload_id: str) -> JsonObject:
        return self._request("POST", f"/api/v1/seller/products/{product_id}/assets", body={"upload_id": upload_id})

    def list_product_assets(self, product_id: str) -> JsonObject:
        return self._request("GET", f"/api/v1/seller/products/{product_id}/assets")

    def _request(self, method: str, path: str, *, query: Mapping[str, str | int] | None = None, body: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None) -> JsonObject:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request_headers = {"Accept": "application/json", "Authorization": f"Bearer {self._token}"}
        if headers:
            request_headers.update(headers)
        data = None
        if body is not None:
            request_headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = Request(url, data=data, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            raise _error_from_response(exc.code, payload, exc.headers.get("Retry-After"), self._token) from None
        except (socket.timeout, TimeoutError):
            raise TDTHTimeoutError() from None
        except URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise TDTHTimeoutError() from None
            raise TDTHConnectionError() from None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TDTHAPIError(502, "The Seller API returned invalid JSON.", code="invalid_response") from exc
        if not isinstance(payload, dict):
            raise TDTHAPIError(502, "The Seller API returned an unexpected response.", code="invalid_response")
        return payload


def print_error(error: Exception) -> None:
    if isinstance(error, TDTHAPIError):
        print(str(error), file=__import__("sys").stderr)
    else:
        print(f"Error: {error}", file=__import__("sys").stderr)
