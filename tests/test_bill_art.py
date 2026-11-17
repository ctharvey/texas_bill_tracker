"""Bill page banner art: live/og/art/<ID>.jpg copies and live/og/art.json, written by the data run."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_feeds as bf


def listing(out):
    return json.loads((out / 'art.json').read_text('utf-8'))


def test_copies_art_and_lists_versions_with_alt(tmp_path):
    art, out, alt = tmp_path / 'og_art', tmp_path / 'og', tmp_path / 'alt.json'
    art.mkdir()
    (art / 'HB5.jpg').write_bytes(b'five')
    (art / 'SB12.jpg').write_bytes(b'twelve')
    alt.write_text(json.dumps({'HB5': '  A   raccoon ', 'SB12': '', '../x': 'bad'}), 'utf-8')
    assert bf.write_bill_art(out, art, alt) == (2, True)
    data = listing(out)
    assert data['format'] == 'texas-bill-art-v1'
    assert data['bills'] == {'HB5': {'v': bf.art_version('HB5', art), 'alt': 'A raccoon'},
                             'SB12': {'v': bf.art_version('SB12', art)}}
    assert (out / 'art' / 'HB5.jpg').read_bytes() == b'five'
    assert bf.write_bill_art(out, art, alt) == (2, False)


def test_skips_bad_names_and_oversized_files(tmp_path):
    art, out = tmp_path / 'og_art', tmp_path / 'og'
    art.mkdir()
    (art / 'HB0.jpg').write_bytes(b'x')
    (art / 'notes.jpg').write_bytes(b'x')
    (art / 'HB7.png').write_bytes(b'x')
    (art / 'HB8.jpg').write_bytes(b'x' * (bf.ART_MAX_BYTES + 1))
    assert bf.write_bill_art(out, art, tmp_path / 'missing.json') == (0, True)
    assert listing(out)['bills'] == {}
    assert not (out / 'art').exists()


def test_replaced_art_is_rewritten_and_removed_art_is_deleted(tmp_path):
    art, out = tmp_path / 'og_art', tmp_path / 'og'
    art.mkdir()
    (art / 'HB5.jpg').write_bytes(b'one')
    (art / 'HB6.jpg').write_bytes(b'six')
    bf.write_bill_art(out, art, tmp_path / 'none.json')
    (art / 'HB5.jpg').write_bytes(b'two')
    (art / 'HB6.jpg').unlink()
    assert bf.write_bill_art(out, art, tmp_path / 'none.json') == (1, True)
    assert (out / 'art' / 'HB5.jpg').read_bytes() == b'two'
    assert not (out / 'art' / 'HB6.jpg').exists()
    assert set(listing(out)['bills']) == {'HB5'}
    assert not [p for p in (out / 'art').iterdir() if p.name.startswith('.')]  # no temporary files left


def test_unreadable_alt_file_means_no_alt(tmp_path):
    bad = tmp_path / 'alt.json'
    bad.write_text('{nope', 'utf-8')
    assert bf.load_art_alt(bad) == {}
    bad.write_text('["HB5"]', 'utf-8')
    assert bf.load_art_alt(bad) == {}


def test_repo_alt_text_names_only_bills_with_art():
    alts = bf.load_art_alt(bf.OG_ART_ALT)
    assert alts, 'scripts/og_art_alt.json should describe the shipped art'
    assert set(alts) <= {p.stem for p in bf.OG_ART_DIR.glob('*.jpg')}
