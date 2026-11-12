"""Private sync links, end to end: create on one device, join from another, edits travel, conflicts lose nothing,
view-only links are read-only and show only the watchlist, deleting a link keeps the local list, and edit keys never
sit in the address bar.

Every test that creates a link uses `fresh_sync` (empty database, fresh rate limiter). Devices are separate browser
profiles; the "server" is the real sync service. The page clock is frozen, so the 30-second focus re-sync cannot fire
by itself: "pulling" on another device is reloading the page, which is what a person does (and what runs on open).
"""

import json
import re
import time

from playwright.sync_api import expect

WATCH = ["HB110", "HB239"]
MEMBER = "A4395"
SYNC_KEY = "tx-bill-atlas-sync-v1"
EDIT_RE = r"#watchlist\?sync=[A-Za-z0-9_-]{22}$"


def grant_clipboard(device):
    device.context.grant_permissions(["clipboard-read", "clipboard-write"])


def star(device, bill):
    page = device.open(f"#all?bill={bill}")
    page.locator(f"#detail-drawer [data-watch='{bill}']").first.click()
    page.wait_for_function(f"JSON.parse(localStorage.getItem('tx-bill-atlas-watch-90r')||'[]').includes('{bill}')")


def follow(device, code):
    page = device.open(f"#member?code={code}")
    page.locator(f"[data-follow='{code}']").first.click()
    page.wait_for_function(f"JSON.parse(localStorage.getItem('tx-bill-atlas-follow-90r')||'[]').includes('{code}')")


def save_search(device, chamber="House"):
    page = device.open("#all")
    page.select_option("#filter-chamber", label=chamber)
    page.click("#save-search")
    page.wait_for_function("JSON.parse(localStorage.getItem('tx-bill-atlas-searches-90r')||'[]').length>=1")


def owner_with_link(device_factory):
    """Device A: a watchlist, a followed legislator and a saved search, then 'Create sync link' as the person would.
    Returns (device, edit_link_text, view_link_text)."""
    a = device_factory()
    grant_clipboard(a)
    for bill in WATCH:
        star(a, bill)
    follow(a, MEMBER)
    save_search(a)
    page = a.open("#watchlist")
    page.click("#sync-create")
    expect(page.locator("#toast")).to_have_text("Sync link created. Copy the edit link to your other devices.")
    expect(page.locator("#sync-copy-edit")).to_be_visible()
    texts = {}
    for name, button in (("edit", "#sync-copy-edit"), ("view", "#sync-copy-view")):
        page.click(button)
        expect(page.locator("#toast")).to_contain_text(f"{'Edit' if name == 'edit' else 'View-only'} link copied")
        texts[name] = page.evaluate("navigator.clipboard.readText()")
    return a, texts["edit"], texts["view"]


def key_of(link):
    return link.rsplit("sync=", 1)[1]


def hash_of(link):
    return "#" + link.split("#", 1)[1]


def server_data(device, key):
    reply = device.page.request.get(device.site.base + "api/sync", headers={"X-Sync-Key": key})
    assert reply.status == 200, reply.status
    return reply.json()


def wait_server(device, key, check, message):
    def read():
        return check(server_data(device, key)["data"])
    deadline = time.monotonic() + 15
    while not read():  # Bounded retry on the service's state (no page signal exists for "the write landed").
        assert time.monotonic() < deadline, message
        time.sleep(0.1)


def reopen(device, hash_):
    """A real page load (a goto that only changes the hash would not run the on-open pull)."""
    page = device.open(hash_)
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#dynamic-content *", state="attached", timeout=20000)
    return page


def stored_list(device, key):
    return json.loads(device.storage().get(key, "[]"))


