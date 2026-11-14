"""Every explorer filter the client can save must be accepted by the sync server, or that device's sync stops."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import sync_service as svc


def client_filters() -> dict:
    source = (ROOT / 'src/prefs.js').read_text(encoding='utf-8')
    body = re.search(r'export const FILTER_DEFAULTS = \{([^}]*)\}', source).group(1)
    return {name: (value.strip() == 'false') for name, value in re.findall(r'(\w+):\s*([^,]+)', body)}


class SyncFilterContract(unittest.TestCase):
    def test_server_accepts_every_client_filter(self):
        filters = client_filters()
        self.assertIn('party', filters)
        payload = {name: (True if is_bool else 'x') for name, is_bool in filters.items()}
        self.assertEqual(svc.clean_filters(payload), payload)

    def test_unknown_filter_is_still_rejected(self):
        with self.assertRaises(svc.Rejected):
            svc.clean_filters({'nonsense': 'x'})


if __name__ == '__main__':
    unittest.main()
