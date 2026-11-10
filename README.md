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

### Focused full-text classification (pending evaluation)

`scripts/classify_bill.py` reads the complete official bill using **Luna Flex/high** and returns a concise
summary, canonical policy tags, direct/inferred state-agency impacts, separate all-agencies scope,
substantive locations, affected groups, major effects and short supporting excerpts. It does not enumerate
every obligation, deadline or exception. Author/party/member counts and legislative events remain official
metadata. The policy and agency vocabularies come from `src/taxonomy.js`; the agency list is still incomplete.

Reviewed statutory definitions live in `scripts/statutory_definitions.json`, initially Water Code
16.001(1)-(2): Board/TWDB and Commission/TCEQ. An explicit matching chapter or section amendment selects
the chapter context; a topical mention or another code does not. In-bill definitions take precedence.
Each entry retains its official source URL, section, chapter scope and verification date. This is a small
reviewed registry, not an automatic or exhaustive statute lookup; unsupported amendment forms and missing
chapters provide no external definitions. Expand it with verified sources before broader deployment.

Definitions follow the full bill in the variable request suffix, preserving the shared prompt cache.
Their text/scope/provenance affect response-cache identity; verification-date-only changes do not. A `D_`
evidence ID cites a statutory definition and is validated separately from bill-page evidence. Agency impact
still requires a bill citation, and identity derived from a supplied definition requires that citation too.
External identity context does not itself establish substantive impact. Definition quotes cannot match an
unrelated chapter or silently fall back to bill text.

```sh
python scripts/classify_bill.py --pdf /path/to/HB00529I.pdf --bill-id HB529 --session 90R --version introduced --source-url ftp://ftp.legis.state.tx.us/bills/90R/billtext/PDF/house_bills/HB00500_HB00599/HB00529I.pdf
```

Install `requirements-extraction.txt` first. Preparation is free; `--execute` authorizes a cache-miss call
using `OPENAI_API_KEY`. This path reuses the detailed extractor's complete-text reader, private persistent
response cache, prompt-cache breakpoints, bounded capacity backoff and uncertain-call protection. Its model,
schema and prompt produce a distinct cache key. A response hit makes no provider call. Shared instructions
and vocabulary target a 12-hour prompt cache; the complete changing bill remains the variable suffix.

