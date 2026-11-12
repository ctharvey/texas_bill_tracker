"""Near you (#local): the four ways to set a place, the result, privacy of the location and forgetting it."""

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "live"
BILLS = json.loads((FIXTURES / "bills.json").read_text(encoding="utf-8"))["bills"]

NEAR_KEY = "texas-bill-atlas-near-you-v1"
AUSTIN = {"latitude": 30.2672, "longitude": -97.7431}    # House 49, Senate 14 (no senator in the roster), Travis
ODESSA = {"latitude": 31.8457, "longitude": -102.3676}   # House 81 Landgraf, Senate 31 Sparks, Ector County
OUTSIDE_TEXAS = {"latitude": 40.7128, "longitude": -74.0060}
STUBBED_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}


def authored_numbers(name, chamber):
    return [b["number"] for b in BILLS if name in b["authors"] and b["chamber"] == chamber]


def open_setup(device):
    page = device.open("#local")
    expect(page.locator("#near-locate")).to_be_enabled()   # the district files have loaded
    return page


def use_location(device, point):
    device.context.grant_permissions(["geolocation"])
    device.context.set_geolocation(point)
    page = open_setup(device)
    page.locator("#near-locate").click()
    expect(page.locator("#near-forget")).to_be_visible()
    return page


def group(page, title_start):
    return page.locator(".today-group", has=page.locator(f"h3:has-text('{title_start}')"))


def watch_requests(page):
    seen = []
    page.on("request", lambda r: seen.append((r.method, r.url)))
    return seen


def assert_no_sync_traffic(requests):
    """The page may ask the sync service whether it is up (GET /api/sync/health on load); it must send it nothing else."""
    sync = [(m, u) for m, u in requests if "/api/sync" in u]
    assert all(m == "GET" and u.endswith("/api/sync/health") for m, u in sync), sync


def test_setup_screen_offers_every_way_and_the_privacy_notice(device):
    page = open_setup(device)
    expect(page.locator("#page-title")).to_contain_text("Near you.")
    content = page.locator("#dynamic-content")
    expect(content.get_by_role("heading", name="Find your legislators")).to_be_visible()
    expect(content).to_contain_text(
        "Your location is used once, in this browser, to find your districts. Only the district numbers and county "
        "are saved on this device; nothing is sent to this site.")
    for heading in ("Use my location", "Choose your county", "Enter your districts"):
        expect(content.get_by_role("heading", name=heading)).to_be_visible()
    expect(page.locator("#near-county option")).not_to_have_count(1)    # the county list is loaded
    assert page.locator("#near-county option").first.inner_text() == "Select a county"
    expect(page.locator("#near-county option", has_text="Travis")).to_have_count(1)
    expect(page.locator(".near-address summary")).to_have_text("Look up an address instead (optional)")
    assert NEAR_KEY not in device.storage()


def test_use_my_location_shows_house_member_and_county_bills(device):
    requests = watch_requests(device.page)
    page = use_location(device, ODESSA)
    expect(page.locator(".near-summary")).to_contain_text("House District 81 · Senate District 31 · Ector County")
    expect(page.locator(".near-summary")).to_contain_text("from your location")
    cards = page.locator(".near-member")
    expect(cards).to_have_count(2)
    expect(cards.nth(0)).to_contain_text("Texas House · District 81")
    expect(cards.nth(0)).to_contain_text("Rep. Brooks Landgraf")
    expect(cards.nth(0)).to_contain_text("Senior")
    expect(cards.nth(0)).to_contain_text("Republican · 12 years in the House")
    expect(cards.nth(0).get_by_role("link", name="All their bills →")).to_have_attribute("href", "#member?code=A3040")
    expect(cards.nth(1)).to_contain_text("Texas Senate · District 31")
    expect(cards.nth(1)).to_contain_text("Sen. Kevin Sparks")

    expected = authored_numbers("Landgraf", "House") + authored_numbers("Sparks", "Senate")
    members_group = group(page, "Filed or signed by your legislators")
    expect(members_group.locator("h3 span")).to_have_text(str(len(expected)))
    expect(members_group.locator(".today-row")).to_have_count(min(30, len(expected)))
    expect(members_group.locator(".today-row").first.locator(".today-action")).to_contain_text("· Author")
    expect(members_group.locator("[data-near-more]")).to_have_text(f"Show 30 more · showing 30 of {len(expected)}")

    area = group(page, "Bills that name Ector County")
    expect(area.locator("h3 span")).to_have_text("1")
    expect(area.locator(".today-row")).to_have_count(1)
    expect(area.locator(".today-row .today-action")).to_have_text("Names Ector County")
    expect(page.locator("#dynamic-content")).to_contain_text("reviewed bills apply statewide and are not listed here.")

    assert_no_sync_traffic(requests)


