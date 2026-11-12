"""Versioned asset folders written by the static deployer."""
from pathlib import Path
import posixpath
import re
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))  # Linux-only lock; unused by these tests.
import deploy_static as deploy

INDEX = (b'<link rel="stylesheet" href="./src/styles.css">\n'
         b'<script type="module" src="./src/app.js"></script>\n')
# from '...', import '...' (side effect), export ... from '...', and import('...') with a literal path.
IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*)['"](\.{1,2}/[^'"]+)['"]""")


def bundle(changes: dict[str, bytes] | None = None) -> dict[str, bytes]:
    files = {'index.html': INDEX, 'src/app.js': b"import {x} from './prefs.js';", 'src/prefs.js': b'export const x = 1;',
             'src/styles.css': b'body{}', 'data/bills.json': b'{}'}
    return files | (changes or {})


def page_modules(read) -> set[str]:
    """Every file the page loads: its two references, then each relative import, resolved against its own folder."""
    pending, seen = [ref[len('./'):] for ref in deploy.PAGE_REFERENCES], set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if name.endswith('.js'):
            folder = posixpath.dirname(name)
            pending += [posixpath.normpath(posixpath.join(folder, m)) for m in IMPORT.findall(read(name))]
    return seen


def tracked_files() -> list[str]:
    out = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], capture_output=True, check=True).stdout
    return [name for name in out.decode().split('\0') if name]


class ShippedModuleTests(unittest.TestCase):
    def test_every_module_the_page_imports_is_published(self):
        # An import of anything the deployer does not publish 404s and the page never starts.
        published = set(deploy.release_files(tracked_files()))
        for name in page_modules(lambda n: (ROOT / n).read_text(encoding='utf-8')):
            self.assertIn(name, published, f'{name} is loaded by the page but would not be published')

    def test_crawl_follows_nested_folders_and_every_import_form(self):
        files = {'src/app.js': "import {a} from './features/x/view.js';\nimport './core/boot.js';",
                 'src/features/x/view.js': "export {b} from '../../core/state.js';\nconst m = import('./lazy.js');",
                 'src/core/boot.js': '', 'src/core/state.js': '', 'src/features/x/lazy.js': ''}
        self.assertEqual(page_modules(lambda n: files[n]), {'src/styles.css', *files})


class ReleaseFilesTests(unittest.TestCase):
    TRACKED = ['index.html', 'README.md', 'src/app.js', 'src/features/brackets/view.js', 'scripts/x.py', *deploy.DATA_FILES]

    def test_publishes_page_all_of_src_and_data(self):
        files = deploy.release_files(self.TRACKED)
        self.assertEqual(files[0], 'index.html')
        self.assertEqual(set(files), {'index.html', 'src/app.js', 'src/features/brackets/view.js', *deploy.DATA_FILES})
        self.assertNotIn('scripts/x.py', files)

    def test_refuses_a_commit_without_the_page_or_data(self):
        for gone in ('index.html', 'data/geo/house.json', deploy.SNAPSHOT):
            with self.subTest(gone=gone), self.assertRaises(ValueError):
                deploy.release_files([n for n in self.TRACKED if n != gone])

    def test_commit_listing_includes_nested_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            for name in ('index.html', 'src/app.js', 'src/features/brackets/view.js'):
                (work / name).parent.mkdir(parents=True, exist_ok=True)
                (work / name).write_text('x', encoding='utf-8')
            git = ['git', '-C', tmp, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
            subprocess.run(git[:3] + ['init', '-q'], check=True)
            subprocess.run(git + ['add', '.'], check=True)
            subprocess.run(git + ['commit', '-qm', 'x'], check=True)
            saved, deploy.REPOSITORY = deploy.REPOSITORY, work / '.git'
            try:
                listed = deploy.commit_files('HEAD')
            finally:
                deploy.REPOSITORY = saved
        self.assertEqual(sorted(listed), ['index.html', 'src/app.js', 'src/features/brackets/view.js'])

    def test_refuses_an_empty_asset_but_not_the_validated_snapshot(self):
        deploy.require_assets(bundle({deploy.SNAPSHOT: b''}))
        with self.assertRaises(ValueError):
            deploy.require_assets(bundle({'src/features/brackets/view.js': b'  \n'}))


class VersionedAssetTests(unittest.TestCase):
    def test_copies_modules_and_points_the_page_at_them(self):
        digest, files = deploy.versioned_assets(bundle())
        self.assertRegex(digest, r'^[0-9a-f]{16}$')
        self.assertEqual(files[f'assets/{digest}/app.js'], b"import {x} from './prefs.js';")
        self.assertEqual(files[f'assets/{digest}/prefs.js'], b'export const x = 1;')
        self.assertEqual(files[f'assets/{digest}/styles.css'], b'body{}')
        self.assertNotIn(f'assets/{digest}/bills.json', files)
        page = files['index.html']
        self.assertIn(f'href="./assets/{digest}/styles.css"'.encode(), page)
        self.assertIn(f'src="./assets/{digest}/app.js"'.encode(), page)
        self.assertNotIn(b'./src/', page)

    def test_nested_modules_keep_their_folders(self):
        digest, files = deploy.versioned_assets(bundle({'src/features/brackets/view.js': b'export const v = 1;'}))
        self.assertEqual(files[f'assets/{digest}/features/brackets/view.js'], b'export const v = 1;')

    def test_any_module_change_changes_the_folder(self):
        first, _ = deploy.versioned_assets(bundle())
        second, _ = deploy.versioned_assets(bundle({'src/prefs.js': b'export const x = 2;'}))
        self.assertNotEqual(first, second)
        self.assertEqual(first, deploy.versioned_assets(bundle())[0])

    def test_refuses_a_page_without_exactly_one_reference(self):
        for page in (b'<script type="module" src="./src/app.js"></script>', INDEX + INDEX):
            with self.subTest(page=page[:40]), self.assertRaises(ValueError):
                deploy.versioned_assets(bundle({'index.html': page}))


class CarryPreviousAssetsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.current, self.staging = self.root / 'current', self.root / 'staging'
        old, files = deploy.versioned_assets(bundle())
        for name, content in files.items():
            (self.current / name).parent.mkdir(parents=True, exist_ok=True)
            (self.current / name).write_bytes(content)
        self.old = old
        self.staging.mkdir()

    def test_keeps_the_previous_release_folder(self):
        deploy.carry_previous_assets(self.current, self.staging, 'f' * 16)
        self.assertEqual((self.staging / 'assets' / self.old / 'app.js').read_bytes(), b"import {x} from './prefs.js';")

    def test_skips_the_same_folder_and_a_first_release(self):
        deploy.carry_previous_assets(self.current, self.staging, self.old)
        deploy.carry_previous_assets(self.root / 'missing', self.staging, 'f' * 16)
        self.assertFalse((self.staging / 'assets').exists())


if __name__ == '__main__':
    unittest.main()