def test_create_link_on_one_device_and_the_links_are_well_formed(device_factory, fresh_sync, site):
    a, edit, view = owner_with_link(device_factory)
    assert edit.startswith(site.base) and view.startswith(site.base)
    assert re.search(EDIT_RE, edit) and re.search(EDIT_RE, view)
    assert key_of(edit) != key_of(view)
    link = json.loads(a.storage()[SYNC_KEY])
    assert link["mode"] == "edit" and link["key"] == key_of(edit) and link["viewKey"] == key_of(view)
    page = a.page
    expect(page.get_by_text("This device is synced; changes save automatically.")).to_be_visible()
    expect(page.locator("#sync-create")).to_have_count(0)
    assert key_of(edit) not in page.url  # the edit key never sits in the address bar
    # The service now holds A's whole list.
    data = server_data(a, key_of(edit))["data"]
    assert data["watch"] == WATCH and data["follows"] == [MEMBER] and len(data["searches"]) == 1


def test_second_device_opens_the_edit_link_and_gets_everything(device_factory, fresh_sync):
    a, edit, _ = owner_with_link(device_factory)
    b = device_factory()
    page = b.open(hash_of(edit))
    expect(page.locator("#toast")).to_have_text("This device is now synced")
    expect(page.locator("#nav-watch")).to_have_text(str(len(WATCH)))
    expect(page.locator("#nav-follow")).to_have_text("2")  # one follow + one saved search
    for bill in WATCH:
        expect(page.locator(f"#bill-list [data-watch='{bill}']")).to_have_attribute("aria-pressed", "true")
    assert key_of(edit) not in page.url and "sync=" not in page.url  # edit key never in the address bar
    expect(page.locator("#sync-copy-edit")).to_be_visible()
    page = b.open("#following")
    expect(page.locator(".followed-member")).to_have_count(1)
    expect(page.locator(".saved-search")).to_have_count(1)
    assert stored_list(b, "tx-bill-atlas-watch-90r") == WATCH
    assert stored_list(b, "tx-bill-atlas-follow-90r") == [MEMBER]
    assert json.loads(b.storage()[SYNC_KEY])["key"] == key_of(edit)
    assert key_of(edit) not in "".join(p.url for p in b.context.pages)


def test_an_edit_on_the_second_device_reaches_the_first_when_it_pulls(device_factory, fresh_sync):
    a, edit, _ = owner_with_link(device_factory)
    b = device_factory()
    b.open(hash_of(edit))
    expect(b.page.locator("#toast")).to_have_text("This device is now synced")
    star(b, "HB381")
    follow(b, "A2150")
    wait_server(b, key_of(edit), lambda d: "HB381" in d["watch"] and "A2150" in d["follows"], "B's edits reach the server")
    # A reloads (the same pull that runs when a synced page opens).
    page = reopen(a, "#watchlist")
    expect(page.locator("#nav-watch")).to_have_text(str(len(WATCH) + 1))
    expect(page.locator("#bill-list [data-watch='HB381']")).to_have_attribute("aria-pressed", "true")
    assert stored_list(a, "tx-bill-atlas-watch-90r") == [*WATCH, "HB381"]
    assert stored_list(a, "tx-bill-atlas-follow-90r") == [MEMBER, "A2150"]
    expect(page.locator("#nav-follow")).to_have_text("3")


def test_conflicting_edits_both_survive(device_factory, fresh_sync):
    """A and B hold the same version; A writes first, then B writes from its stale version. The server answers 409,
    the app replays B's change on top of A's and retries: nothing is lost and no error is shown."""
    a, edit, _ = owner_with_link(device_factory)
    b = device_factory()
    b.open(hash_of(edit))
    expect(b.page.locator("#toast")).to_have_text("This device is now synced")
    b.open("#all")
    puts = []
    b.page.on("response", lambda r: r.url.endswith("/api/sync") and r.request.method == "PUT" and puts.append(r.status))
    star(a, "HB381")  # A's write lands first.
    wait_server(a, key_of(edit), lambda d: "HB381" in d["watch"], "A's edit reaches the server")
    # B has not pulled since joining; it still holds the version from before A's write.
    page = b.open("#all?bill=HB1003")
    is_put_ok = lambda r: r.url.endswith("/api/sync") and r.request.method == "PUT" and r.status == 200
    with page.expect_response(is_put_ok, timeout=15000):
        page.locator("#detail-drawer [data-watch='HB1003']").first.click()
    assert 409 in puts, puts  # B wrote from a stale version: the conflict happened, and the retry then succeeded
    wait_server(b, key_of(edit), lambda d: "HB1003" in d["watch"] and "HB381" in d["watch"], "both edits on the server")
    assert server_data(b, key_of(edit))["data"]["watch"] == [*WATCH, "HB381", "HB1003"]
    expect(page.locator("#toast")).not_to_contain_text("Sync")  # no error shown to the person
    expect(page.locator("#nav-watch")).to_have_text(str(len(WATCH) + 2))  # B now shows A's bill too
    reopen(a, "#watchlist")
    expect(a.page.locator("#nav-watch")).to_have_text(str(len(WATCH) + 2))
    assert stored_list(a, "tx-bill-atlas-watch-90r") == [*WATCH, "HB381", "HB1003"]


