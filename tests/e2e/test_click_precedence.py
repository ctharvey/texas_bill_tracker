"""handleClick is an ordered chain of closest() checks, so which control wins when targets nest is behavior.

Each test clicks the innermost control inside a bill card, row or bill page and checks that the outer card did not also act.
"""

import re

from playwright.sync_api import expect


def card(page, bill):
    return page.locator(f'#bill-list article.bill-card[data-bill-id="{bill}"]')


def first_bill(page):
    """(id, 'HB 110' style number) of the first card in the explorer; HB110 itself is not on the first page."""
    first = page.locator("#bill-list article.bill-card").first
    first.wait_for()
    return first.get_attribute("data-bill-id"), first.locator(".bill-number").inner_text().replace(chr(10), " ")


def wide(page):
    """At 1200px and up a card body opens the preview beside the results; below it, the bill page."""
    return page.viewport_size["width"] >= 1200


def expect_card_opened(page, bill, number):
    if wide(page):
        expect(page.locator("#bill-preview")).to_be_visible()
        expect(page.locator("#bill-preview .bill-number")).to_have_text(number)
        expect(page.locator("#bill-page")).to_have_count(0)
    else:
        expect(page.locator("#bill-page")).to_be_visible()
        expect(page.locator("#bill-page .drawer-number")).to_have_text(f"90R / {number}")
        assert f"#bill?id={bill}" in page.url


def watch_keys(device):
    return {k: v for k, v in device.storage().items() if "watch" in k.lower() and "disclaimer" not in k.lower()}


# ---- inside a bill card ----

