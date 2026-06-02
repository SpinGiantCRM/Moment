# Releasing a New Version

This guide covers the complete procedure for cutting a Moment release — from bumping the version through publishing to PyPI and the AUR.

---

## Prerequisites

- Push access to `SpinGiantCRM/moment`
- A PyPI API token stored as `PYPI_TOKEN` in the repo's **Actions secrets** (Settings → Secrets and variables → Actions)
- The `PYPI_TOKEN` must have upload permissions for the `moment-clips` project

---

## Step-by-Step Release Procedure

### 1. Ensure CI is green on `master`

Before cutting a release, the `master` branch must pass all CI checks:

```bash
# Check CI status
git checkout master
git pull origin master
# Visit https://github.com/SpinGiantCRM/moment/actions
```

If CI is failing, fix the failures first. **Never release from a broken `master`.**

### 2. Bump the version

Use the `make release` target. It handles version bumping in both `pyproject.toml` and `src/moment/__init__.py`, commits, tags, and pushes:

```bash
make release VERSION=0.4.0
```

**What this does:**
- Replaces `version = "…"` in `pyproject.toml`
- Replaces `__version__ = "…"` in `src/moment/__init__.py`
- Commits both changes with message `"Release v0.4.0 [skip ci]"`
- Creates an annotated tag `v0.4.0`
- Pushes the commit and tag to `origin/master`

**Important:** The tag push triggers the release workflow. The `[skip ci]` in the commit message prevents CI from running on the version-bump commit (the release workflow handles testing).

### 3. Wait for the release workflow

The tag push triggers `.github/workflows/release.yml`. Monitor it at:

```
https://github.com/SpinGiantCRM/moment/actions
```

**The release pipeline runs these steps in order:**

| Step | Job | Description |
|------|-----|-------------|
| 1 | `preflight` | Runs full test suite, builds wheel + sdist, runs `twine check` |
| 2 | `publish` | Uploads wheel + sdist to PyPI via API token |
| 3 | `aur-update` | Computes new source tarball checksum and updates `PKGBUILD` |
| 4 | `release` | Creates a GitHub Release with changelog and attached artifacts |

**If preflight fails:** The publish, AUR update, and GitHub Release steps are all blocked. Fix the issue, delete the tag (`git tag -d v0.4.0 && git push origin :refs/tags/v0.4.0`), fix the code, and re-tag.

### 4. Verify the PyPI publish

After the `publish` job succeeds:

```bash
# Verify the version is live
pip install --dry-run moment-clips==0.4.0

# Or check the PyPI page
# https://pypi.org/project/moment-clips/
```

### 5. Verify the GitHub Release

Check that:
- The release appears at `https://github.com/SpinGiantCRM/moment/releases`
- The changelog is populated
- The `.whl` and `.tar.gz` artifacts are attached
- Installation instructions in the release body are correct

### 6. Verify the AUR checksums

The `aur-update` job automatically commits an updated `PKGBUILD` to `master`. Verify:

```bash
git pull origin master
cat PKGBUILD
# Confirm pkgver and sha256sums match the new release
```

---

## What the Release Workflow Tests

The preflight runs **all tests** that don't require external services:

```bash
python -m pytest -m "not slow and not external" --tb=short -q
```

This includes:
- Unit tests (unmarked)
- GUI tests (`@pytest.mark.gui`, run with `xvfb-run`)
- Integration tests (`@pytest.mark.integration`)

It excludes:
- **Slow tests** (`@pytest.mark.slow`) — these take too long
- **External tests** (`@pytest.mark.external`) — these need real network/GSR/rclone

If you need to add slow or external tests and want them to run in the release pipeline, update the preflight filter in `release.yml`.

---

## Troubleshooting Release Failures

### Preflight fails: "sqlcipher3 is required"

The CI runner needs `libsqlcipher-dev` installed. Check that `release.yml`'s system dependency step includes it:

```yaml
sudo apt-get install -y -qq libsqlcipher-dev ...
```

### Preflight fails: GUI tests crash

GUI tests run under `xvfb-run` (virtual framebuffer). Make sure:
- `xvfb` is in the system deps list in `release.yml`
- `QT_QPA_PLATFORM=offscreen` is set
- Tests that create widgets use the `qapp` or `qtbot` fixture and have `pytestmark = [pytest.mark.gui]`

### Publish fails: "403 Forbidden"

The PyPI API token is invalid or expired. Generate a new one at `https://pypi.org/manage/account/token/` and update the `PYPI_TOKEN` secret in the repo.

### Publish fails: "File already exists"

You're trying to re-publish a version that already exists on PyPI. PyPI versions are immutable. Bump to a new version number.

### Wheel is missing files (icons, etc.)

If you add new non-Python assets (SVGs, PNGs, data files, etc.) and they don't appear in the wheel, here's how to fix it.

**Verify what's in the wheel:**

```bash
python -m build --wheel
unzip -l dist/*.whl | grep -E '(svg|png|moment/ui/assets)'
```

**If files are missing, check both:**

1. **`[tool.setuptools.package-data]`** in `pyproject.toml` — controls what goes in the **wheel**
2. **`MANIFEST.in`** — controls what goes in the **sdist**

Add your new file patterns to both, rebuild, and verify again.

---

## Manual Release (Fallback)

If GitHub Actions is unavailable, you can release manually:

```bash
# 1. Bump version + tag
make release VERSION=0.4.0

# 2. Build
make dist

# 3. Upload to PyPI
pip install twine
twine upload dist/*

# 4. Create GitHub Release manually at:
#    https://github.com/SpinGiantCRM/moment/releases/new
#    Attach dist/*.whl and dist/*.tar.gz
```

---

## Version Numbering Convention

Moment uses `MAJOR.MINOR.PATCH`:

| Bump | When |
|------|------|
| **PATCH** (0.3.5 → 0.3.6) | Bug fixes, CI fixes, dependency bumps |
| **MINOR** (0.3.6 → 0.4.0) | New features, new pages/dialogs, new CLI subcommands |
| **MAJOR** (0.4.0 → 1.0.0) | Breaking changes (DB schema, config format, CLI API) |
