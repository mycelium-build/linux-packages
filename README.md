# Mycelium Build Linux packages

Signed pacman, APT and RPM repositories for Mycelium Build applications.
Packages and versions come directly from application releases. Nothing is rebuilt
here. DEB and pacman archives stay unchanged; RPM packages receive a repository
signature.

## Installation

These URLs become available after the first successful publication from `main`.
Packages are available for x86_64 and aarch64. Runtime requirements are those of
the upstream application packages.

### Arch / CachyOS

```sh
curl -fsSLo /tmp/mycelium-build.asc https://packages.datalith.work/signing-key.asc
sudo pacman-key --add /tmp/mycelium-build.asc
sudo pacman-key --lsign-key 2926639D6FF19E8459C4F134C9C65D9D1B69CD63
```

Add this repository at the end of `/etc/pacman.conf`:

```ini
[mycelium-build]
SigLevel = Required DatabaseRequired
Server = https://packages.datalith.work/pacman/$arch
```

Then install with `sudo pacman -Syu datalith`.

### APT

```sh
sudo curl -fsSLo /usr/share/keyrings/mycelium-build.asc https://packages.datalith.work/signing-key.asc
sudo curl -fsSLo /etc/apt/sources.list.d/mycelium-build.sources https://packages.datalith.work/mycelium-build.sources
sudo apt update
sudo apt install datalith
```

### DNF

```sh
sudo curl -fsSLo /etc/yum.repos.d/mycelium-build.repo https://packages.datalith.work/mycelium-build.repo
sudo dnf install datalith
```

Install `datalith-preview` instead of `datalith` to opt into release candidates.
Both packages use the same repositories and have independent release histories;
installing the stable package never opts you into preview updates.

The signing key fingerprint is `2926639D6FF19E8459C4F134C9C65D9D1B69CD63`.

## Publication

After a stable release, Datalith notifies **Publish Linux packages**. GitHub Actions
records the release URLs and checksums, downloads the existing packages, signs the
repositories and deploys them together to GitHub Pages. It does not run package
tests. The two latest releases per application remain available.

To retry, open **Actions → Publish Linux packages → Run workflow** on `main`.
Select the application (`datalith` or `datalith-preview`) and tag (`vX.Y.Z` or `vX.Y.Z-rc.N`), or leave the tag empty for the latest
stable release. Set **revision** only for a packaging revision published
upstream (for example `2` for repackaged `...-2-<arch>.pkg.tar.zst` packages). Enable **publish** to deploy; leave it off to inspect release
record changes in the logs.

See [CONTRIBUTING.md](CONTRIBUTING.md) for maintenance and contribution rules.
