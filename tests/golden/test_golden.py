"""Pipeline parity: each entry point's output on frozen inputs must stay byte-identical across the refactor.

Inputs are the E2E capture (tests/e2e/fixtures/live) and tests/fixtures. Expected values live in tests/golden/expected/
and change only with TBA_GOLDEN_UPDATE=1; a move commit that regenerates them has changed behavior.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LIVE = REPO / "tests" / "e2e" / "fixtures" / "live"
FIXTURES = REPO / "tests" / "fixtures"
EXPECTED = Path(__file__).resolve().parent / "expected"
sys.path.insert(0, str(REPO / "scripts"))
import classify_bill  # noqa: E402
import extract_bill  # noqa: E402
import search_bills  # noqa: E402
import sync_ftp  # noqa: E402
import sync_service as svc  # noqa: E402

UPDATE = os.environ.get("TBA_GOLDEN_UPDATE") == "1"
NODE = shutil.which("node")


def golden(name: str, value):
    path = EXPECTED / f"{name}.json"
    text = json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if UPDATE:
        EXPECTED.mkdir(exist_ok=True)
        path.write_text(text, "utf-8", newline="\n")
        return
    assert path.is_file(), f"no golden {path.name}; record it with TBA_GOLDEN_UPDATE=1 on the base commit"
    expected = json.loads(path.read_text("utf-8"))
    if isinstance(value, dict) and isinstance(expected, dict):
        changed = sorted(k for k in expected.keys() | value.keys() if expected.get(k) != value.get(k))
        assert not changed, f"{name}: {len(changed)} entries differ, first: {changed[:10]}"
    assert value == expected


def manifest(root: Path) -> dict:
    # Python text-mode writes CRLF on Windows; production (Linux) writes LF, so hash the LF form.
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def fixture(name: str) -> str:
    """A tests/fixtures file as committed (LF), whatever line endings this checkout gave it."""
    return (FIXTURES / name).read_bytes().replace(b"\r\n", b"\n").decode("latin-1")


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """A private copy of the capture laid out like the server's live/ folder."""
    root = tmp_path_factory.mktemp("live")
    for name in ("bills.json", "members.json", "luna", "text"):
        source = LIVE / name
        (shutil.copytree if source.is_dir() else shutil.copyfile)(source, root / name)
    return root


def run(*cmd):
    done = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_build_feeds_outputs(live, tmp_path):
    out = run(sys.executable, "scripts/build_feeds.py", "--snapshot", str(live / "bills.json"), "--out",
              str(tmp_path / "feeds"), "--statutes", str(tmp_path / "statutes"), "--brackets", str(tmp_path / "brackets"),
              "--census", str(REPO / "data" / "census" / "tx_population_2020.json"))
    golden("build_feeds", {"stdout": out.splitlines(), "feeds": manifest(tmp_path / "feeds"),
                           "statutes": manifest(tmp_path / "statutes"), "brackets": manifest(tmp_path / "brackets")})


@pytest.fixture(scope="module")
def agent_out(live, tmp_path_factory):
    if not NODE:
        pytest.skip("node is not installed")
    out = tmp_path_factory.mktemp("agent")
    stdout = run(NODE, "scripts/build_agent.mjs", "--snapshot", str(live / "bills.json"), "--tags",
                 str(live / "luna" / "tags.json"), "--members", str(live / "members.json"), "--status",
                 str(live / "luna" / "status.json"), "--districts", str(REPO / "data" / "geo" / "districts.json"),
                 "--out", str(out))
    return out, stdout


def test_build_agent_pages(agent_out):
    out, stdout = agent_out
    golden("build_agent", {"stdout": stdout.splitlines(), "pages": manifest(out)})


QUERIES = ["q=water", "q=property+tax&format=json", "q=HB110", "topic=Education", "q=school&chamber=House",
           "q=%22county+with+a+population%22", "q=water+-flood", "q=", "q=zzzznotaword"]


def test_search_results(agent_out):
    out, _ = agent_out
    index = search_bills.Index(out / "data" / "bills.json").get()
    assert index.docs, "agent search data did not load"
    results = {}
    for query in QUERIES:
        try:
            params = search_bills.parse_params(query)
        except search_bills.BadQuery as error:
            results[query] = {"error": str(error)}
            continue
        found = search_bills.search(index, params)
        results[query] = {"json": search_bills.as_json(found, params),
                          "markdown": search_bills.as_markdown(found, params, search_bills.DISCLAIMER)}
    golden("search", results)


def test_model_requests_are_byte_identical():
    """The paid response cache is keyed on request content: moving prompts or schemas must not change these."""
    registry = extract_bill.load_registry()
    requests = {}
    for bill in ("HB110", "HB717", "HB1001"):
        markdown = (LIVE / "text" / bill / "I.md").read_text("utf-8")
        document = extract_bill.document_from_markdown(bill, "90R", "I", markdown)
        for name, request in (("extract", extract_bill.build_request(document, registry)),
                              ("classify", classify_bill.build_request(document, registry))):
            blob = json.dumps(request, sort_keys=True, ensure_ascii=False).encode("utf-8")
            requests[f"{bill}/{name}"] = hashlib.sha256(blob).hexdigest()
    requests["policy_tags"] = classify_bill.load_policy_tags()
    requests["registry"] = hashlib.sha256(json.dumps(registry, sort_keys=True).encode()).hexdigest()
    golden("model_requests", requests)


