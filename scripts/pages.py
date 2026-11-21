"""Build a static page from the deployed shell so a crawler or a slow phone sees it before the app boots."""

import hashlib
import html
import re
from pathlib import Path


SHELL_PATH = Path('/var/www/html/texas-bill-atlas/current/shell.html')
MARKERS = ('head', 'heading', 'content')
VIEW = re.compile(r'bill:[A-Z]{2,3}[1-9][0-9]{0,4}|(?:law|chapter):[A-Za-z0-9 .]+|member:A[0-9]{3,5}'
                  r'|agency:[a-z0-9][a-z0-9-]{0,40}|topic:[a-z0-9][a-z0-9-]{0,79}|about:(?:method|saving|data)'
                  r'|page:(?:home|today|laws)|code:[A-Z]{2}')
SCRIPT = re.compile(r'<script\b[^>]*>', re.IGNORECASE)
LD_JSON = '<script type="application/ld+json">'
# The app writes every view's heading into these two elements, so a page without a heading keeps them, empty.
EMPTY_HEADING = '<h1 id="page-title"></h1><p id="page-subtitle"></p>'


def markers(shell: str) -> bool:
    """Whether every slot has exactly one opening and one closing marker; a doubled marker is a broken shell."""
    return all(shell.count(f'<!--{name}-->') == 1 and shell.count(f'<!--/{name}-->') == 1 for name in MARKERS)


def load_shell(path: Path = SHELL_PATH) -> str | None:
    """The shell text, or None when it is missing, unreadable or no longer carries the slot markers."""
    try:
        shell = path.read_text(encoding='utf-8')
    except OSError:
        return None
    return shell if markers(shell) else None


def shell_version(shell: str) -> str:
    return hashlib.sha256(shell.encode()).hexdigest()[:12]


def _fill(shell: str, name: str, value: str) -> str:
    start, end = f'<!--{name}-->', f'<!--/{name}-->'
    at = shell.index(start) + len(start)
    return shell[:at] + value + shell[shell.index(end, at):]


def _clean_scripts(value: str) -> None:
    """Only JSON-LD is allowed: the page's own scripts carry a CSP hash and must stay in the shell itself."""
    for match in SCRIPT.finditer(value):
        tag = match.group(0).lower()
        if tag != LD_JSON:
            raise ValueError('a slot may not contain an inline script except application/ld+json')


def slot_text(shell: str, name: str) -> str:
    """What the shell itself has in a slot (the home page's own head tags, for one)."""
    start, end = f'<!--{name}-->', f'<!--/{name}-->'
    at = shell.index(start) + len(start)
    return shell[at:shell.index(end, at)]


def render_page(shell: str, *, head: str, content: str, view: str, heading: str | None = None) -> str:
    """Fill the shell's slots and tag the content section so the app can tell which static page it is on."""
    if not markers(shell):
        raise ValueError('shell markers are missing or doubled')
    if not VIEW.fullmatch(view):
        raise ValueError('bad static view: ' + view)
    for value in (head, heading or '', content):
        _clean_scripts(value)
    slot = f'{head}<meta name="shell-version" content="{shell_version(shell)}">'
    page = _fill(shell, 'head', slot)
    page = _fill(page, 'heading', EMPTY_HEADING if heading is None else heading)
    page = _fill(page, 'content', content)
    page = page.replace('<div class="page-heading"', '<div class="page-heading" hidden', 1) if heading is None else page
    return page.replace('<section id="dynamic-content"', f'<section id="dynamic-content" data-static-view="{html.escape(view, quote=True)}"', 1)
