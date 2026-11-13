"""'Copy for AI' on the bill page and 'Copy page for AI' in the top bar: what lands on the clipboard."""

from playwright.sync_api import expect

DRAWER = "#bill-page"  # the bill page
AGENT = "https://agent.bills.ctharvey.me/"


def grant(device):
    device.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=device.site.base.rstrip("/"))


def clipboard(page):
    # Chrome on Windows hands back CRLF line ends; the text itself is what matters.
    return page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")


def test_copy_for_ai_in_the_drawer_copies_a_prompt_for_the_bill(device):
    grant(device)
    page = device.open("#bill?id=HB147")
    button = page.locator(f"{DRAWER} [data-copy-ai]")
    expect(button).to_have_text("Copy for AI")
    button.click()
    expect(button).to_have_text("Copied")
    lines = clipboard(page).split("\n")
    assert lines == [
        "Texas HB 147 (90th Legislature): Relating to a community health clinic grant program.",
        "",
        f"AI-readable version with history and review: {AGENT}bills/HB147.md",
        "Official bill history and text: https://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&Bill=HB147",
        "",
        "Summarize what this bill does, who it affects, and its current status, citing the bill text.",
    ]


def test_copy_for_ai_includes_each_companion(device):
    grant(device)
    page = device.open("#bill?id=HB110")
    page.locator(f"{DRAWER} [data-copy-ai]").click()
    expect(page.locator(f"{DRAWER} [data-copy-ai]")).to_have_text("Copied")
    text = clipboard(page)
    assert f"Companion bill HB 972 (duplicate): {AGENT}bills/HB972.md" in text.split("\n")
    assert f"AI-readable version with history and review: {AGENT}bills/HB110.md" in text.split("\n")


def test_copied_label_goes_back_to_copy_for_ai(device):
    grant(device)
    page = device.open("#bill?id=HB110")
    button = page.locator(f"{DRAWER} [data-copy-ai]")
    button.click()
    expect(button).to_have_text("Copied")
    expect(button).to_have_text("Copy for AI", timeout=5000)


def test_page_button_with_a_bill_open_copies_that_bills_prompt(device):
    grant(device)
    page = device.open("#bill?id=HB110")
    page.focus("#copy-page-ai")
    page.keyboard.press("Enter")
    expect(page.locator("#copy-page-ai")).to_have_text("Copied")
    first = clipboard(page).split("\n")[0]
    assert first == "Texas HB 110 (90th Legislature): Relating to the minimum wage."


def test_page_button_copies_the_filtered_list(device):
    grant(device)
    page = device.open("#all")
    page.fill("#bill-search", "minimum wage")
    expect(page.locator("#result-count")).not_to_have_text("—")
    shown = page.locator("#result-count").inner_text().split()[0].replace(",", "")
    page.locator("#copy-page-ai").click()
    expect(page.locator("#copy-page-ai")).to_have_text("Copied")
    lines = clipboard(page).split("\n")
    assert lines[0] == 'Texas Bill Atlas (90th Legislature): Bill explorer (search "minimum wage")'
    assert lines[1].startswith("Page: ") and "query=minimum" in lines[1]
    assert lines[2] == f"{shown} {'bill' if shown == '1' else 'bills'} shown."
    assert f"Same list, AI-readable: {AGENT}search?q=minimum+wage" in lines
    assert f"Everything available: {AGENT}llms.txt" in lines
    bullets = [l for l in lines if l.startswith("- ")]
    assert any(l.startswith("- HB 110: Relating to the minimum wage.") and l.endswith(f"{AGENT}bills/HB110.md")
               and "Companion: HB 972 (duplicate)" in l for l in bullets)
    assert len(bullets) == min(int(shown), 50)  # long lists are capped at 50 entries
    assert lines[-1] == "Use these links to answer my questions about these bills; open a bill's page for its full details."


def test_page_button_describes_topic_and_chamber_filters(device):
    grant(device)
    page = device.open("#all")
    page.select_option("#filter-chamber", "Senate")
    page.select_option("#filter-topic", index=1)
    topic = page.locator("#filter-topic option:checked").inner_text()
    page.locator("#copy-page-ai").click()
    expect(page.locator("#copy-page-ai")).to_have_text("Copied")
    lines = clipboard(page).split("\n")
    assert lines[0] == f"Texas Bill Atlas (90th Legislature): Bill explorer (topic {topic}, chamber Senate)"
    search = next(l for l in lines if l.startswith("Same list, AI-readable: "))
    assert "chamber=Senate" in search and "topic=" in search


def test_page_button_on_an_info_page_points_at_its_agent_page(device):
    grant(device)
    page = device.open("#saving")
    page.locator("#copy-page-ai").click()
    expect(page.locator("#copy-page-ai")).to_have_text("Copied")
    lines = clipboard(page).split("\n")
    assert lines[0] == "Texas Bill Atlas (90th Legislature): Saving your info"
    assert lines[1].endswith("#saving")
    assert f"AI-readable version: {AGENT}saving.md" in lines


def test_when_the_clipboard_is_blocked_the_bill_page_shows_the_text_to_copy_by_hand(device):
    # No clipboard permission, and the legacy copy command refused: the prompt appears selected in a text box.
    page = device.open("#bill?id=HB147")
    page.evaluate("""() => {
        navigator.clipboard.writeText = () => Promise.reject(new Error('blocked'));
        document.execCommand = () => false;
    }""")
    page.locator(f"{DRAWER} [data-copy-ai]").click()
    box = page.locator("#ai-fallback")
    expect(box).to_be_visible()
    expect(box).to_have_value(
        f"Texas HB 147 (90th Legislature): Relating to a community health clinic grant program.\n\n"
        f"AI-readable version with history and review: {AGENT}bills/HB147.md\n"
        "Official bill history and text: https://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&Bill=HB147\n\n"
        "Summarize what this bill does, who it affects, and its current status, citing the bill text.")
    expect(page.locator("#toast")).to_have_text("Press Ctrl+C to copy")


def test_when_the_clipboard_is_blocked_the_page_button_says_so(device):
    page = device.open("#all")
    page.evaluate("""() => {
        navigator.clipboard.writeText = () => Promise.reject(new Error('blocked'));
        document.execCommand = () => false;
    }""")
    page.locator("#copy-page-ai").click()
    expect(page.locator("#toast")).to_have_text("Copy failed; your browser blocked the clipboard")
