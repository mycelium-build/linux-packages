import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('distribution', Path(__file__).resolve().parents[1] / 'scripts/distribution.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shutil.copytree(d.ROOT / 'apps', root / 'apps')
        self.enterContext(patch.object(d, 'ROOT', root))
        self.directory = root / 'apps/datalith'
        self.lock = json.loads((self.directory / 'release.lock.json').read_text())

    def refresh(self, tag, changed=None):
        old_version, version = self.lock['tag'][1:], tag[1:]
        release = {'tag_name': tag, 'draft': False, 'prerelease': False, 'assets': [
            {'name': name.replace(old_version, version),
             'browser_download_url': asset['url'].replace(old_version, version),
             'digest': 'sha256:' + ('a' * 64 if changed == asset['format'] else asset['sha256'])}
            for name, asset in self.lock['assets'].items()]}
        with patch.object(d.subprocess, 'check_output', return_value=json.dumps(release)):
            d.refresh('datalith', tag)

    def test_refresh_is_repeatable_and_preserves_previous_release(self):
        old = self.directory / 'releases' / f'{self.lock["tag"]}.json'
        original = old.read_bytes()
        self.refresh(self.lock['tag'])
        self.assertEqual(json.loads(old.read_text()), self.lock)
        self.refresh('v99.0.0')
        self.assertEqual(old.read_bytes(), original)
        current = json.loads((self.directory / 'release.lock.json').read_text())
        self.assertEqual(current['tag'], 'v99.0.0')
        self.assertEqual(current, json.loads((self.directory / 'releases/v99.0.0.json').read_text()))
        self.assertTrue(all('/v99.0.0/' in a['url'] for a in current['assets'].values()))

    def test_replaced_release_is_rejected_without_changes(self):
        before = {p: p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}
        for fmt in ('pacman', 'deb', 'rpm'):
            with self.subTest(format=fmt):
                with self.assertRaisesRegex(ValueError, 'publish a new application release'):
                    self.refresh(self.lock['tag'], changed=fmt)
                self.assertEqual({p: p.read_bytes() for p in before}, before)