def test_conflict_across_sections_keeps_every_follow_and_search(device_factory, fresh_sync):
    a, edit, _ = owner_with_link(device_factory)
    b = device_factory()
    b.open(hash_of(edit))
    expect(b.page.locator("#toast")).to_have_text("This device is now synced")
    b.open("#all")
    follow(a, "A2150")
    wait_server(a, key_of(edit), lambda d: "A2150" in d["follows"], "A's follow reaches the server")
    save_search(b, "Senate")  # B is stale: A's follow is not in B's version.
    wait_server(b, key_of(edit), lambda d: len(d["searches"]) == 2 and "A2150" in d["follows"], "merged on the server")
    data = server_data(b, key_of(edit))["data"]
    assert data["follows"] == [MEMBER, "A2150"] and data["watch"] == WATCH
    assert sorted(s["filters"]["chamber"] for s in data["searches"]) == ["House", "Senate"]


def test_view_only_link_shows_the_watchlist_only_and_refuses_edits(device_factory, fresh_sync, site):
    a, edit, view = owner_with_link(device_factory)
    c = device_factory()
    page = c.open(hash_of(view))
    expect(page.locator(".shared-banner")).to_contain_text(f"Shared watchlist (view-only) · {len(WATCH)} bills")
    expect(page.locator("#toast")).to_have_text("Showing a shared watchlist (view-only)")
    expect(page.locator("#result-count")).to_have_text(f"{len(WATCH)} bills")
    for bill in WATCH:
        expect(page.locator(f"#bill-list [data-bill-id='{bill}']")).to_have_count(1)
    assert key_of(edit) not in page.url
    storage = c.storage()
    assert SYNC_KEY not in storage  # a view-only link never becomes this device's own link
    assert not json.loads(storage.get("tx-bill-atlas-follow-90r", "[]"))
    assert not json.loads(storage.get("tx-bill-atlas-searches-90r", "[]"))
    expect(page.locator("#nav-follow")).to_have_text("0")
    following = c.open("#following")
    expect(following.locator(".followed-member")).to_have_count(0)
    expect(following.locator(".saved-search")).to_have_count(0)
    # On the wire: the view key reads only the watchlist (and its filters), and cannot write or delete.
    base = site.base + "api/sync"
    view_reply = c.page.request.get(base, headers={"X-Sync-Key": key_of(view)}).json()
    assert view_reply["mode"] == "view" and set(view_reply["data"]) == {"watch", "filters"}
    assert view_reply["data"]["watch"] == WATCH and "view_key" not in view_reply
    put = c.page.request.put(base, headers={"X-Sync-Key": key_of(view), "Content-Type": "application/json"},
                             data=json.dumps({"version": view_reply["version"], "data": {"watch": ["HB1"]}}))
    assert put.status == 403
    assert c.page.request.delete(base, headers={"X-Sync-Key": key_of(view)}).status == 403
    assert server_data(a, key_of(edit))["data"]["watch"] == WATCH  # untouched


