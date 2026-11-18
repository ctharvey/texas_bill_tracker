# Texas Bill Atlas

An independent, open-source bill tracker for the Texas Legislature's **90th Regular Session (2027)**, live at
https://billatlas.org. An agent edition (static Markdown and JSON for AI assistants and scripts) is at
https://agent.billatlas.org.

Data comes from the Texas Legislative Council's official bulk FTP service, refreshed hourly. The site shows when its
snapshot was made and warns when it is showing the bundled fallback, a local import, or a snapshot more than eight
hours old.

## What it does

- Search and filter bills by number, author, topic, reader area, chamber, agency, stage, last action and hearing status.
- Each bill has its own page (`/bill/<ID>`) with the official record, bill text with insertions and deletions, the laws
  it changes, population limits, companions, committee witness lists and an "Ask AI" menu.
- **Luna**, an AI review of each bill's full official text, adds a summary, topics, affected agencies, groups and
  places. Only claims whose quotes are found in the bill text are published, and every AI field is labelled as such.
- Shows referral, scheduled hearing and hearing held as separate facts. Nothing is scored without evidence; there is
  no passage probability.
- **Near you**: your House member and Senator, their bills, and bills naming your county or city. Location stays in
  the browser.
- Member pages for every legislator, with tenure, district and bills by role.
- No accounts. Watchlists, followed legislators and saved searches live in the browser, and can move by link, file
  or an optional private sync link. Every bill and legislator has an RSS feed.

## Running locally

The site is static: serve the checkout and open it.

```bash
python3 -m http.server 8787        # then open http://localhost:8787
```

Tests (CI runs the same on every push; browser E2E tests run in CI only):

```bash
python -m pip install pytest -r requirements-extraction.txt
python -m pytest -q tests
node --test tests/*.test.mjs
```

Locally the site uses the bundled `data/bills.json`; on the server it loads the hourly `live/bills.json` first.

## Data sources

- Bill histories, text and documents: the Texas Legislative Council's
  [bulk FTP service](https://capitol.texas.gov/billlookup/filedownloads.aspx), which TLC provides for bulk use in place
  of scraping its web pages. The importer keeps the previous snapshot when a read fails.
- Legislators: Texas Legislature Online and the Legislative Reference Library; members-elect from the Secretary of
  State's unofficial 2026 results (`data/members_elect_2026.json`, until LRL lists the 90th Legislature).
- Districts: TLC plans PLANH2316 and PLANS2168 and Census county lines (`data/geo/`, built by
  `scripts/build_districts.py`).
- Population limits: the 2020 Census P.L. 94-171 file (`data/census/`).

## Documentation

- [docs/data-pipeline.md](docs/data-pipeline.md): the hourly data run and the other server jobs, and what each writes.
- [docs/review-pipeline.md](docs/review-pipeline.md): the Luna review worker, what it publishes, and how its spending
  is guarded.
- [docs/deployment.md](docs/deployment.md): the VPS, the deployer, systemd units, Cloudflare and rollback.
- [docs/data-model.md](docs/data-model.md): `bills.json`, the `live/` files, and what the browser and sync store.
- [deploy/sync/README.md](deploy/sync/README.md): the private sync service.
- [CHANGELOG.md](CHANGELOG.md)

## Editorial principles

1. **Traceability.** Every bill links to its official history; snapshots state their scope and time.
2. **Uncertainty.** A keyword-based agency link is a *possible impact*, not a formal assignment.
3. **No false probabilities.** Hearing facts are reported, not forecast; passage is not scored.
4. **No silent fallback.** A failed import exits nonzero and leaves the last good data in place.

## References

- [Texas Legislature Online](https://capitol.texas.gov/)
- [TLC bulk file downloads and acceptable use](https://capitol.texas.gov/billlookup/filedownloads.aspx)
- [How to Follow a Bill](https://capitol.texas.gov/resources/FollowABill.aspx)
- [Legislative Reference Library prefiling FAQ](https://lrl.texas.gov/whatsNew/client/print.cfm?id=A9F890FC-DFF4-76F1-BF4CFDF37B910F6B)