def test_sync_ftp_parsers():
    xml = (FIXTURES / "89R-HB2.xml").read_bytes()
    record = sync_ftp.parse_bill_xml(xml, "bills/89R/billhistory/house_bills/HB00001_HB00099/HB 2.xml")
    text = sync_ftp.bill_text_markdown(fixture("HB01001I.HTM"), "HB 1001", "Introduced")
    docs = {kind: sync_ftp.document_markdown(fixture(f"89R-HB2-{part}-H.htm"), kind, "HB 2", "House")
            for kind, part in (("analysis", "analysis"), ("fiscal_note", "fiscal"))}
    witnesses = sync_ftp.parse_witness_list(fixture("89R-HB2-witnesses-H.htm"))
    golden("sync_ftp", {"record": record, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "text_head": text[:2000], "docs_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in docs.items()},
                        "witnesses": witnesses})


class Keys:
    def __init__(self):
        self.n = 0

    def __call__(self, nbytes):
        self.n += 1
        return f"{self.n:022d}"[-22:]


def test_sync_service_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(svc.secrets, "token_urlsafe", Keys())
    app = svc.App(svc.Store(tmp_path / "sync.sqlite3"), svc.Snapshot(LIVE / "bills.json"), clock=lambda: 1_800_000_000.0)
    origin = {"Origin": "https://bills.ctharvey.me", "Content-Type": "application/json"}
    transcript, keys = [], {}

    def call(label, method, path, headers=None, body=None):
        raw = json.dumps(body).encode() if body is not None else None
        try:
            status, _, payload = app.handle(method, path, {**origin, **(headers or {})}, raw, "203.0.113.9")
            text = payload.decode("utf-8")
            data = json.loads(text) if text.startswith("{") else text
        except svc.Rejected as error:
            status, data = error.status, {"error": str(error), **getattr(error, "extra", {})}
        transcript.append([label, status, data])
        return data

    save = {"watch": ["HB110", "HB717"], "follows": ["A1234"], "searches": [
        {"id": "abcd1234", "name": "Water", "filters": {"query": "water"}, "seen": "2026-11-12"}]}
    made = call("create", "POST", "/api/sync", body={"data": save})
    keys["edit"], keys["view"] = made["edit_key"], made["view_key"]
    call("read edit", "GET", "/api/sync", {"X-Sync-Key": keys["edit"]})
    call("read view", "GET", "/api/sync", {"X-Sync-Key": keys["view"]})
    call("update", "PUT", "/api/sync", {"X-Sync-Key": keys["edit"]}, {"version": 1, "data": {"watch": ["HB110"]}})
    call("stale update", "PUT", "/api/sync", {"X-Sync-Key": keys["edit"]}, {"version": 1, "data": {"watch": []}})
    call("view cannot write", "PUT", "/api/sync", {"X-Sync-Key": keys["view"]}, {"version": 2, "data": {"watch": []}})
    call("feed", "GET", f"/api/sync/feed/{keys['view']}.xml")
    call("edit key is not a feed", "GET", f"/api/sync/feed/{keys['edit']}.xml")
    call("bad origin", "POST", "/api/sync", {"Origin": "https://evil.example"}, {"data": save})
    call("health", "GET", "/api/sync/health")
    call("delete", "DELETE", "/api/sync", {"X-Sync-Key": keys["edit"]})
    call("gone", "GET", "/api/sync", {"X-Sync-Key": keys["edit"]})
    golden("sync_service", transcript)


def test_review_pipeline_dry_run(tmp_path):
    """Dry run (no --execute, no API key) on a private copy: pins the paid-cache keys the real pipeline path computes."""
    live = tmp_path / "live"
    shutil.copytree(LIVE, live)
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    done = subprocess.run([sys.executable, "scripts/review_pipeline.py", "--cache-dir", str(tmp_path / "cache"),
                           "--snapshot", str(live / "bills.json"), "--input", "markdown", "--text-dir", str(live / "text"),
                           "--publish-tags", str(live / "luna" / "tags.json"), "--bill-id", "HB110", "--bill-id", "HB717"],
                          capture_output=True, text=True, cwd=REPO, encoding="utf-8", env=env)
    assert done.returncode == 0, done.stderr
    assert "$0.000000" in done.stdout
    tags = json.loads((live / "luna" / "tags.json").read_text("utf-8"))
    tags.pop("generated_at", None)
    golden("review_pipeline", {"stdout": done.stdout.splitlines(), "cache_keys": sorted(
        p.name for p in (tmp_path / "cache" / "requests").iterdir()), "tags": tags})
