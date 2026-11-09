#!/usr/bin/env python3
"""Record published application packages for repository publication."""
import argparse
import fnmatch
import json
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def refresh(app, tag=None):
    if not re.fullmatch(r'[a-z][a-z0-9-]*', app):
        raise ValueError('Invalid application name')
    if tag and not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError('Expected a stable release tag: vX.Y.Z')
    directory = ROOT / 'apps' / app
    cfg = tomllib.loads((directory / 'release.toml').read_text())
    endpoint = f'tags/{tag}' if tag else 'latest'
    release = json.loads(subprocess.check_output(['gh', 'api', f'repos/{cfg["repository"]}/releases/{endpoint}']))
    tag = release['tag_name']
    if release['draft'] or release['prerelease'] or not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError('Expected a published stable release')
    version = tag[1:]
    lock_path = directory / 'release.lock.json'
    old_lock = json.loads(lock_path.read_text()) if lock_path.exists() else None
    if old_lock and tuple(map(int, version.split('.'))) < tuple(map(int, old_lock['tag'][1:].split('.'))):
        raise ValueError('Refusing a release downgrade')
    patterns = []
    for fmt in ('deb', 'rpm', 'pacman'):
        selectors = tomllib.loads((directory / fmt / 'package.toml').read_text())['assets']
        patterns.extend((selectors[a].format(version=version), fmt, a) for a in cfg['architectures'])
    assets = {}
    for pattern, fmt, arch in patterns:
        matches = [a for a in release['assets'] if fnmatch.fnmatchcase(a['name'], pattern)]
        if len(matches) != 1:
            raise ValueError(f'Expected one release asset matching {pattern}, found {len(matches)}')
        asset = matches[0]
        digest = asset.get('digest') or ''
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError(f'Missing SHA-256 digest for {asset["name"]}')
        assets[asset['name']] = {'url': asset['browser_download_url'], 'sha256': digest[7:],
                                 'format': fmt, 'arch': arch}
    same_release = old_lock and old_lock['tag'] == tag
    if same_release:
        for name, previous in old_lock['assets'].items():
            if name not in assets or any(previous[k] != assets[name][k] for k in ('url', 'sha256')):
                raise ValueError('Published release assets changed; publish a new application release')
    content = json.dumps({'tag': tag, 'assets': assets}, indent=2) + '\n'
    history = directory / 'releases' / f'{tag}.json'
    if history.exists() and json.loads(history.read_text()) != json.loads(content):
        raise ValueError('Recorded release changed; publish a new application release')
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(content)
    lock_path.write_text(content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app')
    parser.add_argument('--tag', help='Published stable tag; defaults to the latest release')
    args = parser.parse_args()
    refresh(args.app, args.tag)