def test_view_only_list_can_be_copied_without_changing_the_link(device_factory, fresh_sync):
    a, edit, view = owner_with_link(device_factory)
    before = server_data(a, key_of(edit))
    c = device_factory()
    page = c.open(hash_of(view))
    expect(page.locator(".shared-banner")).to_be_visible()
    page.click("#shared-add")
    expect(page.locator("#toast")).to_have_text(f"Added {len(WATCH)} bills to your watchlist")
    assert stored_list(c, "tx-bill-atlas-watch-90r") == WATCH
    assert SYNC_KEY not in c.storage()
    after = server_data(a, key_of(edit))
    assert after["version"] == before["version"] and after["data"] == before["data"]


def test_deleting_the_link_keeps_the_list_on_the_device(device_factory, fresh_sync, site):
    a, edit, view = owner_with_link(device_factory)
    b = device_factory()
    b.open(hash_of(edit))
    expect(b.page.locator("#toast")).to_have_text("This device is now synced")
    page = a.open("#watchlist")
    page.click("#sync-delete")
    expect(page.locator("#sync-delete")).to_have_text("Click again to delete for every device")  # arms; nothing deleted yet
    assert server_data(a, key_of(edit))["data"]["watch"] == WATCH
    page.click("#sync-delete")
    expect(page.locator("#toast")).to_have_text("Sync link deleted; your list stays on this device")
    expect(page.locator("#sync-create")).to_be_visible()  # offers a new link; no longer synced
    expect(page.locator("#nav-watch")).to_have_text(str(len(WATCH)))
    for bill in WATCH:
        expect(page.locator(f"#bill-list [data-watch='{bill}']")).to_have_attribute("aria-pressed", "true")
    storage = a.storage()
    assert SYNC_KEY not in storage
    assert json.loads(storage["tx-bill-atlas-watch-90r"]) == WATCH
    assert json.loads(storage["tx-bill-atlas-follow-90r"]) == [MEMBER]
    assert len(json.loads(storage["tx-bill-atlas-searches-90r"])) == 1
    # The service forgot the list: both keys are unknown now.
    for key in (key_of(edit), key_of(view)):
        assert page.request.get(site.base + "api/sync", headers={"X-Sync-Key": key}).status == 404
    # The other device is told the link is gone, and keeps its own copy of the list.
    page_b = reopen(b, "#watchlist")
    expect(page_b.locator("#toast")).to_have_text("Sync: This sync link no longer exists")
    expect(page_b.locator("#nav-watch")).to_have_text(str(len(WATCH)))
    assert stored_list(b, "tx-bill-atlas-watch-90r") == WATCH
    assert SYNC_KEY not in b.storage()


def test_stop_syncing_keeps_the_list_and_leaves_the_link_alive(device_factory, fresh_sync):
    a, edit, _ = owner_with_link(device_factory)
    page = a.open("#watchlist")
    page.click("#sync-forget")
    expect(page.locator("#toast")).to_have_text("This device stopped syncing; your list stays here")
    assert SYNC_KEY not in a.storage()
    assert stored_list(a, "tx-bill-atlas-watch-90r") == WATCH
    assert server_data(a, key_of(edit))["data"]["watch"] == WATCH  # the link itself still works for other devices


def test_edit_key_is_never_written_to_the_address_bar(device_factory, fresh_sync):
    """The app puts only a view-only key in the address (prefs.js buildHash); the edit key lives in storage and the
    X-Sync-Key header. After a device joins from a pasted edit link, nothing it does leaves the key in the address."""
    a, edit, view = owner_with_link(device_factory)
    key = key_of(edit)
    assert key not in a.page.url
    b = device_factory()
    b.open(hash_of(edit))
    expect(b.page.locator("#toast")).to_have_text("This device is now synced")
    assert key not in b.page.url  # already stripped from the address the moment the link was joined
    for view_name in ("#following", "#all", "#watchlist"):
        b.open(view_name)
        assert key not in b.page.url
    # The address with a view-only link does carry that (shareable) key, and still never the edit key.
    c = device_factory()
    c.open(hash_of(view))
    expect(c.page.locator(".shared-banner")).to_be_visible()
    assert key_of(view) in c.page.url and key not in c.page.url
    expect(c.page.locator("#result-count")).to_be_visible()
    c.page.click("#shared-close")
    assert key not in c.page.url
