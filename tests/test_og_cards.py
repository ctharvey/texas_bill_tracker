"""Per-bill share cards: chip labels, card model/version, cards.json, rendered.json and share page images."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_feeds as bf

BILL = {'id': 'HB5', 'caption': 'Relating to   water\n rights.', 'chamber': 'House', 'status': 'Filed',
        'filed_at': '2026-11-09', 'authors': ['Smith', 'Jones', 'Lee'], 'last_action_date': '2027-02-10',
        'subjects': ['Family--Juvenile Delinquency', 'Water--General', 'Taxes--Sales', 'Roads--Tolls']}


def meta(html, name):
    return re.search(rf'<meta (?:property|name)="{re.escape(name)}" content="([^"]*)">', html).group(1)


def test_subject_labels_use_the_specific_tail():
    assert bf.subject_labels(['Family--Juvenile Delinquency']) == ['Juvenile Delinquency']


def test_subject_labels_generic_tails_use_the_head():
    assert bf.subject_labels(['City Government--General']) == ['City Government']
    assert bf.subject_labels(['Education--Primary & Secondary--Other School Personnel']) == ['Education']


def test_subject_labels_repeated_tails_use_heads():
    got = bf.subject_labels(['City Government--Employees/Officers', 'County Government--Employees/Officers'])
    assert got == ['City Government', 'County Government']


def test_subject_labels_title_case_dedupe_and_skip_junk():
    assert bf.subject_labels(['LIEUTENANT GOVERNOR']) == ['Lieutenant Governor']
    assert bf.subject_labels(['Taxes--General', 'Taxes--General', None, 5, '   ', 'Roads--Tolls']) == ['Taxes', 'Tolls']


def test_card_model_fields():
    m = bf.card_model(BILL)
    assert m['number'] == 'HB 5'
    assert m['byline'] == 'Filed Nov 9, 2026 · By Smith and 2 others'
    assert m['caption'] == 'Relating to water rights.'
    assert len(m['subjects']) == 3
    assert '90th Legislature' in m['session']
    assert m['chamber'] == 'House' and m['status'] == 'Filed'


def test_card_model_author_string_and_single_author():
    piped = bf.card_model({'id': 'SB2', 'filed_at': '2026-11-09', 'author': 'Smith | Jones | Lee'})
    assert piped['byline'] == 'Filed Nov 9, 2026 · By Smith'  # lead author only; no author list to count
    one = bf.card_model({'id': 'SB2', 'filed_at': '2026-11-09', 'authors': ['Smith']})
    assert one['byline'] == 'Filed Nov 9, 2026 · By Smith'
    assert 'other' not in one['byline']
    two = bf.card_model({'id': 'SB2', 'authors': ['Smith', 'Jones']})
    assert two['byline'] == 'By Smith and 1 other'


def test_card_model_missing_filed_at_drops_filed_part():
    m = bf.card_model({'id': 'SB2', 'authors': ['Smith']})
    assert m['byline'] == 'By Smith'
    assert 'Filed' not in m['byline']


def test_card_version_is_stable_and_tracks_changes():
    m = bf.card_model(BILL)
    v = bf.card_version(m)
    assert v == bf.card_version(dict(m))
    assert re.fullmatch(r'[0-9a-f]{12}', v)
    assert bf.card_version({**m, 'status': 'Passed'}) != v


def test_write_og_cards(tmp_path):
    out = tmp_path / 'og'
    snap = {'bills': [BILL, {'id': '../evil', 'caption': 'x'}, {'id': 'HB0'}, {'id': 'SB9', 'caption': 'c'}]}
    assert bf.write_og_cards(snap, out) == (2, True)
    data = json.loads((out / 'cards.json').read_text('utf-8'))
    assert data['format'] == 'texas-bill-og-cards-v1'
    assert set(data['bills']) == {'HB5', 'SB9'}
    assert data['bills']['HB5']['v'] == bf.card_version(bf.card_model(BILL))
    assert data['bills']['HB5']['active'] == '2027-02-10'
    assert data['bills']['SB9']['active'] == ''
    assert bf.write_og_cards(snap, out) == (2, False)


def test_write_og_cards_empty_snapshot_leaves_existing_file(tmp_path):
    out = tmp_path / 'og'
    out.mkdir()
    (out / 'cards.json').write_text('keep me', 'utf-8')
    assert bf.write_og_cards({'bills': []}, out) == (0, False)
    assert bf.write_og_cards({'bills': [{'id': 'bad'}]}, out) == (0, False)
    assert (out / 'cards.json').read_text('utf-8') == 'keep me'


def test_load_rendered(tmp_path):
    p = tmp_path / 'rendered.json'
    p.write_text(json.dumps({'format': 'texas-bill-og-rendered-v1', 'bills': {
        'HB5': 'abc123', '../x': 'abc123', 'HB0': 'abc123', 'SB1': 'NOTHEX', 'SB2': 7}}), 'utf-8')
    assert bf.load_rendered(p) == {'HB5': 'abc123'}


def test_load_rendered_unreadable_gives_empty(tmp_path):
    wrong = tmp_path / 'wrong.json'
    wrong.write_text(json.dumps({'format': 'other', 'bills': {'HB5': 'abc123'}}), 'utf-8')
    bad = tmp_path / 'bad.json'
    bad.write_text('{not json', 'utf-8')
    assert bf.load_rendered(wrong) == {}
    assert bf.load_rendered(tmp_path / 'missing.json') == {}
    assert bf.load_rendered(bad) == {}


def test_share_page_without_image_uses_site_card():
    html = bf.share_page(BILL)
    assert meta(html, 'og:image') == 'https://billatlas.org/social-card.png'
    assert meta(html, 'og:image:alt') == 'Texas Bill Atlas'


def test_share_page_with_image_version_uses_bill_card():
    html = bf.share_page(BILL, image_v='abc123')
    want = 'https://billatlas.org/live/og/HB5.png?v=abc123'
    assert meta(html, 'og:image') == want
    assert meta(html, 'twitter:image') == want
    assert meta(html, 'og:image:alt').startswith('HB 5: ')


def test_share_page_gives_x_the_same_image_alt_as_open_graph():
    with_card = bf.share_page(BILL, image_v='abc123')
    assert meta(with_card, 'twitter:image:alt') == meta(with_card, 'og:image:alt')
    assert meta(with_card, 'twitter:image:alt').startswith('HB 5: Relating to water rights.')
    assert meta(bf.share_page(BILL), 'twitter:image:alt') == 'Texas Bill Atlas'


def test_write_share_pages_uses_rendered_versions(tmp_path):
    snap = {'bills': [BILL, {'id': 'SB9', 'caption': 'Other'}]}
    bf.write_share_pages(snap, tmp_path, rendered={'HB5': 'abc123'})
    hb5 = (tmp_path / 'HB5.html').read_text('utf-8')
    sb9 = (tmp_path / 'SB9.html').read_text('utf-8')
    assert meta(hb5, 'og:image') == 'https://billatlas.org/live/og/HB5.png?v=abc123'
    assert meta(sb9, 'og:image') == 'https://billatlas.org/social-card.png'

def test_art_version_hashes_the_file_and_ignores_missing_or_bad_ids(tmp_path):
    (tmp_path / 'HB486.jpg').write_bytes(b'one')
    v = bf.art_version('HB486', tmp_path)
    assert re.fullmatch(r'[0-9a-f]{12}', v)
    (tmp_path / 'HB486.jpg').write_bytes(b'two')
    assert bf.art_version('HB486', tmp_path) != v
    assert bf.art_version('HB487', tmp_path) is None
    assert bf.art_version('../HB486', tmp_path) is None


def test_card_model_adds_art_only_when_the_bill_has_a_file(tmp_path):
    plain = bf.card_model(BILL, tmp_path)
    assert 'art' not in plain
    assert bf.card_version(plain) == bf.card_version(bf.card_model(BILL, tmp_path / 'missing'))
    (tmp_path / 'HB5.jpg').write_bytes(b'art')
    with_art = bf.card_model(BILL, tmp_path)
    assert with_art['art'] == bf.art_version('HB5', tmp_path)
    assert bf.card_version(with_art) != bf.card_version(plain)


def test_repo_art_files_are_named_for_bills_and_small():
    for path in bf.OG_ART_DIR.glob('*'):
        assert path.suffix == '.jpg' and bf.BILL_ID.fullmatch(path.stem), path.name
        assert path.stat().st_size <= 2_000_000, path.name  # build_og.mjs refuses larger files


def test_share_page_og_url_carries_the_card_version_and_canonical_stays_plain():
    page = bf.share_page({'id': 'HB486', 'caption': 'c'}, image_v='52c122380bfa')
    assert meta(page, 'og:url') == 'https://billatlas.org/bill/HB486?c=52c122380bfa'
    assert '<link rel="canonical" href="https://billatlas.org/bill/HB486">' in page
    plain = bf.share_page({'id': 'HB486', 'caption': 'c'})
    assert meta(plain, 'og:url') == 'https://billatlas.org/bill/HB486'
