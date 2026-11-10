#!/usr/bin/env python3
"""Record published application packages for repository publication."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def release_version(tag):
    """Order stable releases and numbered release candidates numerically."""
    match = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)(?:-rc\.(0|[1-9][0-9]*))?', tag)
    if not match:
        raise ValueError('Expected vX.Y.Z or vX.Y.Z-rc.N')
    major, minor, patch, rc = match.groups()
    return (int(major), int(minor), int(patch), rc is None, int(rc or 0))


def record_key(stem):
    """Order release records: vX.Y.Z[-rc.N] for revision 1, then vX.Y.Z[-rc.N]+rR."""
    tag, separator, revision = stem.partition('+r')
    if separator and (revision == '1' or not re.fullmatch(r'[1-9][0-9]*', revision)):
        raise ValueError(f'Invalid release record: {stem}')
    return (*release_version(tag), int(revision or 1))


def record_name(tag, revision):
    return tag if revision == 1 else f'{tag}+r{revision}'


def retained_records(apps, keep):
    """Records of the latest `keep` releases of each application, with every packaging revision."""
    records = []
    for releases in sorted(apps.glob('*/releases')):
        by_release = {}
        for path in sorted(releases.glob('v*.json'), key=lambda p: record_key(p.stem)):
            by_release.setdefault(record_key(path.stem)[:-1], []).append(path)
        for paths in list(by_release.values())[-keep:]:
            records.extend(paths)
    return records


def package_release(name, selector):
    """Package release (deb/rpm release, pacman pkgrel) that the selector's * matches."""
    prefix, wildcard, suffix = selector.partition('*')
    if not wildcard or '*' in suffix:
        raise ValueError(f'Selector needs one * for the package release: {selector}')
    if len(name) > len(prefix) + len(suffix) and name.startswith(prefix) and name.endswith(suffix):
        release = name[len(prefix):len(name) - len(suffix)]
        if re.fullmatch(r'[1-9][0-9]*', release):
            return int(release)
    return None


def matches_channel(release, channel):
    if release['draft']:
        return False
    try:
        version = release_version(release['tag_name'])
    except ValueError:
        return False
    preview = not version[3]
    return preview == (channel == 'preview') and release['prerelease'] == preview


def refresh(app, tag=None, revision=1):
    if not re.fullmatch(r'[a-z][a-z0-9-]*', app):
        raise ValueError('Invalid application name')
    directory = ROOT / 'apps' / app
    cfg = tomllib.loads((directory / 'release.toml').read_text())
    channel = cfg.get('channel', 'stable')
    if channel not in ('stable', 'preview'):
        raise ValueError('Unknown release channel')
    if tag:
        release_version(tag)
    if not isinstance(revision, int) or revision < 1:
        raise ValueError('Packaging revision must be a positive integer')
    if revision > 1 and not tag:
        raise ValueError('A packaging revision needs its release tag')
    if not tag and channel == 'preview':
        pages = json.loads(subprocess.check_output([
            'gh', 'api', '--paginate', '--slurp', f'repos/{cfg["repository"]}/releases?per_page=100']))
        candidates = [r for page in pages for r in page if matches_channel(r, channel)]
        if not candidates:
            raise ValueError('No published preview release found')
        release = max(candidates, key=lambda r: release_version(r['tag_name']))
    else:
        endpoint = f'tags/{tag}' if tag else 'latest'
        release = json.loads(subprocess.check_output(['gh', 'api', f'repos/{cfg["repository"]}/releases/{endpoint}']))
    if not matches_channel(release, channel):
        raise ValueError(f'Expected a published {channel} release')
    tag = release['tag_name']
    version = tag[1:]
    lock_path = directory / 'release.lock.json'
    old_lock = json.loads(lock_path.read_text()) if lock_path.exists() else None
    if old_lock and (*release_version(tag), revision) < (*release_version(old_lock['tag']), old_lock.get('revision', 1)):
        raise ValueError('Refusing a release downgrade')
    patterns = []
    for fmt in ('deb', 'rpm', 'pacman'):
        selectors = tomllib.loads((directory / fmt / 'package.toml').read_text())['assets']
        patterns.extend((selectors[a].format(version=version.replace('-', '' if fmt == 'pacman' else '.')), fmt, a) for a in cfg['architectures'])
    assets, selected = {}, []
    for pattern, fmt, arch in patterns:
        # Packaging revisions add assets with a higher package release; select the latest
        # one up to the requested revision.
        matches = {}
        for candidate in release['assets']:
            number = package_release(candidate['name'], pattern)
            if number is not None and number <= revision:
                matches[number] = candidate
        if not matches:
            raise ValueError(f'Expected a release asset matching {pattern} up to revision {revision}')
        selected.append(max(matches))
        asset = matches[selected[-1]]
        digest = asset.get('digest') or ''
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError(f'Missing SHA-256 digest for {asset["name"]}')
        assets[asset['name']] = {'url': asset['browser_download_url'], 'sha256': digest[7:],
                                 'format': fmt, 'arch': arch}
    if max(selected) != revision:
        raise ValueError(f'Release has no package at revision {revision}')
    # Every recorded revision stays published, unchanged, for clients with cached metadata.
    published = {a['name']: a for a in release['assets']}
    records = [json.loads(p.read_text()) for p in (directory / 'releases').glob('v*.json')
               if record_key(p.stem)[:-1] == release_version(tag)]
    if old_lock and old_lock['tag'] == tag:
        records.append(old_lock)
    for name, previous in ((n, a) for r in records for n, a in r['assets'].items()):
        current = published.get(name)
        if not current or current['browser_download_url'] != previous['url'] \
                or current.get('digest') != 'sha256:' + previous['sha256']:
            raise ValueError('Published release assets changed; publish a new application release')
    record = {'tag': tag, 'assets': assets} if revision == 1 else {'tag': tag, 'revision': revision, 'assets': assets}
    content = json.dumps(record, indent=2) + '\n'
    history = directory / 'releases' / f'{record_name(tag, revision)}.json'
    if history.exists() and json.loads(history.read_text()) != json.loads(content):
        raise ValueError('Recorded release changed; publish a new application release')
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(content)
    lock_path.write_text(content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app')
    parser.add_argument('--tag', help='Published tag; defaults to the latest release in the application channel')
    parser.add_argument('--revision', type=int, default=1,
                        help='Packaging revision: latest package release to select, recorded separately')
    args = parser.parse_args()
    refresh(args.app, args.tag, args.revision)