The tool verifies canonical IDs/tags and finds literal supporting excerpts in the complete source text.
It derives page offsets and all overlapping span IDs, including excerpts crossing span or page boundaries.
A model-provided span is only a hint: repeated quotes require one uniquely matching source context or stay
flagged as ambiguous. Missing or fuzzy quotes are rejected. `verified_citations` stores source-derived text
and zero-based, end-exclusive offsets into normalized page text, separately from the unchanged model output.
The tool flags unresolved/inferred agency impacts and keeps every output private and pending review.
It does not require every operative span to be
cited. Valid excerpts do not prove semantic accuracy. Nothing is written to `data/bills.json` or published;
classification is not part of the hourly metadata job. Luna Flex short-context cost estimates use the
[official pricing](https://developers.openai.com/api/docs/pricing) verified November 9, 2026, including
cache writes. Review pricing before rollout or use with long-context requests.

The first focused HB529 pilot used all 21 pages and returned 5 policy tags, 2 agency entries, 3 location
scopes, 3 affected groups and 7 major effects. It cost an estimated $0.002208825 in 95 seconds. Six excerpt
locations initially failed validation (four neighboring-span references and two excerpts crossing span
boundaries). Deterministic source matching resolved all six offline: all 43 citations now have verified
locations, with no missing or ambiguous matches. Subsequent statutory review identified the unnamed board
as TWDB under Water Code 16.001(1). The revised HB529 request includes those definitions; it was prepared
offline without another paid pass. The original response remains unchanged and unapproved. This is one pilot, not a claim
of corpus-wide accuracy or demonstrated provider prompt-cache hits across bills.

The detailed version is preserved at
[`archive/detailed-extraction-v1`](https://github.com/ctharvey/texas_bill_tracker/tree/archive/detailed-extraction-v1)
(commit `a78c67d`) and the local tag `detailed-extraction-v1`. Its script and contract remain available below.

### Detailed full-text extraction (preserved, pending evaluation)

`scripts/extract_bill.py` prepares a single Terra Flex/high request from a local official TLC full-bill PDF.
It extracts entities, authority changes, obligations and timing into a **private review cache**. It does not
write `data/bills.json`, run on the hourly history job, or publish classifications. The current tool does not
implement the planned complete policy/geography taxonomy. The existing UI and metadata importer keep working
without these optional dependencies:

```sh
python -m pip install -r requirements-extraction.txt
python scripts/extract_bill.py --pdf /path/to/official-bill.pdf --bill-id HJR31 --session 90R --version introduced --source-url ftp://ftp.legis.state.tx.us/bills/90R/billtext/PDF/house_joint_resolutions/HJ00001_HJ00099/HJ00031I.pdf
```

By default this only prepares the request, or replays and revalidates an existing response. A **new paid call**
requires `--execute` and `OPENAI_API_KEY` in the process environment. The tool does not load repository `.env`
files or credentials from another project. It uses `gpt-6.1-terra`, Flex, high reasoning and a 48,000-token
output allowance with SDK retries disabled. Only explicit capacity/rate rejections get bounded retries;
quota/auth errors and unknown timeouts stop. No automatic model/tier fallback or repair/audit call is made.

The cache persists across invocations at `%LOCALAPPDATA%/texas-bill-atlas/extraction` on Windows or
`$XDG_CACHE_HOME/texas-bill-atlas/extraction` (default `~/.cache/...`) elsewhere. `--cache-dir` selects another
private persistent location **outside the checkout/web root**, including the primary checkout when using a
Git worktree. Ephemeral CI storage would need a persistent cache restored across jobs; no such job is enabled.

Call reduction and cache rules:

- Hash complete whitespace-normalized pages, text version and semantic request configuration. Preserve all
  non-whitespace characters and page boundaries. A blank/image-only page stops extraction rather than silently
  dropping it. PDF bytes and official source URL are retained as provenance.
- Authors, status/actions, refresh timestamps and PDF metadata are excluded from model input and cache identity.
  Repeating an hourly history update cannot invalidate an otherwise identical full-text request.
- Model/settings, prompt, schema, canonical vocabulary, source text or text-version changes invalidate reuse.
  The agency vocabulary is read from the app's `src/taxonomy.js`; the all-agencies marker stays separate.
  If that declaration changes syntax, the reader fails rather than using a stale vocabulary.
- A response hit avoids client construction, credentials and provider calls. Historical token usage/cost is
  labelled separately; new estimated spending is zero. Returned invalid/incomplete output is retained and
  revalidated, not silently paid for again. Validator improvements can recheck saved output without generation.
- OS locks prevent identical concurrent submissions; writes are atomic. A pending crash, timeout or corrupt
  entry blocks resubmission until its outcome is reconciled. Do not delete uncertain entries merely to retry:
  inspect the private request/time and provider logs first. Known capacity rejections have a cooldown.

Shared instructions/schema and vocabulary precede bill-specific content. An explicit 12-hour breakpoint targets
prompt reuse across bills/hourly runs; the changing full bill has no write breakpoint in this single-call path.
Provider prompt caching reduces input cost, while the application response cache skips a request entirely.
Write lifetime details and reasoning-inclusive output usage are used for estimates at the documented Terra Flex
rates; missing lifetime details produce a range. Provider prices and model aliases can change: review rates
before rollout and change the prompt/schema revision or model identity deliberately when regeneration is intended.
See [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) and
[Terra model pricing](https://developers.openai.com/api/docs/models/gpt-6.1-terra) for provider behavior and rates.

Schema/validation fixes include actor certainty (`explicit`, `inferred`, or null/`unspecified`), one actor/action/
modality per obligation, coupled deadline/duration shapes, ordinal-weekday/event-relative calendar relationships,
qualifying-year selection and nullable interval inclusivity. For example, first Monday in June three years after
the census remains an event-relative rule. `resolve_calendar` resolves supported calendar types only after a
verified anchor date is supplied. It rejects nonexistent dates instead of rolling them to another month.
Unmatched/grouped/proposed entities use a null registry ID; only canonical matches use a nonempty ID.
Business-day counts have an explicit `business_days` unit. They are not converted to calendar days or resolved
against a guessed holiday calendar.

Code derives counts and evidence reverse links; the model does not repeat a second bookkeeping table. Unknown
evidence, bad references/dates, unresolved/inferred actors, embedded modal verbs, uncited potentially operative
spans and a stable 5% quality sample generate review signals. These are conservative checks, not a proof of
semantic accuracy or exhaustive coverage. Every result remains `pending_review` or `needs_review`, with
`publishable: false`. No reviewer pass is automatically billed. The private `results/<request-key>.json` contains
the extraction and validation; `responses/` retains the raw response and call state, and `requests/` the exact input.

Before enabling classification, validate the revised contract on varied unseen bills and establish an explicit
approval/publication path. Pilot results showed why valid JSON and resolvable citations alone are insufficient.
No live call or unseen-bill evaluation was performed as part of implementing these fixes.

Run all offline checks with optional dependencies installed:

```sh
python -m unittest discover -s tests -v
node --test tests/*.test.mjs
```

The SDK test uses a mocked HTTP transport and no real credential. Optional schema/SDK tests skip when those
dependencies are absent so the standard-library-only FTP workflow remains usable.

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
