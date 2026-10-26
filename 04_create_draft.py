"""Create an unpublished draft only when explicitly executed."""

from __future__ import annotations

import argparse

from tdth_client import TDTHSellerClient, print_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Actually create an unpublished draft.")
    parser.add_argument("--confirm", action="store_true", help="Confirm that the configured seller account will change.")
    parser.add_argument("--idempotency-key", help="Stable key to reuse if the request outcome is uncertain.")
    parser.add_argument("--title", default="API example draft")
    args = parser.parse_args()
    fields = {"title": args.title, "short_description": "A draft created by the TDTH Seller API example.", "description": "Review and complete this unpublished draft in TDTH.", "is_free": True, "price_cents": 0}
    key = args.idempotency_key or "<stable-key-required-for-execution>"
    if not args.execute:
        print("DRY RUN: no request sent and no draft created.")
        print(f"Would POST an unpublished draft with idempotency key {key!r} and title {args.title!r}.")
        print("Re-run with --execute --confirm and a stable --idempotency-key to create it.")
        return 0
    if not args.idempotency_key:
        print("Refusing to create a draft: provide a stable --idempotency-key for safe retries.")
        return 2
    if not args.confirm:
        print("Refusing to create a draft: add --confirm after reviewing the warning.")
        return 2
    print("WARNING: this will create one unpublished draft in the authenticated seller account.")
    try:
        result = TDTHSellerClient.from_environment().create_draft(idempotency_key=key, fields=fields)
    except Exception as error:
        print_error(error)
        return 1
    print(f"Created unpublished draft {result.get('id')} at revision {result.get('revision')}.")
    print("Publishing is not available through this example or the public Seller API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
