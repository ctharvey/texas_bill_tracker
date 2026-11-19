"""Computed-style snapshot of the whole site, for CSS moves that must not change how anything looks (plan phase 4.4).

Not a pytest module: a CSS move is proven by comparing two commits, so run_style_parity.py runs this script in both
commits' trees on ubuntu-server and compares the results. It snapshots the tree it sits in.

  python tests/e2e/style_snapshot.py snap OUT.json.gz [--mode bundle|src] [--workers N] [--only ID,ID]
  python tests/e2e/style_snapshot.py compare A.json.gz B.json.gz [--trees DIR_A DIR_B] [--mode ...]

A snapshot holds, for every page state below at both viewports, each element's (and its drawn ::before, ::after,
::marker and ::placeholder) full computed style as a hash, under light and dark mode and every colour theme. States
open with the stored fixture data (watchlist, follows, saved searches, near-you location, sync link), so the lists
are drawn. compare names the states and elements that differ; with --trees it re-runs the first few differing states
in both trees and prints the differing properties.
"""

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STORED = Path(__file__).resolve().parent / "fixtures" / "stored"
VIEWPORTS = {"desktop": {"width": 1366, "height": 900}, "phone": {"width": 390, "height": 844}}
MODES_SHOWN = ("light", "dark")
PALETTES = ("atlas", "granite", "lone-star", "bluebonnet", "ranch", "warbler")  # atlas = no data-palette
IGNORED_CONSOLE = ("Failed to load resource",)
DETAIL_STATES = 5


def _click(selector):
    def run(page):
        import harness
        harness.click(page, selector)
    return run


def _open_details(*selectors):
    def run(page):
        for s in selectors:
            page.locator(f"{s} > summary").click()
    return run


def _preview(page):
    page.locator("#dynamic-content .bill-card").first.locator(".bill-filed").click()
    page.locator("#bill-preview").wait_for(state="visible")


def _bill_sections(page):
    page.locator("#drawer-statutes").wait_for(state="visible")


def _privacy(page):
    page.locator("#privacy-open").click()
    page.locator("#privacy").wait_for(state="visible")


# id: (address, setup or None, viewports, stored data loaded)
STATES = {
    "home": ("#home", None, VIEWPORTS, True),
    "explorer": ("#all", None, VIEWPORTS, True),
    "explorer-menus": ("#all", _open_details("#more-filters", "#share-menu"), VIEWPORTS, True),
    "explorer-agency-picker": ("#all", _click("#filter-agency"), VIEWPORTS, True),
    "explorer-search": ("#all?query=HB110", None, VIEWPORTS, True),
    "explorer-agency": ("#all?agency=ers", None, VIEWPORTS, True),
    "explorer-list": ("#all?list=HB110,HB1001", None, VIEWPORTS, True),
    "preview": ("#all", _preview, ("desktop",), True),
    "watchlist": ("#watchlist", None, VIEWPORTS, True),
    "following": ("#following", None, VIEWPORTS, True),
    "today": ("#today", None, VIEWPORTS, True),
    "near": ("#local", None, VIEWPORTS, True),
    "member": ("#member?code=A2150", None, VIEWPORTS, True),
    "statute": ("#statute?law=LA&sec=62.051", None, VIEWPORTS, True),
    "bill-HB110": ("#bill?id=HB110", None, VIEWPORTS, True),
    "bill-HB717": ("#bill?id=HB717", _bill_sections, VIEWPORTS, True),
    "bill-HB147": ("#bill?id=HB147", None, VIEWPORTS, True),
    "agencies": ("#agencies", None, VIEWPORTS, True),
    "review": ("#review", None, VIEWPORTS, True),
    "method": ("#method", None, VIEWPORTS, True),
    "saving": ("#saving", None, VIEWPORTS, True),
    "export": ("#export", None, VIEWPORTS, True),
    "data": ("#data", None, VIEWPORTS, True),
    "nav-more": ("#all", _click("#nav-more"), ("phone",), True),
    "privacy": ("#home", _privacy, VIEWPORTS, True),
    "disclaimer": ("#home", None, VIEWPORTS, False),
}

