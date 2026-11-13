"""Private sync links for Texas Bill Atlas: carry a watchlist and filters across devices with no accounts.

Creating a list returns an edit key and a view key (random, 128 bits). Only SHA-256 hashes of keys are stored,
so the database alone cannot be used to open or change a list. The edit key travels in the X-Sync-Key header,
never in a URL path, so it does not reach access logs; the view key may appear in a watchlist feed URL.
Nothing that identifies a person (email, name, IP address) is stored. Standard library only.
"""
from __future__ import annotations

import argparse
import base64
from collections import deque
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import threading
import time

import build_feeds
import search_bills

SEARCH_PATHS = {"/search", "/search.md", "/search.json", "/api/search"}
KEY_RE = re.compile(r"[A-Za-z0-9_-]{22}")
FEED_RE = re.compile(r"/api/sync/feed/([A-Za-z0-9_-]{22})\.xml")
# Matches the gateway's request_body limit (cth.hosting 07-bills.ctharvey.me.caddy). 500 bills, 200 follows and 20
# searches with SEARCH_FILTER_BYTES each come to about 21 KB.
MAX_BODY = 32 * 1024
SEARCH_FILTER_BYTES = 600
DISCARD_LIMIT, DISCARD_SECONDS = 1024 * 1024, 2  # Bounds on draining a refused body (make_handler).
MAX_BILLS = 500
MAX_FOLLOWS = 200
MEMBER_CODE = re.compile(r"A\d{3,5}")
MAX_SEARCHES = 20
SEARCH_ID = re.compile(r"[a-z0-9]{8,16}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
OPTIONAL_SECTIONS = ("follows", "searches", "theme")
THEME_ID = re.compile(r"[a-z][a-z-]{0,23}")
MAX_LISTS = 100_000
RETENTION_SECONDS = 365 * 86400
FEED_ITEMS = 300
TEXT_FILTERS = {"view", "query", "topic", "agency", "chamber", "stage", "action", "outlook", "sort"}
BOOL_FILTERS = {"onlyWatch"}
LIMITS = {"create": (10, 3600), "write": (300, 3600), "read": (1200, 3600), "search": (1200, 3600)}


class Rejected(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("ascii")).hexdigest()


def view_key_for(edit_key: str) -> str:
    # One-way: the edit key yields the view key, never the reverse.
    digest = hashlib.sha256(b"texas-bill-atlas-view:" + edit_key.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")[:22]


def clean_data(data) -> dict:
    if not isinstance(data, dict):
        raise Rejected(400, "data must be an object")
    watch = data.get("watch", [])
    if not isinstance(watch, list) or len(watch) > MAX_BILLS:
        raise Rejected(400, f"watch must be a list of at most {MAX_BILLS} bills")
    bills = []
    for bill_id in watch:
        if not isinstance(bill_id, str) or not build_feeds.BILL_ID.fullmatch(bill_id):
            raise Rejected(400, "invalid bill id")
        if bill_id not in bills:
            bills.append(bill_id)
    cleaned = {"watch": bills, "filters": clean_filters(data.get("filters") or {})}
    if "follows" in data:  # Absent means "not sent" (an older client), never "none": see merge_data.
        follows = data["follows"]
        if not isinstance(follows, list) or len(follows) > MAX_FOLLOWS:
            raise Rejected(400, f"follows must be a list of at most {MAX_FOLLOWS} member codes")
        codes = []
        for code in follows:
            if not isinstance(code, str) or not MEMBER_CODE.fullmatch(code):
                raise Rejected(400, "invalid member code")
            if code not in codes:
                codes.append(code)
        cleaned["follows"] = codes
    if "searches" in data:
        searches = data["searches"]
        if not isinstance(searches, list) or len(searches) > MAX_SEARCHES:
            raise Rejected(400, f"searches must be a list of at most {MAX_SEARCHES}")
        kept, ids = [], set()
        for item in searches:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str) or not SEARCH_ID.fullmatch(item["id"])
                    or not isinstance(item.get("name"), str) or not 0 < len(item["name"].strip()) <= 80
                    or not (item.get("seen") is None or isinstance(item["seen"], str) and DAY.fullmatch(item["seen"]))
                    or set(item) - {"id", "name", "filters", "seen"}):
                raise Rejected(400, "invalid saved search")
            if item["id"] in ids:
                continue
            filters = clean_filters(item.get("filters") or {})
            if len(json.dumps(filters, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > SEARCH_FILTER_BYTES:
                raise Rejected(400, "saved search filters too long")
            ids.add(item["id"])
            kept.append({"id": item["id"], "name": item["name"].strip(), "filters": filters, "seen": item.get("seen")})
        cleaned["searches"] = kept
    if "theme" in data:  # The site's colour theme id; one value, last write wins.
        if not isinstance(data["theme"], str) or not THEME_ID.fullmatch(data["theme"]):
            raise Rejected(400, "theme must be a theme id")
        cleaned["theme"] = data["theme"]
    return cleaned


def clean_filters(filters) -> dict:
    if not isinstance(filters, dict):
        raise Rejected(400, "filters must be an object")
    kept = {}
    for name, value in filters.items():
        if name in TEXT_FILTERS and isinstance(value, str) and len(value) <= 200:
            kept[name] = value
        elif name in BOOL_FILTERS and isinstance(value, bool):
            kept[name] = value
        else:
            raise Rejected(400, "unsupported filter")
    return kept


def merge_data(stored: dict, cleaned: dict) -> dict:
    """A write replaces the sections it carries and keeps the rest, so a client that predates a section (an old
    cached page sends only `watch`) cannot erase what newer clients saved there."""
    merged = dict(cleaned)
    for section in OPTIONAL_SECTIONS:
        if section not in cleaned and section in stored:
            merged[section] = stored[section]
    return merged


def view_data(data: dict) -> dict:
    # View-only links share the watchlist (and its filters), never the rest of the profile such as follows.
    return {"watch": data.get("watch", []), "filters": data.get("filters", {})}


class Store:
    def __init__(self, path: Path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS lists (edit_hash TEXT PRIMARY KEY, view_hash TEXT UNIQUE NOT NULL,
                           data TEXT NOT NULL, version INTEGER NOT NULL, created_at INTEGER NOT NULL,
                           updated_at INTEGER NOT NULL, seen_at INTEGER NOT NULL)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS lists_seen ON lists(seen_at)")
        self.purged_at = 0.0

    def create(self, data: dict, now: float) -> str:
        with self.lock:
            if now - self.purged_at > 3600:
                self.db.execute("DELETE FROM lists WHERE seen_at < ?", (int(now - RETENTION_SECONDS),))
                self.purged_at = now
            if self.db.execute("SELECT COUNT(*) FROM lists").fetchone()[0] >= MAX_LISTS:
                raise Rejected(503, "sync storage is full")
            edit_key = secrets.token_urlsafe(16)
            self.db.execute("INSERT INTO lists VALUES (?, ?, ?, 1, ?, ?, ?)",
                            (key_hash(edit_key), key_hash(view_key_for(edit_key)), json.dumps(data),
                             int(now), int(now), int(now)))
            return edit_key

    def lookup(self, key: str, now: float) -> tuple[str, dict, int] | None:
        digest = key_hash(key)
        with self.lock:
            row = self.db.execute("SELECT 'edit', data, version, seen_at, edit_hash FROM lists WHERE edit_hash = ?",
                                  (digest,)).fetchone() or \
                self.db.execute("SELECT 'view', data, version, seen_at, edit_hash FROM lists WHERE view_hash = ?",
                                (digest,)).fetchone()
            if row is None:
                return None
            if now - row[3] > 86400:  # Retention clock; at most one write a day per list.
                self.db.execute("UPDATE lists SET seen_at = ? WHERE edit_hash = ?", (int(now), row[4]))
            return row[0], json.loads(row[1]), row[2]

    def update(self, edit_key: str, version: int, data: dict, now: float) -> tuple[int, dict]:
        """Returns the new version and the stored data (sections the write did not carry are kept)."""
        with self.lock:
            row = self.db.execute("SELECT data, version FROM lists WHERE edit_hash = ?", (key_hash(edit_key),)).fetchone()
            if row is None:
                raise Rejected(403 if self._is_view(edit_key) else 404, "an edit link is required")
            if version != row[1]:
                raise Rejected(409, "changed on another device", version=row[1], data=json.loads(row[0]))
            merged = merge_data(json.loads(row[0]), data)
            self.db.execute("UPDATE lists SET data = ?, version = ?, updated_at = ?, seen_at = ? WHERE edit_hash = ?",
                            (json.dumps(merged), row[1] + 1, int(now), int(now), key_hash(edit_key)))
            return row[1] + 1, merged

    def delete(self, edit_key: str) -> None:
        with self.lock:
            if self.db.execute("DELETE FROM lists WHERE edit_hash = ?", (key_hash(edit_key),)).rowcount == 0:
                raise Rejected(403 if self._is_view(edit_key) else 404, "an edit link is required")

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def _is_view(self, key: str) -> bool:
        return self.db.execute("SELECT 1 FROM lists WHERE view_hash = ?", (key_hash(key),)).fetchone() is not None


def rate_key(client: str) -> str:
    """One rate-limit bucket per IPv4 address or per IPv6 /64: one IPv6 visitor usually holds a whole /64 and could
    otherwise rotate addresses within it for fresh limits. Anything unparseable is used as given."""
    try:
        address = ipaddress.ip_address(client)
    except ValueError:
        return client
    if address.version == 6:
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((int(address) >> 64 << 64, 64)))
    return str(address)


class RateLimiter:
    def __init__(self, limits: dict = LIMITS):
        self.limits, self.hits, self.lock = limits, {}, threading.Lock()

    def check(self, client: str, kind: str, now: float) -> None:
        count, window = self.limits[kind]
        with self.lock:
            if len(self.hits) > 50_000:  # Bound memory under address churn.
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < window}
            hits = self.hits.setdefault((client, kind), deque())
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= count:
                raise Rejected(429, "too many requests", retry_after=int(window - (now - hits[0])) + 1)
            hits.append(now)


class Snapshot:
    def __init__(self, path: Path):
        self.path, self.mtime, self.bills, self.lock = path, None, {}, threading.Lock()

    def get(self) -> dict:
        with self.lock:
            try:
                mtime = self.path.stat().st_mtime
            except OSError:
                return self.bills
            if mtime != self.mtime:
                try:
                    data = json.loads(self.path.read_text("utf-8"))
                    self.bills = {b["id"]: b for b in data.get("bills", []) if isinstance(b, dict) and "id" in b}
                    self.mtime = mtime
                except (OSError, ValueError):
                    pass  # Keep serving the last good snapshot.
            return self.bills


class Reviews:
    """Published Luna tags (live/luna/tags.json), reloaded when the file changes."""

    def __init__(self, path: Path | None):
        self.path, self.mtime, self.entries, self.lock = path, None, {}, threading.Lock()

    def get(self) -> dict:
        if self.path is None:
            return {}
        with self.lock:
            try:
                mtime = self.path.stat().st_mtime
            except OSError:
                return self.entries
            if mtime != self.mtime:
                self.entries, self.mtime = build_feeds.load_reviews(self.path), mtime
            return self.entries


def watchlist_feed(bill_ids: list[str], bills: dict, site: str, reviews: dict | None = None) -> str:
    reviews = reviews or {}
    items = [item for bill_id in bill_ids if bill_id in bills
             for item in build_feeds.all_items(bills[bill_id], reviews.get(bill_id))]
    items.sort(key=lambda i: i["date"] or "", reverse=True)
    return build_feeds.render_rss("Watchlist · Texas Bill Atlas", site + "#watchlist",
                                  f"Latest actions on {len(bill_ids)} watched bills. Unofficial; confirm on "
                                  "Texas Legislature Online.", items[:FEED_ITEMS], site)


class App:
    def __init__(self, store: Store, snapshot: Snapshot, *, trust_proxy=False,
                 allowed_origins=("https://bills.ctharvey.me",), site=build_feeds.SITE, clock=time.time,
                 search: search_bills.Index | None = None, reviews: Reviews | None = None):
        self.store, self.snapshot, self.trust_proxy = store, snapshot, trust_proxy
        self.allowed_origins, self.site, self.clock = set(allowed_origins), site, clock
        self.search_index, self.reviews = search, reviews or Reviews(None)
        self.limiter = RateLimiter()

    def handle(self, method: str, path: str, headers, body: bytes | None, peer: str) -> tuple[int, dict, bytes]:
        now = self.clock()
        client = peer
        if self.trust_proxy and headers.get("X-Forwarded-For"):
            client = headers["X-Forwarded-For"].split(",")[-1].strip()  # The hop our proxy appended.
        client = rate_key(client)
        path, _, query = path.partition("?")
        if path == "/api/sync/health" and method == "GET":
            return self.json(200, {"ok": True})
        if path in SEARCH_PATHS:
            if method != "GET":
                raise Rejected(405, "method not allowed")
            self.limiter.check(client, "search", now)
            return self.search(path, query, headers)
        feed = FEED_RE.fullmatch(path)
        if feed and method == "GET":
            self.limiter.check(client, "read", now)
            found = self.store.lookup(feed[1], now)
            if found is None or found[0] != "view":
                raise Rejected(404, "unknown feed")  # Edit keys never work in URLs.
            text = watchlist_feed(found[1]["watch"], self.snapshot.get(), self.site, self.reviews.get())
            return 200, {"Content-Type": "application/rss+xml; charset=utf-8"}, text.encode("utf-8")
        if path != "/api/sync":
            raise Rejected(404, "not found")
        origin = headers.get("Origin")
        if origin and origin not in self.allowed_origins:
            raise Rejected(403, "origin not allowed")
        if method == "POST":
            self.limiter.check(client, "create", now)
            data = clean_data(self.read_json(headers, body).get("data"))
            edit_key = self.store.create(data, now)
            return self.json(201, {"mode": "edit", "edit_key": edit_key, "view_key": view_key_for(edit_key),
                                   "version": 1, "data": data})
        key = headers.get("X-Sync-Key", "")
        if not KEY_RE.fullmatch(key):
            raise Rejected(400, "missing or malformed sync key")
        if method == "GET":
            self.limiter.check(client, "read", now)
            found = self.store.lookup(key, now)
            if found is None:
                raise Rejected(404, "unknown sync link")
            mode, data, version = found
            payload = {"mode": mode, "version": version, "data": data, "view_key": view_key_for(key)}
            if mode == "view":
                payload.pop("view_key")
                payload["data"] = view_data(data)
            return self.json(200, payload)
        if method == "PUT":
            self.limiter.check(client, "write", now)
            request = self.read_json(headers, body)
            if not isinstance(request.get("version"), int):
                raise Rejected(400, "version is required")
            version, stored = self.store.update(key, request["version"], clean_data(request.get("data")), now)
            return self.json(200, {"version": version, "data": stored})
        if method == "DELETE":
            self.limiter.check(client, "write", now)
            self.store.delete(key)
            return 204, {}, b""
        raise Rejected(405, "method not allowed")

    def search(self, path: str, query: str, headers) -> tuple[int, dict, bytes]:
        index = self.search_index.get() if self.search_index else None
        if index is None or not index.docs:
            raise Rejected(503, "search data is not available yet; it is rebuilt hourly")
        try:
            params = search_bills.parse_params(query)
        except search_bills.BadQuery as error:
            raise Rejected(400, str(error)) from None
        accept = (headers.get("Accept") or "").lower()
        wants_json = path.endswith(".json") or params["format"] == "json" or (
            "application/json" in accept and "markdown" not in accept and "html" not in accept)
        if not params["q"] and not params["filters"]:
            if wants_json:
                return self.json(200, {"format": "texas-bill-atlas-search-v1", "usage": f"{search_bills.AGENT}search",
                                       "error": None, "results": []})
            return 200, {"Content-Type": "text/markdown; charset=utf-8"}, search_bills.usage(index.meta, index.topic_names).encode("utf-8")
        found = search_bills.search(index, params)
        if wants_json:
            return 200, {"Content-Type": "application/json"}, json.dumps(search_bills.as_json(found, params)).encode("utf-8")
        text = search_bills.as_markdown(found, params, search_bills.DISCLAIMER)
        return 200, {"Content-Type": "text/markdown; charset=utf-8"}, text.encode("utf-8")

    @staticmethod
    def read_json(headers, body: bytes | None) -> dict:
        if (headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            raise Rejected(415, "JSON required")
        try:
            value = json.loads(body or b"")
        except ValueError:
            raise Rejected(400, "invalid JSON") from None
        if not isinstance(value, dict):
            raise Rejected(400, "body must be an object")
        return value

    @staticmethod
    def json(status: int, payload: dict) -> tuple[int, dict, bytes]:
        return status, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version, sys_version, timeout = "TexasBillSync", "", 10

        def log_message(self, *args):
            pass  # Never log paths, keys or client addresses.

        def dispatch(self, method: str):
            unread = 0  # Body bytes refused without reading.
            try:
                body = None
                if method in ("POST", "PUT"):
                    try:
                        length = int(self.headers.get("Content-Length") or -1)
                    except ValueError:
                        length = -1
                    if length < 0:
                        raise Rejected(411, "length required")
                    if length > MAX_BODY:
                        unread = length
                        raise Rejected(413, "body too large")
                    body = self.rfile.read(length)
                status, headers, payload = app.handle(method, self.path, self.headers, body, self.client_address[0])
            except Rejected as error:
                extra = dict(error.extra)
                status, payload = error.status, json.dumps({"error": error.message, **extra}).encode("utf-8")
                headers = {"Content-Type": "application/json"}
                if "retry_after" in extra:
                    headers["Retry-After"] = str(extra["retry_after"])
            except Exception:
                status, headers, payload = 500, {"Content-Type": "application/json"}, b'{"error": "internal"}'
            self.send_response(status)
            for name, value in {**headers, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                "Referrer-Policy": "no-referrer"}.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            if unread:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            if unread:
                self.discard_body(unread)

        def discard_body(self, length: int):
            # Closing with the body still unread makes TCP send a reset, which can reach the client before it reads
            # the 413 (seen as WinError 10053). Answer first, then read and drop a bounded amount before closing.
            self.close_connection = True
            deadline = time.monotonic() + DISCARD_SECONDS
            try:
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_WR)
                left = min(length, DISCARD_LIMIT)
                while left > 0:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self.connection.settimeout(remaining)
                    chunk = self.rfile.read1(min(left, 65536))
                    if not chunk:
                        break
                    left -= len(chunk)
            except OSError:
                pass

        def do_GET(self): self.dispatch("GET")
        def do_POST(self): self.dispatch("POST")
        def do_PUT(self): self.dispatch("PUT")
        def do_DELETE(self): self.dispatch("DELETE")
    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # socketserver listens with a backlog of 5; under load the kernel then drops new connections and clients wait a
    # 1 s retry (seen from 100 requests a second in the 2026-11-10 load test).
    request_queue_size = 512


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Private SQLite file outside the web root")
    parser.add_argument("--snapshot", type=Path, required=True, help="live/bills.json, for watchlist feeds")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--trust-proxy", action="store_true", help="Use the proxy's X-Forwarded-For hop for rate limits")
    parser.add_argument("--allowed-origin", action="append", default=None)
    parser.add_argument("--search-data", type=Path, default=None, help="live/agent/data/bills.json, for /search")
    parser.add_argument("--tags", type=Path, default=None, help="live/luna/tags.json, for review items in feeds")
    args = parser.parse_args()
    app = App(Store(args.db), Snapshot(args.snapshot), trust_proxy=args.trust_proxy,
              allowed_origins=args.allowed_origin or ("https://bills.ctharvey.me",),
              search=search_bills.Index(args.search_data) if args.search_data else None, reviews=Reviews(args.tags))
    server = Server((args.host, args.port), make_handler(app))
    print(f"Sync service listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
