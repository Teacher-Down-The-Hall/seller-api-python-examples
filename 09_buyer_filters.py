"""List or explicitly manage the authenticated seller's buyer filters."""

from __future__ import annotations

import argparse
from uuid import uuid4

from tdth_client import TDTHSellerClient, print_error


def _ids(result: dict) -> list[str]:
    return [str(item["id"]) for item in result.get("items", [])]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Create, rename, reorder, and delete a temporary filter.")
    parser.add_argument("--confirm", action="store_true", help="Confirm that the authenticated store may be changed.")
    args = parser.parse_args()

    if not args.execute:
        try:
            filters = TDTHSellerClient.from_environment().list_buyer_filters()
        except Exception as error:
            print_error(error)
            return 1
        print(f"Buyer filters ({len(filters.get('items', []))}):")
        for item in filters.get("items", []):
            print(f"{item.get('position')}: {item.get('name')} ({item.get('id')})")
        return 0

    if not args.confirm:
        print("Refusing to change buyer filters: add --confirm after reviewing the warning.")
        return 2

    client = TDTHSellerClient.from_environment()
    original_ids: list[str] = []
    temporary_id: str | None = None
    cleanup_ok = True
    try:
        original_ids = _ids(client.list_buyer_filters())
        temporary_name = f"TDTH API example {uuid4().hex[:10]}"
        created = client.create_buyer_filter(temporary_name)
        temporary_id = str(created["id"])
        renamed = client.update_buyer_filter(temporary_id, f"{temporary_name} renamed")
        current_ids = _ids(client.list_buyer_filters())
        reordered = client.order_buyer_filters([item_id for item_id in current_ids if item_id != temporary_id] + [temporary_id])
        if _ids(reordered)[-1:] != [temporary_id]:
            raise RuntimeError("The API did not preserve the requested temporary-filter order.")
        print(f"Created, renamed, and reordered temporary buyer filter {temporary_id}.")
        print(f"Renamed filter: {renamed.get('name')}")
    except Exception as error:
        print_error(error)
        cleanup_ok = False
    finally:
        if temporary_id is not None:
            try:
                client.delete_buyer_filter(temporary_id, confirm=True)
                if _ids(client.list_buyer_filters()) != original_ids:
                    raise RuntimeError("Buyer-filter cleanup verification did not restore the original order.")
            except Exception as error:
                cleanup_ok = False
                print(f"WARNING: buyer-filter cleanup failed or could not be verified: {error}")
        elif original_ids:
            try:
                if _ids(client.list_buyer_filters()) != original_ids:
                    cleanup_ok = False
                    print("WARNING: buyer-filter state changed but no temporary filter ID was available for cleanup.")
            except Exception as error:
                cleanup_ok = False
                print(f"WARNING: buyer-filter cleanup verification failed: {error}")

    if not cleanup_ok:
        return 1
    print("Buyer-filter write example completed and original state was verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
