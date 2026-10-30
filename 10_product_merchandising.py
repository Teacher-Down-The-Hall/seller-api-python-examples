"""Read or explicitly replace buyer-filter and related-resource assignments."""

from __future__ import annotations

import argparse

from tdth_client import TDTHAPIError, TDTHSellerClient, print_error


def _print_state(filters: dict, related: dict) -> None:
    print(f"Product revision: {filters.get('revision')}")
    print(f"Buyer-filter IDs: {filters.get('filter_ids', [])}")
    print("Related resources:")
    for item in related.get("related_products", []):
        print(f"  {item.get('position')}: {item.get('title')} ({item.get('id')})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product_id")
    parser.add_argument("--filter-id", action="append", default=[], help="A complete replacement buyer-filter ID; repeat to preserve order.")
    parser.add_argument("--related-product-id", action="append", default=[], help="A complete replacement related-product ID; repeat to preserve order (maximum four).")
    parser.add_argument("--clear-filters", action="store_true", help="Explicitly clear all buyer-filter assignments.")
    parser.add_argument("--clear-related", action="store_true", help="Explicitly clear all related resources.")
    parser.add_argument("--expected-revision", type=int, help="Optional revision to use instead of reading the current revision immediately before writing.")
    parser.add_argument("--execute", action="store_true", help="Actually replace the requested assignments.")
    parser.add_argument("--confirm", action="store_true", help="Confirm that the owned product may be changed.")
    args = parser.parse_args()

    if args.clear_filters and args.filter_id:
        parser.error("Use --clear-filters or --filter-id, not both.")
    if args.clear_related and args.related_product_id:
        parser.error("Use --clear-related or --related-product-id, not both.")
    if len(args.related_product_id) > 4:
        parser.error("The Seller API permits at most four related resources.")
    if args.execute and not (args.filter_id or args.related_product_id or args.clear_filters or args.clear_related):
        parser.error("Choose an explicit filter or related-resource replacement, or use the default read-only mode.")
    if not args.execute and (args.filter_id or args.related_product_id or args.clear_filters or args.clear_related):
        print("DRY RUN: no request sent and no assignments changed.")
        print(f"Would update merchandising assignments for owned product {args.product_id}.")
        print("Re-run with --execute --confirm after reviewing the replacement lists.")
        return 0
    if not args.execute:
        try:
            client = TDTHSellerClient.from_environment()
            filters = client.get_product_buyer_filters(args.product_id)
            related = client.get_product_related_resources(args.product_id)
        except Exception as error:
            print_error(error)
            return 1
        _print_state(filters, related)
        return 0
    if not args.confirm:
        print("Refusing to change product merchandising: add --confirm after reviewing the warning.")
        return 2
    if args.expected_revision is not None and args.expected_revision < 1:
        parser.error("--expected-revision must be at least 1.")

    try:
        client = TDTHSellerClient.from_environment()
        current_filters = client.get_product_buyer_filters(args.product_id)
        revision = args.expected_revision if args.expected_revision is not None else int(current_filters["revision"])
        filter_result = current_filters
        related_result = current_filters
        final_revision = revision
        if args.filter_id or args.clear_filters:
            filter_ids = [] if args.clear_filters else args.filter_id
            filter_result = client.set_product_buyer_filters(args.product_id, expected_revision=revision, filter_ids=filter_ids)
            revision = int(filter_result["revision"])
            final_revision = revision
        if args.related_product_id or args.clear_related:
            related_ids = [] if args.clear_related else args.related_product_id
            related_result = client.set_product_related_resources(args.product_id, expected_revision=revision, related_product_ids=related_ids)
            final_revision = int(related_result["revision"])
        verified_filters = client.get_product_buyer_filters(args.product_id)
        verified_related = client.get_product_related_resources(args.product_id)
        expected_filters = [] if args.clear_filters else args.filter_id if args.filter_id else verified_filters.get("filter_ids", [])
        expected_related = [] if args.clear_related else args.related_product_id if args.related_product_id else [item["id"] for item in verified_related.get("related_products", [])]
        if args.filter_id or args.clear_filters:
            if verified_filters.get("filter_ids", []) != expected_filters:
                raise RuntimeError("Buyer-filter assignment was not preserved by a fresh read.")
        if args.related_product_id or args.clear_related:
            if [item["id"] for item in verified_related.get("related_products", [])] != expected_related:
                raise RuntimeError("Related-resource ordering was not preserved by a fresh read.")
    except TDTHAPIError as error:
        if error.status_code == 409:
            print("The product revision changed. Read the product again and review the new state before retrying.")
        print_error(error)
        return 1
    except Exception as error:
        print_error(error)
        return 1
    print("Product merchandising assignments updated without changing publication status.")
    print(f"New revision: {final_revision}")
    print(f"Buyer-filter IDs: {verified_filters.get('filter_ids', [])}")
    print(f"Related resource count: {len(verified_related.get('related_products', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
