# TDTH Seller API Python examples

These small scripts demonstrate the public Seller API using a seller-issued
Personal Access Token (PAT). They are useful for a first integration check and
as readable starting points for tools such as Micah.

The examples use the production API by default:

```text
https://api.teacherdownthehall.com
```

For local development or mocked testing, set
`TDTH_SELLER_API_BASE_URL` (or the compatibility name
`TDTH_API_BASE_URL`) to the approved API origin.

## Get a PAT

Sign in to TDTH, then open **Seller Dashboard → Settings → API Access**. Choose
**New Token**, name it, select only the permissions you need, and copy
the raw token when it is shown. It is displayed once. Never put it in source
control, a URL, browser code, screenshots, logs, or a command-line argument.
Revoke it from the same page when it is no longer needed. PAT access requires
an active user, active seller profile, and active store; store publication and
Stripe payout onboarding are not required.

The scripts read `TDTH_SELLER_API_TOKEN` when present. If it is absent, they
prompt without echoing the token. The token is held in memory only.

## Run on macOS, Windows, or Linux

Install Python 3.10 or newer. From the standalone repository root:

```bash
cd seller-api-python-examples
```

macOS/Linux:

```bash
export TDTH_SELLER_API_TOKEN='use-the-hidden-prompt-instead-when-possible'
python3 01_check_connection.py
python3 02_list_products.py
python3 03_list_taxonomy.py
```

Windows PowerShell:

```powershell
Remove-Item Env:TDTH_SELLER_API_TOKEN -ErrorAction SilentlyContinue
python .\01_check_connection.py
python .\02_list_products.py
python .\03_list_taxonomy.py
```

When the environment variable is absent, each script uses Python's hidden
password prompt. This avoids putting the PAT in PowerShell history. You may
also supply `TDTH_SELLER_API_TOKEN` through a separately managed secret
environment, but never paste it into a command line.

The examples themselves have no third-party runtime dependencies. To run the
mocked test suite, install the development dependency listed in
`requirements-dev.txt`:

```bash
python3 -m venv .venv
. .venv/bin/activate       # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Read-only examples

These requests do not create, update, publish, delete, upload, or transfer
files:

```bash
python3 01_check_connection.py
python3 02_list_products.py --status published
python3 03_list_taxonomy.py
```

Required permissions:

| Example | Permission |
| --- | --- |
| Connection check and product list | `products:read` |
| Taxonomy list | `taxonomy:read` |
| Create or update draft | `drafts:write` |
| Product image upload | `media:write`, when external uploads are enabled |
| Resource upload/status | `resources:write`, when external uploads and scanning are enabled |

## Buyer filters and related resources

The merchandising examples use the public Seller API directly. Read operations
require `store:read` and/or `products:read`; mutations require `store:write`
and/or `products:write`. Existing PATs are not granted new permissions
automatically: create or reauthorize a token with only the scopes your
integration needs.

```bash
python3 09_buyer_filters.py
python3 10_product_merchandising.py PRODUCT_UUID
```

`09_buyer_filters.py` lists the connected store's filters by default. Its
complete create, rename, reorder, delete, and fresh-read cleanup demonstration
requires `--execute --confirm` and changes only the authenticated seller's
store. The temporary filter is uniquely named and the original order is
verified after deletion. If cleanup cannot be verified, the script exits
nonzero and prints a warning.

`10_product_merchandising.py` reads product buyer-filter assignments and
ordered related resources by default. Assignment writes are explicit and
replace the complete list:

```bash
python3 10_product_merchandising.py PRODUCT_UUID \
  --filter-id FILTER_UUID \
  --related-product-id RELATED_PRODUCT_UUID \
  --execute --confirm

python3 10_product_merchandising.py PRODUCT_UUID \
  --clear-filters --clear-related \
  --execute --confirm