# In the page: finish running transitions and animations, then each element's computed style under one theme.
# Paths are tag and child index from <html>, so both commits' (identical) DOMs line up element by element.
SNAPSHOT_JS = r"""
({detail}) => {
  for (const a of document.getAnimations()) { try { a.finish(); } catch { a.cancel(); } }
  const props = Array.from(getComputedStyle(document.documentElement));
  const h = s => { let a = 0xdeadbeef, b = 0x41c6ce57;
    for (let i = 0; i < s.length; i++) { const c = s.charCodeAt(i); a = Math.imul(a ^ c, 2654435761); b = Math.imul(b ^ c, 1597334677); }
    a = Math.imul(a ^ (a >>> 16), 2246822507) ^ Math.imul(b ^ (b >>> 13), 3266489909);
    b = Math.imul(b ^ (b >>> 16), 2246822507) ^ Math.imul(a ^ (a >>> 13), 3266489909);
    return (b >>> 0).toString(16).padStart(8, '0') + (a >>> 0).toString(16).padStart(8, '0'); };
  const paths = new Map([[document.documentElement, 'html']]);
  const pathOf = el => { let p = paths.get(el); if (p) return p;
    p = pathOf(el.parentElement) + '>' + el.tagName.toLowerCase() + ':' + Array.prototype.indexOf.call(el.parentElement.children, el);
    paths.set(el, p); return p; };
  const keys = [], values = [];
  const add = (key, style) => { const v = props.map(n => style.getPropertyValue(n)); keys.push(key); values.push(detail ? v : h(v.join('\u0001'))); };
  for (const el of document.querySelectorAll('html, body, body *')) {
    const p = pathOf(el);
    add(p, getComputedStyle(el));
    for (const pseudo of ['::before', '::after']) {
      const s = getComputedStyle(el, pseudo);
      if (s.content !== 'none' && s.content !== 'normal') add(p + pseudo, s);
    }
    if (el.tagName === 'LI' || el.tagName === 'SUMMARY') add(p + '::marker', getComputedStyle(el, '::marker'));
    if (el.hasAttribute('placeholder')) add(p + '::placeholder', getComputedStyle(el, '::placeholder'));
  }
  return {props: h(props.join(',')), propNames: detail ? props : null, keys, values};
}
"""

SET_THEME_JS = """([mode, palette]) => { const d = document.documentElement; d.dataset.mode = mode;
  if (palette === 'atlas') delete d.dataset.palette; else d.dataset.palette = palette; }"""


class _Worker:
    """One browser and one site per process."""

    def __init__(self, mode):
        from playwright.sync_api import sync_playwright
        import harness
        self.harness = harness
        self.pw = sync_playwright().start()
        self.browser = harness.launch(self.pw)
        self.site = harness.Site(mode)
        self.local = json.loads((STORED / "local_storage.json").read_text("utf-8"))
        self.captured_at = harness.capture_info()["captured_at"]

    def run(self, state, viewport, detail):
        address, setup, _, stored = STATES[state]
        # A fresh copy of the stored sync database per state: the stored link syncs against it.
        db = Path(tempfile.mkdtemp(dir=self.site.tmp)) / "sync.sqlite3"
        shutil.copy(STORED / "sync.sqlite3", db)
        self.site.new_sync_store(db)
        from datetime import datetime
        context = self.browser.new_context(viewport=VIEWPORTS[viewport], locale="en-US", timezone_id="America/Chicago",
                                           bypass_csp=True)
        errors = []
        try:
            context.clock.set_fixed_time(datetime.fromisoformat(self.captured_at.replace("Z", "+00:00")))
            context.route("https://fonts.googleapis.com/**", lambda r: r.fulfill(status=200, body="", content_type="text/css"))
            context.route("https://fonts.gstatic.com/**", lambda r: r.fulfill(status=404, body=""))
            context.route("https://geocoding.geo.census.gov/**", lambda r: r.abort())
            if stored:
                context.add_init_script("for (const [k, v] of Object.entries(%s)) localStorage.setItem(k, v);"
                                        % json.dumps(self.local))
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: m.type == "error" and not m.text.startswith(IGNORED_CONSOLE)
                    and errors.append(f"console.error: {m.text}"))
            page.goto(self.site.base + address, wait_until="networkidle")
            page.wait_for_selector("#dynamic-content *", state="attached", timeout=20000)
            if setup:
                setup(page)
            page.wait_for_load_state("networkidle")
            themes = {}
            keys = props = prop_names = None
            for mode in MODES_SHOWN:
                for palette in PALETTES:
                    page.evaluate(SET_THEME_JS, [mode, palette])
                    snap = page.evaluate(SNAPSHOT_JS, {"detail": detail})
                    if keys is None:
                        keys, props, prop_names = snap["keys"], snap["props"], snap["propNames"]
                    elif snap["keys"] != keys:
                        errors.append(f"the DOM changed between themes ({mode}/{palette})")
                    themes[f"{mode}/{palette}"] = snap["values"]
            return {"keys": keys, "props": props, "propNames": prop_names, "themes": themes, "errors": errors}
        except Exception as error:  # Report it with the state; one broken state must not hide the others.
            return {"keys": [], "props": None, "propNames": None, "themes": {}, "errors": errors + [f"{type(error).__name__}: {error}"]}
        finally:
            context.close()


_worker = None


def _init(mode):
    global _worker
    _worker = _Worker(mode)


def _job(args):
    state, viewport, detail = args
    return f"{state}|{viewport}", _worker.run(state, viewport, detail)


def snapshot(mode, workers, only=None, detail=False):
    jobs = [(s, v, detail) for s, (_, _, viewports, _) in STATES.items() if not only or s in only for v in viewports]
    with ProcessPoolExecutor(max_workers=max(1, min(workers, len(jobs))), initializer=_init, initargs=(mode,)) as pool:
        results = dict(pool.map(_job, jobs))
    return {"mode": mode, "states": results}


