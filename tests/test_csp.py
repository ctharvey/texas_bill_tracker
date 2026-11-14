"""The page's Content-Security-Policy must keep allowing what the site really loads, and nothing broader."""
import base64
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'index.html').read_text(encoding='utf-8')


def policy() -> dict:
    content = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', INDEX).group(1)
    return {part.split()[0]: part.split()[1:] for part in (p.strip() for p in content.split(';')) if part}


class ContentSecurityPolicy(unittest.TestCase):
    def test_policy_comes_before_any_script_or_stylesheet(self):
        at = INDEX.index('http-equiv="Content-Security-Policy"')
        self.assertLess(at, INDEX.index('<script'))
        self.assertLess(at, INDEX.index('rel="stylesheet"'))

    def test_every_inline_script_is_allowed_by_its_hash(self):
        scripts = re.findall(r'<script>(.*?)</script>', INDEX, re.S)
        self.assertTrue(scripts)
        allowed = policy()['script-src']
        for body in scripts:
            digest = "'sha256-" + base64.b64encode(hashlib.sha256(body.encode('utf-8')).digest()).decode() + "'"
            self.assertIn(digest, allowed, 'inline script changed: update its hash in the CSP')
        self.assertNotIn("'unsafe-inline'", allowed)
        self.assertNotIn("'unsafe-eval'", allowed)

    def test_external_hosts_the_site_loads_are_allowed(self):
        rules = policy()
        geo = (ROOT / 'src/geo.js').read_text(encoding='utf-8')
        census = re.search(r'https://[a-z.]+census\.gov', geo).group(0)
        self.assertIn(census, rules['script-src'])  # address lookup loads the geocoder as JSONP
        for host in re.findall(r'<link href="(https://[^/"]+)/[^"]*" rel="stylesheet"', INDEX):
            self.assertIn(host, rules['style-src'])
        self.assertIn('https://fonts.gstatic.com', rules['font-src'])
        self.assertEqual(rules['object-src'], ["'none'"])
        self.assertEqual(rules['connect-src'], ["'self'"])


if __name__ == '__main__':
    unittest.main()
