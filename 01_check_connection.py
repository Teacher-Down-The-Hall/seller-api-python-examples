"""Make a small read-only authenticated Seller API request."""

from __future__ import annotations

from tdth_client import TDTHSellerClient, print_error


def main() -> int:
    try:
        result = TDTHSellerClient.from_environment().list_products(limit=1)
    except Exception as error:
        print_error(error)
        return 1
    print(f"Seller API connection succeeded. Products visible to this seller: {result.get('total', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
