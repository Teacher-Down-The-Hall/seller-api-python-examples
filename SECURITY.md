# Security

Please do not report security issues in public GitHub issues. Use the
repository's private vulnerability report form:
<https://github.com/Teacher-Down-The-Hall/seller-api-python-examples/security/advisories/new>.
If that form is unavailable, contact Teacher Down the Hall through the
official support channel at <https://teacherdownthehall.com/contact>. Include
a concise description of the issue and a safe way to reproduce it.

## Protect Seller API tokens

- Generate tokens from **Seller Dashboard → Settings → API Access** using
  **New Token**.
- Store tokens in a secret manager or a protected environment, not in source
  control, URLs, screenshots, browser code, or logs.
- Do not pass tokens as command-line arguments.
- Revoke a token immediately if it may have been exposed.
- Use the smallest set of permissions needed for the task.

The examples intentionally do not persist tokens, print authorization headers,
print signed storage URLs, access databases, or call private OAuth delegation
routes.