def test_location_in_austin_names_the_city_and_county_in_local_bills(device):
    page = use_location(device, AUSTIN)
    expect(page.locator(".near-summary")).to_contain_text("House District 49 · Senate District 14 · Travis County")
    expect(page.locator(".near-members .near-member").nth(0)).to_contain_text("Rep. Montserrat Garibay")
    expect(page.locator(".near-members .near-member").nth(1)).to_contain_text("No member listed yet")
    area = group(page, "Bills that name Travis County")
    expect(area.locator("h3 span")).to_have_text("17")
    # Bills naming a city point at it, with its county, as well as plain county mentions.
    expect(area.locator(".today-action", has_text="Names Austin (Travis County)").first).to_be_visible()
    expect(area.locator(".today-action", has_text="Names Travis County").first).to_be_visible()
    expect(group(page, "Filed or signed by your legislators").locator(".review-empty")).to_have_text(
        "No bills by your legislators in this snapshot yet.")


def test_location_stays_on_the_device(device):
    requests = watch_requests(device.page)
    page = use_location(device, ODESSA)
    expect(page.locator(".near-summary")).to_contain_text("Ector County")
    stored = device.storage()[NEAR_KEY]
    # Only district numbers, county and how they were chosen: never coordinates.
    assert json.loads(stored) == {"house": "81", "senate": "31", "county": "Ector", "source": "location", "near": False}
    everything = json.dumps(device.storage())
    for fragment in ("31.84", "-102.36", "latitude", "longitude"):
        assert fragment not in everything
    assert "31.84" not in page.url and "102.36" not in page.url
    origin = device.site.base
    outside = [u for m, u in requests if not u.startswith(origin)]
    assert {urlparse(u).hostname for u in outside} <= STUBBED_HOSTS, outside
    inside = [(m, u) for m, u in requests if u.startswith(origin)]
    assert any(u.endswith("/data/geo/districts.json") for m, u in inside)   # control: we did see local fetches
    assert all(m == "GET" for m, u in inside)
    assert_no_sync_traffic(requests)
    assert not [u for m, u in inside if "31.84" in u or "102.36" in u]


def test_location_survives_reload_then_forget_clears_it(device):
    page = use_location(device, ODESSA)
    page.reload(wait_until="networkidle")
    expect(page.locator(".near-summary")).to_contain_text("House District 81 · Senate District 31 · Ector County")
    page.locator("#near-forget").click()
    expect(page.locator("#toast")).to_have_text("Your districts were removed from this device")
    expect(page.locator("#near-locate")).to_be_visible()
    expect(page.locator(".near-summary")).to_have_count(0)
    assert NEAR_KEY not in device.storage()
    page.reload(wait_until="networkidle")
    expect(page.locator("#near-locate")).to_be_visible()
    assert NEAR_KEY not in device.storage()


def test_change_returns_to_setup_and_a_new_choice_replaces_the_place(device):
    page = use_location(device, ODESSA)
    page.locator("#near-change").click()
    expect(page.locator("#near-locate")).to_be_visible()
    expect(page.locator(".near-summary")).to_have_count(0)
    # Current behavior: "Change" only reopens the setup screen; the saved place stays until a new one replaces it.
    assert json.loads(device.storage()[NEAR_KEY])["house"] == "81"
    # ...so a reload brings the old place straight back.
    page.reload(wait_until="networkidle")
    expect(page.locator(".near-summary")).to_contain_text("House District 81 · Senate District 31 · Ector County")
    page.locator("#near-change").click()
    page.locator("#near-house-num").fill("123")
    page.locator("#near-senate-num").fill("26")
    page.locator("#near-numbers-use").click()
    expect(page.locator(".near-summary")).to_contain_text("House District 123 · Senate District 26")
    assert json.loads(device.storage()[NEAR_KEY]) == {"house": "123", "senate": "26", "county": None,
                                                      "source": "district", "near": False}


