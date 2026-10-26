"""Upload, scan, and attach one synthetic PDF to an owned unpublished product."""

from __future__ import annotations

import argparse
import hashlib

from tdth_client import TDTHSellerClient, print_error
from upload_fixtures import make_pdf


def _asset_summary(asset: dict) -> str:
    fields = ("id", "kind", "original_filename", "mime_type", "size_bytes", "width", "height")
    return ", ".join(f"{field}={asset[field]}" for field in fields if field in asset)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-id", required=True, help="UUID of an owned unpublished product.")
    parser.add_argument("--idempotency-key", required=True, help="Stable key to safely retry this exact upload authorization.")
    parser.add_argument("--scan-timeout", type=float, default=300.0, help="Maximum seconds to wait for a clean scan (default: 300).")
    parser.add_argument("--execute", action="store_true", help="Perform the upload and attachment.")
    parser.add_argument("--confirm", action="store_true", help="Confirm that one scanned resource will be attached to the owned unpublished product.")
    args = parser.parse_args()
    data = make_pdf()
    digest = hashlib.sha256(data).hexdigest()
    print(f"Synthetic PDF: {len(data)} bytes, SHA-256 {digest}")
    if not args.execute:
        print("DRY RUN: no API, storage, task, or product mutation request sent.")
        print(f"Would create a resource upload for owned unpublished product {args.product_id}, wait for scan_status=clean, then attach it.")
        print("Re-run with --execute --confirm after reviewing the product and key.")
        return 0
    if not args.confirm:
        print("Refusing resource upload: add --confirm after reviewing the warning.")
        return 2
    if args.scan_timeout <= 0:
        print("Refusing resource upload: --scan-timeout must be positive.")
        return 2
    print("WARNING: this will upload, scan, and attach one private resource to the specified owned unpublished product; it will not publish anything.")
    try:
        client = TDTHSellerClient.from_environment(timeout=30.0)
        session = client.create_upload_session(product_id=args.product_id, purpose="resource", filename="tdth-api-acceptance.pdf", content_type="application/pdf", size_bytes=len(data), idempotency_key=args.idempotency_key)
        print(f"Upload session: {session['id']}")
        upload_url = session.get("upload_url")
        if not isinstance(upload_url, str) or not upload_url:
            raise RuntimeError("The API did not return an upload destination.")
        client.upload_bytes(upload_url, data, content_type="application/pdf")
        completed = client.complete_upload(str(session["id"]))
        if completed.get("scan_status") not in {"pending", "clean"}:
            raise RuntimeError(f"Resource completion is not eligible for scanning: scan_status={completed.get('scan_status', 'unknown')}")
        status = completed if completed.get("scan_status") == "clean" else client.wait_for_resource_scan(str(session["id"]), timeout=args.scan_timeout)
        if status.get("scan_status") != "clean":
            raise RuntimeError(f"Resource is not eligible for attachment: scan_status={status.get('scan_status', 'unknown')}")
        asset = client.attach_product_asset(args.product_id, str(session["id"]))
        print(f"Attached scanned resource: {_asset_summary(asset)}")
        return 0
    except Exception as error:
        print_error(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
