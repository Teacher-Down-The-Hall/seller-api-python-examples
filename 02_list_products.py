"""List the authenticated seller's products without changing data."""

from __future__ import annotations

import argparse

from tdth_client import TDTHSellerClient, print_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=24, choices=range(1, 101))
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--search")
    parser.add_argument("--status", choices=("draft", "published", "unpublished", "archived", "suspended"))
    args = parser.parse_args()
    try:
        result = TDTHSellerClient.from_environment().list_products(limit=args.limit, offset=args.offset, search=args.search, status=args.status)
    except Exception as error:
        print_error(error)
        return 1
    print(f"Products {result.get('offset', 0) + 1}–{result.get('offset', 0) + len(result.get('items', []))} of {result.get('total', 0)}")
    for item in result.get("items", []):
        print(f"- {item.get('title', '(untitled)')} | status={item.get('status')} | revision={item.get('revision')} | id={item.get('id')}")
    if result.get("next_offset") is not None:
        print(f"Next offset: {result['next_offset']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
