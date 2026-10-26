"""Update an unpublished draft with explicit revision protection."""

from __future__ import annotations

import argparse

from tdth_client import TDTHSellerClient, print_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product_id")
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--title", default="Updated API example draft")
    parser.add_argument("--execute", action="store_true", help="Actually update the unpublished draft.")
    parser.add_argument("--confirm", action="store_true", help="Confirm that the configured seller account will change.")
    args = parser.parse_args()
    fields = {"title": args.title}
    if not args.execute:
        print("DRY RUN: no request sent and no draft changed.")
        print(f"Would PATCH the owned unpublished product {args.product_id} at expected revision {args.expected_revision}.")
        print("Re-run with --execute --confirm after checking the current revision.")
        return 0
    if not args.confirm:
        print("Refusing to update a draft: add --confirm after reviewing the warning.")
        return 2
    print("WARNING: this will update one owned unpublished draft and will not publish it.")
    try:
        result = TDTHSellerClient.from_environment().update_draft(args.product_id, expected_revision=args.expected_revision, fields=fields)
    except Exception as error:
        print_error(error)
        return 1
    print(f"Updated unpublished draft {result.get('id')} to revision {result.get('revision')}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
