"""Inspect one owned upload session without exposing upload credentials."""

from __future__ import annotations

import argparse

from tdth_client import TDTHSellerClient, print_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upload_id", help="Upload-session UUID.")
    args = parser.parse_args()
    try:
        status = TDTHSellerClient.from_environment(timeout=30.0).get_upload_status(args.upload_id)
    except Exception as error:
        print_error(error)
        return 1
    for field in ("id", "product_id", "purpose", "status", "filename", "content_type", "size_bytes", "expires_at", "scan_status"):
        if field in status:
            print(f"{field}: {status[field]}")
    print(f"attachment_ready: {status.get('status') == 'completed' and status.get('scan_status') in {'clean', 'not_required'}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