def test_watch_button_in_a_card_toggles_the_watch_and_does_not_open_the_bill_page(device):
    page = device.open("#all")
    bill, number = first_bill(page)
    star = card(page, bill).locator(".watch-button")
    expect(star).to_have_attribute("aria-pressed", "false")
    star.click()
    expect(card(page, bill).locator(".watch-button")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#toast")).to_have_text(f"{bill} added to your watchlist")
    expect(page.locator("#bill-page")).to_be_hidden()
    assert "#bill?" not in page.url
    assert bill in "".join(watch_keys(device).values())
    card(page, bill).locator(".watch-button").click()
    expect(card(page, bill).locator(".watch-button")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#toast")).to_have_text(f"{bill} removed from your watchlist")
    expect(page.locator("#bill-page")).to_be_hidden()


def test_card_body_opens_the_preview_when_wide_and_the_bill_page_on_a_phone(device):
    page = device.open("#all")
    bill, number = first_bill(page)
    card(page, bill).locator(".bill-filed").click()
    expect_card_opened(page, bill, number)


def test_plain_tags_inside_a_card_are_not_controls(device):
    page = device.open("#all")
    bill, number = first_bill(page)
    card(page, bill).locator(".action-tag").click()
    expect_card_opened(page, bill, number)


def test_bill_details_button_number_and_title_each_open_the_bill_page(device):
    page = device.open("#all")
    bill, number = first_bill(page)
    for selector in (".bill-open", ".bill-number", ".bill-title-link"):
        card(page, bill).locator(selector).click()
        expect(page.locator("#bill-page .drawer-number")).to_have_text(f"90R / {number}")
        page.locator("#bill-back").click()
        expect(page.locator("#bill-page")).to_be_hidden()


def test_author_link_in_a_card_goes_to_the_member_page_without_opening_the_bill_page(device):
    page = device.open("#all")
    link = page.locator("#bill-list article.bill-card a.member-name").first
    parent = link.locator("xpath=ancestor::article")
    link.click()
    expect(page.locator("#page-title")).to_contain_text("One legislator.")
    assert re.search(r"#member\?code=", page.url)
    expect(page.locator("#bill-page")).to_be_hidden()
    assert "#bill?" not in page.url


def test_companion_tag_in_a_card_opens_the_companion_not_the_card(device):
    page = device.open("#all")
    tag = page.locator("#bill-list .companion-tag").first
    expect(tag).to_be_visible()
    owner = tag.locator("xpath=ancestor::article").get_attribute("data-bill-id")
    companion = tag.get_attribute("data-open")
    assert owner != companion
    tag.click()
    expect(page.locator("#bill-page .drawer-number")).to_have_text(re.compile(r"^90R / "))
    assert f"#bill?id={companion}" in page.url


def test_selecting_text_in_a_card_does_not_open_the_bill_page(device):
    page = device.open("#all")
    bill, number = first_bill(page)
    body = card(page, bill).locator(".bill-filed")
    # A programmatic click leaves the selection in place, like releasing a drag-selection inside the card.
    body.evaluate("e=>{const r=document.createRange();r.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(r);e.click()}")
    page.wait_for_timeout(200)
    expect(page.locator("#bill-page")).to_be_hidden()
    expect(page.locator("#bill-preview")).to_be_hidden()
    # Once nothing is selected the same click opens it.
    page.evaluate("getSelection().removeAllRanges()")
    body.evaluate("e=>e.click()")
    expect_card_opened(page, bill, number)


def test_modified_click_on_a_card_does_not_open_the_bill_page(device):
    page = device.open("#all")
    bill, number = first_bill(page)
    card(page, bill).locator(".bill-filed").click(modifiers=["Control"])
    page.wait_for_timeout(200)
    expect(page.locator("#bill-page")).to_be_hidden()
    card(page, bill).locator(".bill-filed").click(modifiers=["Shift"])
    page.wait_for_timeout(200)
    expect(page.locator("#bill-page")).to_be_hidden()
    expect(page.locator("#bill-preview")).to_be_hidden()


# ---- nav ----

def open_more(page):
    """On a phone the pages outside the bottom bar are behind More."""
    more = page.locator("#nav-more")
    if more.is_visible():
        more.click()


def test_view_nav_button_switches_view(device):
    page = device.open("#all")
    open_more(page)
    page.locator('[data-view="agencies"]').first.click()
    expect(page.locator("#page-title")).to_contain_text("Follow the agencies.")
    assert page.url.endswith("#agencies")
    expect(page.locator('.sidebar [data-view="agencies"].active')).to_have_count(1)
    page.locator('[data-view="all"]').first.click()
    expect(page.locator("#page-title")).to_contain_text("See what’s moving.")


def test_nav_leaves_the_bill_page(device):
    page = device.open("#bill?id=HB110")
    expect(page.locator("#bill-page")).to_be_visible()
    open_more(page)
    page.locator('[data-view="review"]').first.click()
    expect(page.locator("#page-title")).to_contain_text("Full-text review.")
    expect(page.locator("#bill-page")).to_be_hidden()


# ---- today and member rows ----

def test_row_in_a_list_opens_the_bill_page_from_its_body_and_its_links(device):
    page = device.open("#today")
    row = page.locator('.today-row[data-bill-id="HB1084"]')
    row.locator(".today-action").click()
    expect(page.locator("#bill-page .drawer-number")).to_have_text("90R / HB 1084")
    page.locator("#bill-back").click()
    row.locator(".bill-title-link").click()
    expect(page.locator("#bill-page .drawer-number")).to_have_text("90R / HB 1084")


def member_code(page):
    page.locator("#bill-list a.member-name").first.wait_for()
    return re.search(r"code=([^&]+)", page.locator("#bill-list a.member-name").first.get_attribute("href")).group(1)


def test_follow_button_on_a_member_page_follows_without_navigating(device):
    page = device.open("#all")
    code = member_code(page)
    page.goto(device.site.base + f"#member?code={code}")
    button = page.locator(".member-profile [data-follow]")
    expect(button).to_have_text("+ Follow")
    url = page.url
    button.click()
    expect(page.locator(".member-profile [data-follow]")).to_have_text("✓ Following")
    expect(page.locator(".member-profile [data-follow]")).to_have_attribute("aria-pressed", "true")
    assert page.url == url
    expect(page.locator("#bill-page")).to_be_hidden()
    assert code in "".join(device.storage().values())
    page.locator(".member-profile [data-follow]").click()
    expect(page.locator(".member-profile [data-follow]")).to_have_text("+ Follow")


def test_unfollow_on_the_following_page_does_not_follow_the_neighbouring_links(device):
    page = device.open("#all")
    code = member_code(page)
    page.goto(device.site.base + f"#member?code={code}")
    page.locator(".member-profile [data-follow]").click()
    open_more(page)
    page.locator('[data-view="following"]').first.click()
    chip = page.locator(".followed-member")
    expect(chip).to_have_count(1)
    chip.get_by_role("button", name=re.compile("Unfollow")).click()
    expect(page.locator(".followed-member")).to_have_count(0)
    assert page.url.endswith("#following")
    expect(page.locator("#bill-page")).to_be_hidden()


def test_follow_button_in_a_near_you_member_card_does_not_navigate(device):
    page = device.open("#local")
    page.fill("#near-house-num", "1")
    page.locator("#near-numbers-use").click()
    follow = page.locator(".near-member [data-follow]").first
    expect(follow).to_be_visible()
    follow.click()
    expect(page.locator(".near-member [data-follow]").first).to_have_text("✓ Following")
    assert "local" in page.url and "member" not in page.url
    expect(page.locator("#page-title")).to_contain_text("Near you.")
    expect(page.locator("#bill-page")).to_be_hidden()
    # Rows under it still open the bill page from their body.
    row = page.locator(".today-row").first
    if row.count():
        row.locator(".today-action, .bill-tags").first.click()
        expect(page.locator("#bill-page")).to_be_visible()


# ---- on the bill page ----

def test_watch_button_on_the_bill_page_toggles_and_keeps_the_bill_page_open(device):
    page = device.open("#all")
    bill, _ = first_bill(page)
    page.goto(device.site.base + f"#bill?id={bill}")
    button = page.locator("#bill-page .drawer-actions [data-watch]")
    expect(button).to_have_text("☆ Follow this bill")
    button.click()
    expect(page.locator("#bill-page .drawer-actions [data-watch]")).to_have_text("★ Remove from watchlist")
    expect(page.locator("#bill-page")).to_be_visible()
    assert f"#bill?id={bill}" in page.url
    # The list picked up the change too.
    page.locator("#bill-back").click()
    expect(card(page, bill).locator(".watch-button")).to_have_attribute("aria-pressed", "true")


def test_companion_group_watch_button_on_the_bill_page_keeps_the_bill_page_open(device):
    page = device.open("#all")
    owner = page.locator("#bill-list .companion-tag").first.locator("xpath=ancestor::article").get_attribute("data-bill-id")
    page.goto(device.site.base + f"#bill?id={owner}")
    group = page.locator("#bill-page [data-watch-group]")
    expect(group).to_contain_text("Watch all")
    group.click()
    expect(page.locator("#bill-page [data-watch-group]")).to_contain_text("Watching all")
    expect(page.locator("#bill-page")).to_be_visible()


def test_companion_link_on_the_bill_page_opens_that_bills_page(device):
    page = device.open("#all")
    owner = page.locator("#bill-list .companion-tag").first.locator("xpath=ancestor::article").get_attribute("data-bill-id")
    page.goto(device.site.base + f"#bill?id={owner}")
    link = page.locator("#bill-page .companion-open").first
    other = link.get_attribute("data-open")
    link.click()
    expect(page.locator("#bill-page")).to_be_visible()
    assert f"#bill?id={other}" in page.url
    expect(page.locator("#bill-page .drawer-number")).not_to_have_text(re.compile(rf"/ {owner[:2]} {owner[2:]}$"))


def test_back_to_results_leaves_the_bill_page_and_escape_does_not(device):
    page = device.open("#bill?id=HB110")
    page.keyboard.press("Escape")  # a page, not a dialog: Escape leaves it where it is
    expect(page.locator("#bill-page")).to_be_visible()
    page.locator("#bill-back").click()
    expect(page.locator("#bill-page")).to_have_count(0)
    page.locator("#bill-list .bill-open").first.click()
    expect(page.locator("#bill-page")).to_be_visible()


def test_clicking_inside_the_bill_page_does_not_leave_it(device):
    page = device.open("#bill?id=HB110")
    page.locator("#bill-page-title").click()
    page.locator("#bill-page .drawer-caption").click()
    expect(page.locator("#bill-page")).to_be_visible()


def test_statute_link_on_the_bill_page_navigates(device):
    page = device.open("#bill?id=HB110")
    page.locator("#drawer-statutes a", has_text="62.051").click()
    expect(page.locator(".law-compare-wrap")).to_be_visible()
    assert re.search(r"#statute\?law=LA&sec=62\.051$", page.url)
    expect(page.locator("#bill-page")).to_be_hidden()
