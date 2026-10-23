# Catalog availability check

Checked on October 23, 2026 from one network. The snapshot contains 25,000 profile templates.

23,605 fixed HTTP/HTTPS origins were requested. 71 username-dependent host templates were skipped because they require an account name. Four origins failed validation before a request.

| Result | Origins |
| --- | ---: |
| Responding on the same hostname (including www normalization) | 20,983 |
| Responding after redirecting to another hostname | 326 |
| Access restricted: HTTP 401, 403, 407, 429, 451 or 999 | 729 |
| Other HTTP error | 485 |
| DNS, TLS, connection error or six-second timeout | 924 |
| URL/response rejected, unsupported compression or redirect limit | 158 |

The check used paced GET requests, up to 64 simultaneous connections, a six-second timeout and a 64 KiB response limit. Responses and account records were not stored. The JSONL report contains origins, HTTP status, a category and the final origin where available.

A responding homepage is not proof that profile detection works. Redirects can lead to login pages or parked domains. A failed request from one network does not establish that a site is permanently offline. No catalog entries were automatically removed from this single pass.

The count is not 25,000 verified profile detectors. Many entries are separate servers running the same federated platform.

The [raw report](https://github.com/hexmisery/NIX/releases/latest/download/NIX-catalog-availability.jsonl) and [summary](https://github.com/hexmisery/NIX/releases/latest/download/NIX-catalog-check.json) are included with the release.

Repeat the check from the source directory:

    python tools/check_catalog.py --output catalog-check

Run the same command again to resume an interrupted check. Use a new output directory for a fresh check.
