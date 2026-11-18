"""Purge Cloudflare's copy of the files only the data run writes, so the edge can keep them an hour between runs.

texas-bill-data.service runs this from ExecStopPost, after every run (finished, failed or timed out). A Cloudflare cache
rule keeps PREFIXES at the edge for an hour; this purge is what makes a new hour's data visible right away. If it
fails, the edge serves at most an hour-old copy. luna/, og/ and members.json have other writers and keep the
5-minute rule, so they are not purged here.

The token (Cache Purge on the billatlas.org zone only) comes from the unit's LoadCredential=cf-purge-token.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ZONE_ID = "db785871c15127e883574d0bef17bce4"  # billatlas.org
ENDPOINT = f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/purge_cache"
# Origin paths (after Cloudflare's rewrites of /openapi.json, /auth.md and /.well-known/api-catalog).
PREFIXES = [f"billatlas.org/live/{path}" for path in (
    "bills.json", "feeds/", "share/", "sitemap.xml", "statutes/", "brackets/", "text/", "history/",
    "api-catalog.json", "openapi.json", "auth.md")]
CREDENTIAL = "cf-purge-token"


def read_token(environ=os.environ) -> str | None:
    folder = environ.get("CREDENTIALS_DIRECTORY")
    if not folder:
        return None
    try:
        return (Path(folder) / CREDENTIAL).read_text("utf-8").strip() or None
    except OSError:
        return None


def purge(token: str, opener=None) -> tuple[bool, str]:
    """One prefix purge; returns (ok, status line). Never retries: the purge rate limit is shared by the account."""
    import urllib.error
    import urllib.request
    request = urllib.request.Request(ENDPOINT, data=json.dumps({"prefixes": PREFIXES}).encode("utf-8"), method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                              "User-Agent": "texas-bill-atlas-purge"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=30) as response:
            body = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return False, f"HTTP {error.code}"
    except (urllib.error.URLError, OSError, ValueError) as error:
        return False, f"failed: {type(error).__name__}"
    if not body.get("success"):
        codes = ",".join(str(e.get("code")) for e in body.get("errors") or [] if isinstance(e, dict))
        return False, f"not accepted ({codes or 'no error code'})"
    return True, f"{len(PREFIXES)} prefixes purged"


def main(environ=os.environ, opener=None) -> int:
    token = read_token(environ)
    if not token:
        print("Cache purge skipped: no cf-purge-token credential", flush=True)
        return 0
    ok, status = purge(token, opener)
    print(f"Cache purge: {status}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
