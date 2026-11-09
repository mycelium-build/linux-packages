# Contributing

## Layout and local changes

- `apps/<app>/`: upstream repository, package filename selectors, current release
  lock and release history.
- `repositories/`: hosting URL, retention, public signing key and client configuration.
- `scripts/distribution.py`: records published packages without downloading them.
- `scripts/build_repositories.py`: downloads packages and publishes repository metadata.

Use Python 3.11+ and an authenticated GitHub CLI:

```sh
python3 scripts/distribution.py datalith --tag v1.1.1
python3 -B -m unittest discover -s tests -v
```

Commit the current lock and new history record together. Published assets must
remain unchanged; packaging fixes and version changes belong in the application
repository. Repository configuration fixes can be deployed by rerunning publication
with the same tag, without rebuilding the application.

To assemble repositories locally, install `apt-ftparchive`, `createrepo_c`,
`rpmsign`, `repo-add` and GnuPG, and use a `GNUPGHOME` containing the signing key:

```sh
python3 scripts/build_repositories.py --output /tmp/mycelium-repositories
```

The output path must not exist. No application build or package tests are run.

## Pull requests

- Reuse upstream packages and versions; do not rebuild them here.
- Keep credentials in Actions secrets and private keys outside Git.
- Keep documentation focused on installation and maintenance.
- Add regression tests only for meaningful failures in distribution logic.
- Use Conventional Commit subjects with a concise changes list in the body.
- Explain the behavior changed and checks performed in the PR.

## Repository maintenance

Use a Conventional Commit PR title and a concise changes list in the body.
Completed PR branches are deleted automatically.

Keep GitHub Actions pinned to full commit SHAs with version comments. Check the
actions' upstream releases when maintaining workflows. Renovate is not configured:
application versions and checksums are updated by the release notification workflow.

Publication workflows commit verified generated records directly to main using
GITHUB_TOKEN. Main rejects deletion and force pushes; requiring pull requests for
these updates first requires adapting the publication authentication and workflow.
