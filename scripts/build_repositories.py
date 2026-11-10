#!/usr/bin/env python3
"""Assemble signed pacman/APT/RPM repositories from published application packages."""
import argparse
import gzip
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import tomllib
import urllib.request

from distribution import release_version

ROOT = Path(__file__).resolve().parents[1]
DEB_ARCH = {'x86_64': 'amd64', 'aarch64': 'arm64'}


def download(asset, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(asset['url'], headers={'User-Agent': 'mycelium-linux-packages'})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response, destination.open('wb') as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != asset['sha256']:
        destination.unlink()
        raise ValueError(f'Release checksum mismatch: {asset["url"]}')


def build(output):
    if output.exists():
        raise ValueError(f'Use an empty output path: {output}')
    output.mkdir(parents=True)
    cfg = tomllib.loads((ROOT / 'repositories/config.toml').read_text())
    key = cfg['signing_fingerprint']
    url = cfg['url'].rstrip('/')
    shutil.copyfile(ROOT / 'repositories/signing-key.asc', output / 'signing-key.asc')
    key_listing = subprocess.check_output(['gpg', '--with-colons', '--list-keys', key], text=True)
    key_created = next(line.split(':')[5] for line in key_listing.splitlines() if line.startswith('pub:'))
    downloaded = {}
    # Keep the previous release for clients with cached repository metadata.
    snapshots = []
    for releases in sorted((ROOT / 'apps').glob('*/releases')):
        versions = sorted(releases.glob('v*.json'), key=lambda p: release_version(p.stem))
        snapshots.extend(versions[-cfg['retain_releases']:])
    for snapshot in snapshots:
        app = snapshot.parent.parent.name
        for name, asset in json.loads(snapshot.read_text())['assets'].items():
            if asset['format'] == 'deb':
                target = output / 'apt/pool' / DEB_ARCH[asset['arch']] / app / name
            elif asset['format'] == 'rpm':
                target = output / 'rpm' / asset['arch'] / 'Packages' / app / name
            elif asset['format'] == 'pacman':
                target = output / 'pacman' / asset['arch'] / name
            else:
                continue
            if Path(name).name != name:
                raise ValueError(f'Invalid package filename: {name}')
            if target in downloaded:
                if downloaded[target] != asset['sha256']:
                    raise ValueError(f'Conflicting release payload: {name}')
                continue
            download(asset, target)
            downloaded[target] = asset['sha256']
            if asset['format'] == 'rpm':
                # Stable signing time keeps RPM bytes unchanged when a publication is retried.
                subprocess.run(['rpmsign', '--define', f'_gpg_name {key}',
                                '--define', '__gpg /usr/bin/gpg',
                                '--define', f'_gpg_sign_cmd_extra_args --faked-system-time {key_created}!', '--addsign', str(target)], check=True)
            elif asset['format'] == 'pacman':
                subprocess.run(['gpg', '--batch', '--yes', '--local-user', key, '--detach-sign', str(target)], check=True)
    if not downloaded:
        raise ValueError('No native release packages to publish')
    apt = output / 'apt'
    release_dir = apt / 'dists/stable'
    for arch in sorted(DEB_ARCH.values()):
        pool = apt / 'pool' / arch
        pool.mkdir(parents=True, exist_ok=True)
        index = release_dir / f'main/binary-{arch}/Packages'
        index.parent.mkdir(parents=True, exist_ok=True)
        with index.open('wb') as stream:
            subprocess.run(['apt-ftparchive', 'packages', f'pool/{arch}'], cwd=apt, stdout=stream, check=True)
        (index.parent / 'Packages.gz').write_bytes(gzip.compress(index.read_bytes(), mtime=0))
    release = subprocess.check_output(['apt-ftparchive', '-o', 'APT::FTPArchive::Release::Origin=mycelium-build',
                        '-o', 'APT::FTPArchive::Release::Label=mycelium-build',
                        '-o', 'APT::FTPArchive::Release::Suite=stable',
                        '-o', 'APT::FTPArchive::Release::Codename=stable',
                        '-o', 'APT::FTPArchive::Release::Architectures=amd64 arm64',
                        '-o', 'APT::FTPArchive::Release::Components=main',
                        'release', 'dists/stable'], cwd=apt)
    (release_dir / 'Release').write_bytes(release)
    gpg = ['gpg', '--batch', '--yes', '--local-user', key, '--armor']
    subprocess.run([*gpg, '--clearsign', '--output', str(release_dir / 'InRelease'),
                    str(release_dir / 'Release')], check=True)
    subprocess.run([*gpg, '--detach-sign', '--output', str(release_dir / 'Release.gpg'),
                    str(release_dir / 'Release')], check=True)
    for arch in DEB_ARCH:
        repo = output / 'rpm' / arch
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(['createrepo_c', str(repo)], check=True)
        subprocess.run([*gpg, '--detach-sign', str(repo / 'repodata/repomd.xml')], check=True)
    current = {arch: [] for arch in DEB_ARCH}
    for lock in (ROOT / 'apps').glob('*/release.lock.json'):
        for name, asset in json.loads(lock.read_text())['assets'].items():
            if asset['format'] == 'pacman':
                current[asset['arch']].append(name)
    for arch, packages in current.items():
        repo = output / 'pacman' / arch
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(['repo-add', '--sign', '--key', key, 'mycelium-build.db.tar.gz', *packages],
                       cwd=repo, check=True)
        # Pages artifacts cannot contain symlinks; pacman needs the .db and .files aliases.
        for alias in repo.iterdir():
            if alias.is_symlink():
                contents = alias.read_bytes()
                alias.unlink()
                alias.write_bytes(contents)
    for template, target in [('apt/mycelium-build.sources.in', 'mycelium-build.sources'),
                             ('rpm/mycelium-build.repo.in', 'mycelium-build.repo'),
                             ('pacman/mycelium-build.conf.in', 'mycelium-build.conf')]:
        content = (ROOT / 'repositories' / template).read_text().replace('@URL@', url)
        (output / target).write_text(content)
    (output / '.nojekyll').touch()
    shutil.copytree(ROOT / 'repositories/web/assets', output / 'assets')
    page = (ROOT / 'repositories/web/index.html.in').read_text()
    page = page.replace('@URL@', html.escape(url, quote=True))
    page = page.replace('@FINGERPRINT@', html.escape(key, quote=True))
    (output / 'index.html').write_text(page)
    size = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
    if size >= 950_000_000:
        raise ValueError('Repository approaches the GitHub Pages 1 GB limit; move hosting before publishing')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'site')
    build(parser.parse_args().output.resolve())
