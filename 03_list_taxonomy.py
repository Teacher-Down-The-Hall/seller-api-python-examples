"""Read active TDTH grade levels, subjects, and resource types."""

from __future__ import annotations

from tdth_client import TDTHSellerClient, print_error


def main() -> int:
    try:
        result = TDTHSellerClient.from_environment().get_taxonomy()
    except Exception as error:
        print_error(error)
        return 1
    for key in ("grade_levels", "subjects", "resource_types"):
        values = result.get(key, [])
        print(f"{key.replace('_', ' ').title()} ({len(values)}):")
        print("  " + ", ".join(item.get("name", item.get("slug", "")) for item in values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