def test_pick_district_numbers(device):
    page = open_setup(device)
    page.locator("#near-house-num").fill("123")
    page.locator("#near-senate-num").fill("26")
    page.locator("#near-numbers-use").click()
    summary = page.locator(".near-summary")
    expect(summary).to_contain_text("House District 123 · Senate District 26")
    expect(summary).to_contain_text("from the districts you entered")
    cards = page.locator(".near-member")
    expect(cards.nth(0)).to_contain_text("Rep. Diego Bernal")
    expect(cards.nth(1)).to_contain_text("Sen. José Menéndez")
    assert json.loads(device.storage()[NEAR_KEY]) == {"house": "123", "senate": "26", "county": None,
                                                      "source": "district", "near": False}
    # With no county, local bills come from every county of the House district.
    expect(page.locator(".today-group h3").nth(1)).to_contain_text("Bills that name your district's county")


def test_district_numbers_out_of_range_are_refused(device):
    page = open_setup(device)
    page.locator("#near-house-num").fill("151")
    page.locator("#near-senate-num").fill("32")
    page.locator("#near-numbers-use").click()
    expect(page.locator(".near-error")).to_have_text(
        "Enter a House district from 1 to 150, a Senate district from 1 to 31, or both.")
    assert NEAR_KEY not in device.storage()


def test_pick_county_with_one_district_each(device):
    page = open_setup(device)
    page.locator("#near-county").select_option("Midland")
    page.locator("#near-county-use").click()
    summary = page.locator(".near-summary")
    expect(summary).to_contain_text("House District 82 · Senate District 31 · Midland County")
    expect(summary).to_contain_text("from your county")
    expect(summary.locator(".near-hint")).to_have_count(0)
    assert json.loads(device.storage()[NEAR_KEY]) == {"house": "82", "senate": "31", "county": "Midland",
                                                      "source": "county", "near": False}


def test_pick_county_split_between_districts_asks_which_and_warns(device):
    page = open_setup(device)
    page.locator("#near-county").select_option("Webb")
    pick = page.locator("#near-house-pick")
    expect(pick).to_be_visible()
    options = [o.strip() for o in pick.locator("option").all_inner_texts()]
    assert options[0].startswith("District 42 · 69% of Webb County")      # largest share first
    assert options[1].startswith("District 80 · 31% of Webb County")
    expect(page.locator("#near-senate-pick")).to_have_count(0)               # one Senate district: no choice
    expect(page.locator(".near-setup")).to_contain_text("Your county has more than one district.")
    pick.select_option("80")
    page.locator("#near-county-use").click()
    summary = page.locator(".near-summary")
    expect(summary).to_contain_text("House District 80 · Senate District 21 · Webb County")
    expect(summary.locator(".near-hint")).to_contain_text(
        "Webb County has more than one district, so these are the ones you picked.")
    assert json.loads(device.storage()[NEAR_KEY]) == {"house": "80", "senate": "21", "county": "Webb",
                                                      "source": "county", "near": True}


def test_location_outside_texas_is_refused_and_nothing_is_saved(device):
    device.context.grant_permissions(["geolocation"])
    device.context.set_geolocation(OUTSIDE_TEXAS)
    page = open_setup(device)
    page.locator("#near-locate").click()
    expect(page.locator(".near-error")).to_have_text(
        "That location is outside Texas, so it has no Texas House or Senate district.")
    assert NEAR_KEY not in device.storage()


def test_declined_location_permission_explains_and_offers_the_other_ways(device):
    page = open_setup(device)   # permission not granted: the browser denies the request
    page.locator("#near-locate").click()
    expect(page.locator(".near-error")).to_have_text(
        "Location permission was declined. Choose your county or enter your districts instead.")
    expect(page.locator("#near-county")).to_be_visible()
    assert NEAR_KEY not in device.storage()


def census_reply(x, y, matched="1100 CONGRESS AVE, AUSTIN, TX, 78701"):
    return {"result": {"addressMatches": [{"matchedAddress": matched, "coordinates": {"x": x, "y": y}}]}}


