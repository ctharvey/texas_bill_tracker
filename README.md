# Texas Bill Atlas

An independent, open-source bill tracker for the Texas Legislature's **90th Regular Session (2027)**. Built for fast exploration by policy, state agency, author prominence and the verifiable legislative path to a hearing. Its verified November 9, 2026 official FTP snapshot contains 1,059 legislative measures; the interface displays the dataset's source and timestamp.

## What it does now

- Search and filter by bill number, author, topic, chamber, affected agency, procedural stage, and hearing status.
- Surface **multiple potentially affected agencies per bill**, distinguishing directly supported mentions from inferred connections. The agency catalog is an extensible starting vocabulary, not a claim of complete statutory review.
- Include the Texas State Board of Public Accountancy for CPA certification and licensing bills, and a separate **All state agencies (cross-cutting)** scope tag for general agency-wide requirements. Explicit broad language gets a direct tag; broader compliance inferences are marked possible. The cross-cutting scope is not counted as another physical state agency.
- Show author institutional influence **only when a verified role or tenure fact has been entered**. No party-only influence assumptions.
- Show referral, scheduled hearing and hearing held as separate procedural signals. A prefiled bill without committee evidence is *not rated*, never assigned an invented probability.
- Maintain a device-local watchlist, view bill details and source links, export filtered CSV, and import CSV/JSON datasets locally.
- Include a conservative bulk updater for the [Texas Legislative Council's official FTP service](https://capitol.texas.gov/billlookup/filedownloads.aspx) and GitHub Actions workflows for sync and Pages deployment.
- On the hosted app, read the repository's current `data/bills.json` snapshot, falling back to the locally bundled snapshot if GitHub cannot be reached. The UI reports which source was loaded.

## Running locally

Requires only Python 3.10+ and optionally Node 18+ for JS tests.

```bash
python3 -m http.server 8787
# open http://localhost:8787
node --test tests/*.test.mjs
python3 -m unittest discover -s tests -v
```

No package installation, database, cookies, or API credentials are needed for the UI.

## Data pipeline and provenance

The TLC specifically provides bulk documents over anonymous FTP and warns against mining public `capitol.texas.gov` pages. The updater honors that constraint:

```bash
python3 scripts/sync_ftp.py
```

`scripts/sync_ftp.py` enumerates `/bills/90r/billhistory`, parses each XML document, validates the bill number and caption, then atomically replaces `data/bills.json` **only if enough records parse successfully**. The previous file stays unchanged on a connectivity or schema failure. Manually reviewed impact tags survive metadata refreshes. The parser intentionally does not claim unobserved hearings or manufacture agency facts.

The first verified official import read 1,059 bill histories on November 9, 2026. GitHub Actions is scheduled hourly, at minute 17 UTC (GitHub may delay scheduled jobs). Each snapshot records its actual generation time and coverage; it is a dated bulk snapshot rather than a real-time feed.

### Production deployment

Production: https://bills.ctharvey.me on the existing VPS, 147.93.132.141.
Cloudflare DNS has a DNS-only A record `bills` pointing there. Shared Caddy routing
is owned by `ctharvey/cth.hosting`; its site root is
`/srv/static/texas-bill-atlas/current`, through the existing read-only `/var/www/html` mount.
Caddy manages HTTPS and the HTTP redirect. No application server or build is required.

`texas-bill-atlas.timer` checks public GitHub `main` every two minutes, including commits
from the data-refresh workflow. No deployment credential is needed. `scripts/deploy_static.py`
reads all five application files at one commit, requires an official-FTP 90R snapshot
of at least 1,000 unique valid measures, writes an immutable release, and atomically
switches `current`. Fetch or validation failure leaves the previous release online.
The bundled fallback updates with each release. The frontend still prefers live GitHub
JSON and retains all existing source and freshness indicators.

One-time VPS installation as root, from a reviewed Git archive of this repository:

```sh
useradd --system --home-dir /var/lib/texas-bill-atlas --shell /usr/sbin/nologin texas-bill-atlas
install -d -m 755 -o texas-bill-atlas -g texas-bill-atlas /var/www/html/texas-bill-atlas
install -d -m 755 /usr/local/lib/texas-bill-atlas
install -m 644 scripts/deploy_static.py /usr/local/lib/texas-bill-atlas/deploy_static.py
install -m 644 scripts/texas-bill-atlas.service scripts/texas-bill-atlas.timer /etc/systemd/system/
systemctl daemon-reload
systemctl start texas-bill-atlas.service
systemctl enable --now texas-bill-atlas.timer
```

Requires existing Python 3, Git and systemd. The unprivileged service writes only its
state directory and this site's directory. Check `systemctl status texas-bill-atlas.timer`
and `journalctl -u texas-bill-atlas.service`. Deployer or unit changes require reinstalling
the reviewed files; application and data changes deploy automatically. Old releases are retained.

Rollback: stop the timer, make a temporary relative symlink to a retained `releases/<commit>`,
then atomically rename it over `current` using `mv -Tf`. Fix or revert main before restarting
the timer. This affects only the bills site. The legacy Pages workflow below is manual-only.

Deferred improvements: incremental FTP imports; retry/rebase concurrent dataset pushes;
an authoritative agency registry; full-text agency classification; and alerts for importer
failures, stale snapshots and frontend fallback use.

### Optional GitHub Pages publishing

The `Publish tracker to GitHub Pages` workflow assembles the static files from the repository. Enable GitHub Pages with **Source: GitHub Actions** under the repository's Pages settings if the workflow indicates that Pages isn't configured. The expected project URL after successful deployment is `https://ctharvey.github.io/texas_bill_tracker/` (unverified until GitHub confirms).

Member roles from official FTP are stored separately in `authors`, `coauthors`, `sponsors` and
`cosponsors` arrays. Counts are derived from those lists. Bill cards show author/coauthor/cosponsor
counts; details list every member by role. Search and CSV export include these fields.
Empty official lists mean none listed in the snapshot; missing fields in local imports are
shown as not reported. Authors/coauthors belong to the originating chamber and sponsors/
cosponsors to the other chamber. The `author` display string remains for compatibility.

### Input data schema

`data/bills.json` contains:

```json
{
  "session": "90R",
  "generated_at": "2026-11-09T19:35:18Z",
  "data_mode": "curated",
  "coverage_note": "selected filings, not exhaustive",
  "bills": [{
    "id": "HB164", "title": "...", "caption": "...", "author": "...",
    "status": "Filed", "filed_at": "2026-11-09",
    "topics": ["Education"],
    "agencies": [{"id":"comptroller","relationship":"direct","reason":"..."}],
    "impacts": ["Program repeal"], "constituencies": ["Students & families"]
  }]
}
```

CSV import accepts columns such as `id`, `title`, `caption`, `author`, `status`, `filed_at`, `topics` and `agencies` (multi-value columns separated by `|`). Imports are in-memory and don't alter the shared file.

## Analysis dimensions

| Dimension | Current behavior | Next addition |
|---|---|---|
| Policy areas | Multi-tag rules + curated overrides | Review full text with evidence snippets |
| State agencies | All detected links, direct or inferred, with explanation | Complete authoritative agency registry and exhaustive bill-text references |
| Impact mechanism | Funding, mandates, eligibility, regulation, reporting etc. | Section-level statutory diff and implementation burden |
| Geography | Counties/local government in topic tags | Geographic district/MUD/ETJ effects |
| Author prominence | Verified leadership/committee/tenure fields only | 90R roster, historical effectiveness and committee membership |
| Hearing outlook | Referral/scheduled/heard facts only | Calibrated, historical hearing model with confidence intervals |
| Passage outlook | Deliberately unscored | Separate chamber and governor conditional model |
| Companions | Source model can be extended | Cross-chamber companion graph |
| Fiscal impacts | Broad tags | Fiscal note amounts and state/local cost allocation |
| Civil liberties | Rights/privacy tag | Dedicated rights, preemption and enforcement review |

## Editorial principles

1. **Traceability.** Each bill links to its official TLO history; source snapshots state their scope and time.
2. **Uncertainty.** A policy-keyword agency relation is a *possible impact*, not a formal agency assignment.
3. **No false probabilities.** Early prefiling is a poor basis for precise forecast percentages. Keep hearing and passage outcomes separate.
4. **No silent fallback.** A failed FTP sync exits nonzero and leaves the last good dataset in place.
5. **Versioning.** Keep the underlying snapshot in Git history so changes can be audited.

## References

- [Official Texas Legislature Online](https://capitol.texas.gov/)
- [TLC bulk file downloads and acceptable use](https://capitol.texas.gov/billlookup/filedownloads.aspx)
- [Official “How to Follow a Bill” guide](https://capitol.texas.gov/resources/FollowABill.aspx)
- [Legislative Reference Library prefiling FAQ](https://lrl.texas.gov/whatsNew/client/print.cfm?id=A9F890FC-DFF4-76F1-BF4CFDF37B910F6B)