```

Use a current `--expected-revision` only when you intentionally want a
specific optimistic-concurrency check; otherwise the example reads the latest
revision immediately before its writes. A successful buyer-filter update
returns a new revision, which is used for the related-resource update. A `409`
means the product changed elsewhere; retrieve the current state and decide
whether to retry rather than overwriting another edit. These examples never
publish, unpublish, create, or delete products.

The API accepts an explicit empty list to clear assignments. Related resources
must be distinct, cannot include the product itself, must belong to the same
store, and are limited to four. The server rejects a fifth item and other
invalid IDs with `422`. Published products may receive these merchandising
updates without a publication-status change. Product and store ownership is
always derived from the PAT, not from caller-supplied seller IDs.

The direct endpoint contracts are:

| Operation | Method and path | Scope |
| --- | --- | --- |
| List/create buyer filters | `GET/POST /api/v1/seller/store/buyer-filters` | `store:read` / `store:write` |
| Rename/delete buyer filter | `PATCH/DELETE /api/v1/seller/store/buyer-filters/{filter_id}` | `store:write` |
| Replace filter order | `PUT /api/v1/seller/store/buyer-filters/order` | `store:write` |
| Get/set product filters | `GET/PUT /api/v1/seller/products/{product_id}/buyer-filters` | `products:read` / `products:write` |
| Get/set related resources | `GET/PUT /api/v1/seller/products/{product_id}/related-resources` | `products:read` / `products:write` |

The client does not automatically retry non-idempotent requests. `401` and
`403` indicate authentication, ownership, or scope problems; `409` indicates a
revision or state conflict; `422` indicates invalid IDs, duplicates, status,
or the four-resource limit; and `429` indicates rate limiting. Respect the
server's `Retry-After` guidance and never log the PAT.

## Draft examples

Write scripts are dry-run by default:

```bash
python3 04_create_draft.py --title "My example draft"
python3 05_update_draft.py PRODUCT_UUID --expected-revision 1
```

To opt in, use `--execute --confirm`. Draft creation also requires a stable
idempotency key that you can safely reuse if the network result is uncertain:

```bash
python3 04_create_draft.py \
  --execute --confirm \
  --idempotency-key micah-example-draft-001 \
  --title "My example draft"

python3 05_update_draft.py PRODUCT_UUID \
  --expected-revision 1 \
  --execute --confirm
```

These commands affect only the authenticated seller's account and create or
edit unpublished drafts. They never publish or delete products. A stale
`--expected-revision` returns `409`; fetch the product again and review the
new revision before retrying. Do not overwrite a concurrent change.

## Errors and revocation

- `401`: token is missing, invalid, expired, or revoked.
- `403`: the seller or requested scope is not eligible.
- `404`: the feature or seller-owned resource is unavailable.
- `409`: idempotency mismatch, revision conflict, or invalid state.
- `429`: token or seller rate limit; respect `Retry-After` when provided.

The client uses bounded timeouts, does not retry automatically, and reports
sanitized errors without response bodies or authorization headers. Revoke a
PAT from **Seller Dashboard → Settings → API Access**; revocation takes
effect immediately.

## Upload acceptance examples

Upload examples require an explicitly selected unpublished product and the
matching PAT permission. Backend feature availability must also be enabled.
They use small synthetic fixtures and never publish,
delete, or create orders.

| Example | Permission | Behavior |
| --- | --- | --- |
| `06_upload_product_image.py` | `media:write` | Creates a cover upload, transfers a synthetic 480×480 PNG, completes it, and attaches it. |
| `07_upload_resource.py` | `resources:write` | Creates a PDF upload, transfers it, waits for `scan_status=clean`, and attaches it. |
| `08_check_upload_status.py` | `media:write` or `resources:write` | Reads one owned upload session without showing upload credentials. |

All write examples are dry runs unless both `--execute` and `--confirm` are
provided. Upload authorization requires a stable caller-supplied
`Idempotency-Key`; reuse that same key after an uncertain response rather than
creating a new session. The returned GCS resumable URL is used only in memory
and is never printed. Resource attachment fails closed for pending, rejected,
failed, unknown, or timed-out scans.

Preview the operations locally without a token or network request:

```bash
python3 06_upload_product_image.py --product-id PRODUCT_UUID --idempotency-key image-acceptance-001
python3 07_upload_resource.py --product-id PRODUCT_UUID --idempotency-key resource-acceptance-001
```

For a later approved acceptance test, verify the product belongs to the
authenticated seller and remains unpublished, then run the same commands with
`--execute --confirm`. Use a unique stable key for each distinct fixture. Check
status with `08_check_upload_status.py UPLOAD_UUID`; do not paste or log signed
URLs. Cleanup must use TDTH's existing seller-owned upload/session and asset
procedures; these examples do not automatically delete existing assets.

## What is not included

These examples do not call private OAuth delegation routes, publish products,
delete products, access orders or payments, or create test sellers/stores.
External uploads remain feature-controlled, and paid resources remain private
through TDTH's existing entitlement-controlled download path.

More information:

- [TDTH Developer Portal](https://teacherdownthehall.com/developers)
- [Seller API reference](https://teacherdownthehall.com/developers/api)
- [Seller API authentication](https://teacherdownthehall.com/developers/authentication)

## GitHub Actions

The included workflow runs compilation and mocked tests only. It does not
receive PATs, cloud credentials, production database access, or signed
storage URLs.
