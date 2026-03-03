# Release Process for lager-cli

This document is for **maintainers** who publish releases of the `lager-cli` package to PyPI.

If you are looking to contribute code, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Prerequisites

- Python 3.10+
- [`build`](https://pypa-build.readthedocs.io/) (`pip install build`)
- [`twine`](https://twine.readthedocs.io/) (`pip install twine`)
- A [PyPI API token](https://pypi.org/help/#apitoken) with upload access to the `lager-cli` project
- Push access to the `main` branch on GitHub

## Pre-release Checklist

Before starting a release, verify:

- [ ] All staging changes are merged and CI is green
- [ ] Tests pass against target hardware boxes
- [ ] `CHANGELOG.md` has entries for all user-facing changes
- [ ] No open security issues that should block the release

## Release Steps

Throughout this guide, replace `X.Y.Z` with the actual version number (e.g., `0.3.29`).

### 1. Update Version Number

Edit the version in `cli/__init__.py`:

```python
__version__ = 'X.Y.Z'
```

### 2. Update CHANGELOG.md

Add a new section at the top of `CHANGELOG.md` following the [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New features

### Changed
- Changes to existing functionality

### Fixed
- Bug fixes

### Removed
- Removed features
```

To see what changed since the last release, review the commit history:

```bash
git log origin/main..HEAD --oneline --no-decorate
```

### 3. Create Release Notes File

Create `docs/source/release-notes/vX.Y.Z.mdx`:

```markdown
---
title: "Version X.Y.Z"
description: "Month DD, YYYY"
---

## <u>Features</u>

- Feature description

## <u>Bug Fixes</u>

- Bug fix description

## <u>Improvements</u>

- Improvement description

## <u>Installation</u>

To install this version:

\`\`\`bash
pip install lager-cli==X.Y.Z
\`\`\`

To upgrade from a previous version:

\`\`\`bash
pip install --upgrade lager-cli
\`\`\`

## Resources

[View Release on PyPI](https://pypi.org/project/lager-cli/X.Y.Z/)
```

**Categorization guidelines:**
- **Features**: New functionality, new commands, new device support
- **Bug Fixes**: Fixes for issues, crashes, incorrect behavior
- **Improvements**: Performance, code cleanup, minor enhancements

**Terminology:** Use "Lager Box" (not "gateway"), "Lager Boxes" (not "gateways").

### 4. Update Navigation

Add the new version to the top of the Release Notes list in `docs/docs.json`:

```json
{
  "tab": "Release Notes",
  "groups": [
    {
      "group": "Version History",
      "pages": [
        "source/release-notes/vX.Y.Z",
        "source/release-notes/v0.3.28",
        ...
      ]
    }
  ]
}
```

### 5. Commit and Push to Staging

```bash
git add cli/__init__.py CHANGELOG.md docs/source/release-notes/vX.Y.Z.mdx docs/docs.json
git commit -m "vX.Y.Z"
git push origin staging
```

### 6. Merge to Main

```bash
git checkout main
git merge staging
git push origin main
```

### 7. Tag the Release

Create an annotated tag on main:

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
```

### 8. Build Distribution Packages

Clean old artifacts and build:

```bash
cd cli
rm -rf dist/ build/ *.egg-info
python -m build
```

This creates `.tar.gz` and `.whl` files in `cli/dist/`.

### 9. Upload to PyPI

```bash
twine upload dist/*
```

When prompted, use `__token__` as the username and your PyPI API token as the password.

### 10. Create GitHub Release

Go to [Releases](https://github.com/lagerdata/lager/releases) and create a new release:

- **Tag**: Select the `vX.Y.Z` tag
- **Title**: `vX.Y.Z`
- **Description**: Copy the relevant section from `CHANGELOG.md`

Alternatively, use the GitHub CLI:

```bash
gh release create vX.Y.Z --title "vX.Y.Z" --notes-file - <<EOF
Copy CHANGELOG.md section here
EOF
```

## Post-release

1. Verify the release is live:
   ```bash
   pip install lager-cli==X.Y.Z
   lager --version
   ```
2. Switch back to the staging branch for continued development:
   ```bash
   git checkout staging
   git merge main
   git push origin staging
   ```

## Versioning Policy

This project follows [Semantic Versioning](https://semver.org/):

- **MAJOR** (`X`): Breaking changes to CLI commands or Python API
- **MINOR** (`Y`): New features, new device/instrument support
- **PATCH** (`Z`): Bug fixes, documentation, minor improvements

> **Note:** Releases before v0.3.25 used version branches (e.g., `v0.2.18`) instead of tags. These branches are preserved as historical markers and should not be modified.

## Troubleshooting

**`python -m build` fails:** Make sure `build` is installed (`pip install build`) and you are in the `cli/` directory.

**`twine upload` fails:** Verify your PyPI API token is valid and the version does not already exist on PyPI. Check that the package name is `lager-cli`.

**Import errors during build:** Ensure all dependencies listed in `cli/setup.py` are available in your environment.

**Tag already exists:** If you need to re-tag (e.g., after a fix), delete the old tag first: `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`. Only do this if the release has not been published to PyPI.
