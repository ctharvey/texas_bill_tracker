"""Versioned asset folders written by the static deployer."""
from pathlib import Path
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


def bundle(changes: dict[str, bytes] | None = None) -> dict[str, bytes]:
    files = {'index.html': INDEX, 'src/app.js': b"import {x} from './prefs.js';", 'src/prefs.js': b'export const x = 1;',
             'src/styles.css': b'body{}', 'data/bills.json': b'{}'}
    return files | (changes or {})


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
