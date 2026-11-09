# Texas Bill Atlas

An independent, open-source bill tracker for the Texas Legislature's **90th Regular Session (2027)**. Built for fast exploration by policy, state agency, author prominence and the verifiable legislative path to a hearing. It starts with a **clearly labeled, selective** November 9, 2026 filing snapshot, not a fictional complete feed.

## What it does now

- Search and filter by bill number, author, topic, chamber, affected agency, procedural stage, and hearing status.
- Surface **multiple potentially affected agencies per bill**, distinguishing directly supported mentions from inferred connections. The agency catalog is an extensible starting vocabulary, not a claim of complete statutory review.
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

**Important first-run limitation:** the current TLC 90R FTP XML layout has not been tested in this environment. The GitHub Actions job and parser tests are present, but the first actual remote sync must be observed and any schema differences adapted before claiming live completeness. The UI distinguishes curated, imported and official-FTP snapshots so users see this limitation. GitHub Actions runs every 12 hours once enabled, but should not be represented as successful until it completes.

### Publishing

The `Publish tracker to GitHub Pages` workflow assembles the static files from the repository. Enable GitHub Pages with **Source: GitHub Actions** under the repository's Pages settings if the workflow indicates that Pages isn't configured. The expected project URL after successful deployment is `https://ctharvey.github.io/texas_bill_tracker/` (unverified until GitHub confirms).

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
