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


class PreviewTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shutil.copytree(d.ROOT / 'apps', root / 'apps')
        self.enterContext(patch.object(d, 'ROOT', root))
        self.directory = root / 'apps/datalith-preview'
        self.lock = json.loads((self.directory / 'release.lock.json').read_text())
        self.stable = root / 'apps/datalith/release.lock.json'

    def release(self, tag):
        old = self.lock['tag'][1:]
        version = tag[1:]
        assets = []
        for name, asset in self.lock['assets'].items():
            separator = '' if asset['format'] == 'pacman' else '.'
            assets.append({
                'name': name.replace(old.replace('-', separator), version.replace('-', separator)),
                'browser_download_url': asset['url'].replace(old, version),
                'digest': 'sha256:' + asset['sha256'],
            })
        return {'tag_name': tag, 'draft': False, 'prerelease': True, 'assets': assets}

    def refresh(self, release, app='datalith-preview', revision=1):
        with patch.object(d.subprocess, 'check_output', return_value=json.dumps(release)):
            d.refresh(app, release['tag_name'], revision)

    def revised(self, release, number):
        """Add pacman packages at a higher package release, as an upstream repack does."""
        extra = [{**a, 'name': a['name'].replace('-1-', f'-{number}-'),
                  'browser_download_url': a['browser_download_url'].replace('-1-', f'-{number}-'),
                  'digest': 'sha256:' + str(number) * 64}
                 for a in release['assets'] if a['name'].endswith('-1-x86_64.pkg.tar.zst')
                 or a['name'].endswith('-1-aarch64.pkg.tar.zst')]
        return {**release, 'assets': release['assets'] + extra}

    def test_packaging_revision_keeps_the_original_record(self):
        releases = self.directory / 'releases'
        original = (releases / 'v1.1.0-rc.2.json').read_bytes()
        release = self.revised(self.release(self.lock['tag']), 2)
        self.refresh(release)
        self.assertEqual((self.directory / 'release.lock.json').read_bytes(), original)
        self.refresh(release, revision=2)
        self.refresh(release, revision=2)
        lock = json.loads((self.directory / 'release.lock.json').read_text())
        self.assertEqual(lock, json.loads((releases / 'v1.1.0-rc.2+r2.json').read_text()))
        self.assertEqual((releases / 'v1.1.0-rc.2.json').read_bytes(), original)
        self.assertEqual(lock['revision'], 2)
        self.assertEqual(sorted(n for n in lock['assets'] if n.endswith('.pkg.tar.zst')),
                         ['datalith-preview-1.1.0rc.2-2-aarch64.pkg.tar.zst',
                          'datalith-preview-1.1.0rc.2-2-x86_64.pkg.tar.zst'])
        self.assertEqual({n: a for n, a in lock['assets'].items() if a['format'] != 'pacman'},
                         {n: a for n, a in self.lock['assets'].items() if a['format'] != 'pacman'})
        self.refresh(self.release('v1.1.0-rc.3'))
        self.assertNotIn('revision', json.loads((self.directory / 'release.lock.json').read_text()))

    def test_packaging_revisions_cannot_go_back_or_drop_published_packages(self):
        release = self.revised(self.release(self.lock['tag']), 2)
        with self.assertRaisesRegex(ValueError, 'no package at revision 3'):
            self.refresh(release, revision=3)
        self.refresh(release, revision=2)
        before = {p: p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            self.refresh(release, revision=1)
        dropped = {**release, 'assets': [a for a in release['assets'] if '-1-x86_64' not in a['name']]}
        with self.assertRaisesRegex(ValueError, 'Published release assets changed'):
            self.refresh(self.revised(dropped, 3), revision=3)
        self.assertEqual({p: p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}, before)

    def test_preview_formats_and_independent_history(self):
        stable = self.stable.read_bytes()
        self.refresh(self.release('v99.0.0-rc.10'))
        lock = json.loads((self.directory / 'release.lock.json').read_text())
        self.assertEqual(lock['tag'], 'v99.0.0-rc.10')
        self.assertEqual(len(lock['assets']), 6)
        self.assertIn('datalith-preview_99.0.0.rc.10-1_amd64.deb', lock['assets'])
        self.assertIn('datalith-preview-99.0.0.rc.10-1.x86_64.rpm', lock['assets'])
        self.assertIn('datalith-preview-99.0.0rc.10-1-x86_64.pkg.tar.zst', lock['assets'])
        self.assertEqual(self.stable.read_bytes(), stable)
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            self.refresh(self.release('v99.0.0-rc.2'))

    def test_channels_drafts_and_mismatched_flags_are_rejected(self):
        before = (self.directory / 'release.lock.json').read_bytes()
        rc = self.release('v99.0.0-rc.1')
        for release, app in [(rc, 'datalith'),
                             ({**rc, 'draft': True}, 'datalith-preview'),
                             ({**rc, 'prerelease': False}, 'datalith-preview'),
                             ({**rc, 'tag_name': 'v99.0.0', 'prerelease': False}, 'datalith-preview')]:
            with self.subTest(release=release['tag_name'], app=app):
                with self.assertRaises(ValueError):
                    self.refresh(release, app)
        self.assertEqual((self.directory / 'release.lock.json').read_bytes(), before)

    def test_latest_preview_uses_all_pages_and_numeric_rc_order(self):
        rc2 = self.release('v99.0.0-rc.2')
        rc10 = self.release('v99.0.0-rc.10')
        stable = {**rc10, 'tag_name': 'v100.0.0', 'prerelease': False}
        draft = {**rc10, 'tag_name': 'v101.0.0-rc.1', 'draft': True}
        with patch.object(d.subprocess, 'check_output', return_value=json.dumps([[stable, rc2], [draft, rc10]])):
            d.refresh('datalith-preview')
        self.assertEqual(json.loads((self.directory / 'release.lock.json').read_text())['tag'], 'v99.0.0-rc.10')

    def test_preview_assets_cannot_be_replaced(self):
        release = self.release(self.lock['tag'])
        release['assets'][0]['digest'] = 'sha256:' + '0' * 64
        with self.assertRaisesRegex(ValueError, 'Published release assets changed'):
            self.refresh(release)

    def test_retention_keeps_every_revision_of_the_retained_releases(self):
        releases = self.directory / 'releases'
        for name in ('v1.0.0-rc.1', 'v1.0.0-rc.9+r2', 'v1.1.0-rc.2+r2', 'v1.1.0-rc.2+r10', 'v1.0.0-rc.9'):
            (releases / f'{name}.json').write_text('{}')
        kept = [p.stem for p in d.retained_records(self.directory.parent, 2) if p.parent == releases]
        self.assertEqual(kept, ['v1.0.0-rc.9', 'v1.0.0-rc.9+r2', 'v1.1.0-rc.2', 'v1.1.0-rc.2+r2',
                                'v1.1.0-rc.2+r10'])
        for name in ('v1.1.0-rc.2+r1', 'v1.1.0-rc.2+r', 'v1.1.0-rc.2+r02'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                d.record_key(name)

    def test_retention_order_handles_preview_and_stable_tags(self):
        tags = ['v1.2.0-rc.10', 'v1.2.0', 'v1.2.0-rc.2', 'v1.1.9', 'v1.3.0-rc.0']
        self.assertEqual(sorted(tags, key=d.release_version),
                         ['v1.1.9', 'v1.2.0-rc.2', 'v1.2.0-rc.10', 'v1.2.0', 'v1.3.0-rc.0'])