def mock_census(device, reply, log):
    def handle(route):
        url = route.request.url
        log.append(url)
        callback = parse_qs(urlparse(url).query)["callback"][0]
        route.fulfill(status=200, content_type="text/javascript", body=f"{callback}({json.dumps(reply)});")
    device.context.route("https://geocoding.geo.census.gov/**", handle)


def test_address_lookup_uses_the_census_geocoder_and_keeps_only_districts(device):
    census = []
    mock_census(device, census_reply(ODESSA["longitude"], ODESSA["latitude"]), census)
    page = open_setup(device)
    requests = watch_requests(page)
    page.locator(".near-address summary").click()
    expect(page.locator(".near-address")).to_contain_text("sends the address you type to the US Census Bureau")
    page.locator("#near-address").fill("500 N Grant Ave, Odessa, TX 79761")
    page.get_by_role("button", name="Look up").click()
    summary = page.locator(".near-summary")
    expect(summary).to_contain_text("House District 81 · Senate District 31 · Ector County")
    expect(summary).to_contain_text("from the address you looked up")
    expect(page.locator(".near-member").nth(0)).to_contain_text("Rep. Brooks Landgraf")

    assert len(census) == 1
    query = parse_qs(urlparse(census[0]).query)
    assert census[0].startswith("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?")
    assert query["address"] == ["500 N Grant Ave, Odessa, TX 79761"]
    assert query["benchmark"] == ["Public_AR_Current"] and query["format"] == ["jsonp"]
    assert re.fullmatch(r"nearCensus\d+", query["callback"][0])

    assert json.loads(device.storage()[NEAR_KEY]) == {"house": "81", "senate": "31", "county": "Ector",
                                                      "source": "address", "near": False}
    everything = json.dumps(device.storage())
    assert "Grant" not in everything and "79761" not in everything and "31.84" not in everything
    assert "Grant" not in page.url
    origin = device.site.base
    # Only the census geocoder is contacted off-origin; nothing about the address reaches this site or /api/sync.
    hosts = {urlparse(u).hostname for m, u in requests if not u.startswith(origin)}
    assert hosts <= STUBBED_HOSTS | {"geocoding.geo.census.gov"}, hosts
    assert_no_sync_traffic(requests)
    assert not [u for m, u in requests if u.startswith(origin) and ("Grant" in u or "79761" in u)]


def test_address_with_no_match_says_so_and_saves_nothing(device):
    mock_census(device, {"result": {"addressMatches": []}}, [])
    page = open_setup(device)
    page.locator(".near-address summary").click()
    page.locator("#near-address").fill("1 Nowhere Lane, Nowhere, TX 00000")
    page.get_by_role("button", name="Look up").click()
    expect(page.locator(".near-error")).to_have_text(
        "The Census geocoder found no match for that address. Check the spelling, or choose your county.")
    assert NEAR_KEY not in device.storage()


def test_short_address_is_rejected_without_a_lookup(device):
    census = []
    mock_census(device, census_reply(-97.7, 30.2), census)
    page = open_setup(device)
    page.locator(".near-address summary").click()
    page.locator("#near-address").fill("1 Elm")
    page.get_by_role("button", name="Look up").click()
    expect(page.locator(".near-error")).to_have_text("Enter a street address, city and ZIP code.")
    assert census == []


def test_address_outside_texas_is_refused(device):
    mock_census(device, census_reply(-74.0060, 40.7128, "NEW YORK, NY"), [])
    page = open_setup(device)
    page.locator(".near-address summary").click()
    page.locator("#near-address").fill("350 5th Ave, New York, NY 10118")
    page.get_by_role("button", name="Look up").click()
    expect(page.locator(".near-error")).to_have_text(
        "That location is outside Texas, so it has no Texas House or Senate district.")
    assert NEAR_KEY not in device.storage()


def test_unreachable_geocoder_says_so(device):
    # The harness aborts the census host by default, so the lookup script fails to load.
    page = open_setup(device)
    page.locator(".near-address summary").click()
    page.locator("#near-address").fill("500 N Grant Ave, Odessa, TX 79761")
    page.get_by_role("button", name="Look up").click()
    expect(page.locator(".near-error")).to_have_text(
        "The address lookup could not be reached. Choose your county instead.")
    assert NEAR_KEY not in device.storage()