def digest(snap):
    body = json.dumps({k: [v["keys"], v["themes"]] for k, v in sorted(snap["states"].items())}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def summary(snap):
    states = snap["states"]
    styles = sum(len(v["keys"]) * len(v["themes"]) for v in states.values())
    errors = [f"{k}: {e}" for k, v in sorted(states.items()) for e in v["errors"]]
    return f"{len(states)} page states, {styles} element styles, digest {digest(snap)}", errors


def save(path, snap):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(snap, f)


def load(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def differences(a, b):
    """{state: [(theme or '*', key, why)]} for every state whose styles differ."""
    out = {}
    for state in sorted(set(a["states"]) | set(b["states"])):
        x, y = a["states"].get(state), b["states"].get(state)
        if x is None or y is None:
            out[state] = [("*", "*", "state missing in " + ("A" if x is None else "B"))]
            continue
        diffs = []
        if x["props"] != y["props"]:
            diffs.append(("*", "*", "different property list (another browser build?)"))
        if x["keys"] != y["keys"]:
            only_a, only_b = set(x["keys"]) - set(y["keys"]), set(y["keys"]) - set(x["keys"])
            diffs += [("*", k, "only in A") for k in sorted(only_a)[:20]] + [("*", k, "only in B") for k in sorted(only_b)[:20]]
            if not (only_a or only_b):
                diffs.append(("*", "*", "same elements in a different order"))
        else:
            for theme in sorted(set(x["themes"]) | set(y["themes"])):
                xs, ys = x["themes"].get(theme), y["themes"].get(theme)
                if xs is None or ys is None:
                    diffs.append((theme, "*", "theme missing"))
                    continue
                diffs += [(theme, k, "style differs") for k, p, q in zip(x["keys"], xs, ys) if p != q]
        if diffs:
            out[state] = diffs
    return out


def _detail(tree, mode, state):
    """Full property values for one state, snapshotted by the script in `tree`."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "detail.json.gz"
        subprocess.run([sys.executable, str(Path(tree) / "tests/e2e/style_snapshot.py"), "snap", str(out), "--mode", mode,
                        "--workers", "1", "--only", state.split("|")[0], "--detail"], check=True)
        return load(out)["states"][state]


def explain(trees, mode, state, diffs):
    a, b = (_detail(t, mode, state) for t in trees)
    names = a["propNames"]
    index_a, index_b = {k: i for i, k in enumerate(a["keys"])}, {k: i for i, k in enumerate(b["keys"])}
    shown = 0
    for theme, key, why in diffs:
        if why != "style differs":
            continue
        va, vb = a["themes"][theme][index_a[key]], b["themes"][theme][index_b[key]]
        changed = [f"{n}: {p!r} -> {q!r}" for n, p, q in zip(names, va, vb) if p != q]
        print(f"    {theme} {key}\n      " + "\n      ".join(changed[:12]))
        shown += 1
        if shown == 8:
            break


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    snap = sub.add_parser("snap")
    snap.add_argument("out")
    snap.add_argument("--mode", default="bundle", choices=["bundle", "src"])
    snap.add_argument("--workers", type=int, default=3)
    snap.add_argument("--only", default="")
    snap.add_argument("--detail", action="store_true", help=argparse.SUPPRESS)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("a")
    cmp_.add_argument("b")
    cmp_.add_argument("--trees", nargs=2)
    cmp_.add_argument("--mode", default="bundle", choices=["bundle", "src"])
    opts = parser.parse_args()

    if opts.cmd == "snap":
        unknown = [s for s in filter(None, opts.only.split(",")) if s not in STATES]
        if unknown:
            parser.error("unknown state: " + ", ".join(unknown))
        result = snapshot(opts.mode, opts.workers, set(filter(None, opts.only.split(","))), opts.detail)
        save(opts.out, result)
        line, errors = summary(result)
        print(f"{opts.mode}: {line}", flush=True)
        for e in errors:
            print("  ERROR " + e)
        return 1 if errors else 0

    a, b = load(opts.a), load(opts.b)
    for name, s in (("A", a), ("B", b)):
        line, errors = summary(s)
        print(f"{name}: {line}" + (f", {len(errors)} errors" if errors else ""))
    diffs = differences(a, b)
    if not diffs:
        print("IDENTICAL: every computed style matches.")
        return 0
    total = sum(len(d) for d in diffs.values())
    print(f"DIFFERENT: {total} differences in {len(diffs)} page states")
    for state, d in diffs.items():
        print(f"  {state}: {len(d)}")
        for theme, key, why in d[:5]:
            print(f"    {theme} {key}: {why}")
    if opts.trees:
        for state in list(diffs)[:DETAIL_STATES]:
            print(f"  detail {state}:")
            explain(opts.trees, opts.mode, state, diffs[state])
    return 1


if __name__ == "__main__":
    sys.exit(main())
