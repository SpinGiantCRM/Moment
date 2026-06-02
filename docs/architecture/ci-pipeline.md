# CI/CD Pipeline Reference

Moment uses GitHub Actions for continuous integration and release automation. Two workflows are defined — `ci.yml` (runs on PRs and pushes to `master`) and `release.yml` (triggered by version tags).

---

## CI Workflow (`.github/workflows/ci.yml`)

**Trigger:** Push to `master`, Pull Request to `master`

**Purpose:** Catch regressions before they land.

### Jobs

#### 1. `lint` — Ruff Linter

- Runs `ruff check` + `ruff format --check`
- Must pass before any other job runs (other jobs `needs: lint`)
- Python 3.13 only (linting is Python-version agnostic)

#### 2. `fast` — Unit Tests

- **Matrix:** Python 3.11, 3.12, 3.13
- **Marker filter:** `-m "not gui and not integration and not slow and not external"`
- **Runs:** unmarked tests only (pure unit tests)
- **Coverage:** Only collected on Python 3.13
- **System deps:** `libsqlcipher-dev libegl1 libgl1 libpulse0 libxkbcommon0 libfontconfig1`
- **Env:** `QT_QPA_PLATFORM=offscreen`

#### 3. `gui` — Qt Widget Tests

- **Matrix:** Python 3.11, 3.12, 3.13
- **Marker filter:** `-m gui`
- **Runs:** Tests marked `pytest.mark.gui` (widget creation, QApplication, qtbot)
- **Uses `xvfb-run`** for a virtual display
- **Additional system dep:** `xvfb`

#### 4. `integration` — Filesystem/DB/Thread Tests

- **Matrix:** Python 3.11, 3.12, 3.13
- **Marker filter:** `-m "integration and not external"`
- **Runs:** Tests marked `pytest.mark.integration` (real filesystem, SQLite DBs, threads)
- Creates `~/Videos` directory (needed by some integration tests)

#### 5. `smoketest` — End-to-End Install Test

- Builds the wheel from source
- Installs it via `pipx` (simulating the recommended user install method)
- Runs `--version`, `--help`, and `mcp --help`
- **Catches:** missing entry points, broken imports, packaging errors

#### 6. `security` — Bandit + pip-audit

- Runs `bandit` static analysis on `src/`
- Runs `pip-audit` to check for known vulnerabilities in dependencies

### System Dependencies

| Package | Purpose |
|---------|---------|
| `libsqlcipher-dev` | SQLite encryption library (mandatory for DB operations) |
| `libegl1` | EGL support for Qt (offscreen rendering) |
| `libgl1` | OpenGL support for Qt |
| `libpulse0` | PulseAudio support (audio capture) |
| `libxkbcommon0` | Keyboard handling in Qt |
| `libfontconfig1` | Font rendering in Qt |
| `xvfb` | Virtual framebuffer (GUI tests only) |

---

## Release Workflow (`.github/workflows/release.yml`)

**Trigger:** Push of a `v*` tag (e.g., `v0.3.6`) or manual `workflow_dispatch`

**Purpose:** Validate, build, and publish a new release.

### Jobs

#### 1. `preflight` — Test + Build + Twine Check

- Installs `.[all]` dependencies + `pytest build twine`
- Runs **all non-slow, non-external** tests (including GUI with `xvfb-run`)
- Builds wheel + sdist with `python -m build`
- Runs `twine check` to validate package metadata
- Verifies wheel contents (lists files inside)
- **Uploads `dist/` as a build artifact** (retained 7 days)

#### 2. `publish` — PyPI Upload

- **Gate:** Only runs on tag push (not `workflow_dispatch`)
- Downloads the `dist` artifact from preflight
- Uploads to PyPI via `twine upload` using `PYPI_TOKEN` secret

#### 3. `aur-update` — PKGBUILD Checksum

- **Gate:** Only runs on tag push
- Downloads the GitHub source tarball and computes its SHA-256
- Updates `pkgver` and `sha256sums` in `PKGBUILD`
- Commits and pushes the update to `master`

#### 4. `release` — GitHub Release

- **Gate:** Only runs on tag push
- Downloads `dist` artifacts from preflight
- Generates a changelog from `git log` between tag ranges
- Creates a GitHub Release with installation instructions and attached `.whl` + `.tar.gz`

### Permissions Required

```yaml
permissions:
  contents: write  # Needed for: creating GitHub Release, pushing PKGBUILD commits
```

### Secrets Required

| Secret | Used By | Purpose |
|--------|---------|---------|
| `PYPI_TOKEN` | `publish` job | Upload packages to PyPI |

---

## Adding a New CI Job

1. Add the job to `ci.yml` under `jobs:`
2. Each job `needs: lint` (gate on lint passing)
3. Install system dependencies in a `run:` step (use `sudo apt-get install -y -qq <pkg>`)
4. Use `matrix.python-version` if testing across Python versions
5. Set `QT_QPA_PLATFORM=offscreen` for any job that may import PyQt6
6. Set `timeout-minutes:` to prevent hung jobs from blocking the pipeline

---

## Test Marker Strategy

The CI pipeline partitions tests by pytest markers. See [Testing Conventions](../guides/testing.md) for how and when to use each marker.

### Marker ↔ Job Mapping

| Marker | Job | Description |
|--------|-----|-------------|
| *(none)* | `fast` | Pure unit tests — fast, no filesystem, no Qt |
| `gui` | `gui` | Tests that create QWidgets or need `qapp`/`qtbot` |
| `integration` | `integration` | Tests that touch real filesystem, SQLite DBs, or threads |
| `slow` | *(excluded everywhere)* | Tests that take >5 seconds |
| `external` | *(excluded everywhere)* | Tests that need network, GSR, rclone, or OS services |

---

## Common CI Failure Modes

### "sqlcipher3 is required"

Missing `libsqlcipher-dev` in system dependencies. Add it to the system deps step.

### "Could not find Qt platform plugin 'offscreen'"

Missing `libegl1` and `libgl1`. These provide the EGL/OpenGL backends Qt needs for offscreen rendering.

### "xvfb-run: command not found"

The `xvfb` package is not installed. Add it to the system deps step for any job that runs GUI tests.

### GUI tests hang indefinitely

GUI tests must run under `xvfb-run` with `QT_QPA_PLATFORM=offscreen`. Without this, QApplication will try to open a real display and hang in CI.

### Integration tests fail with "No such file or directory: ~/Videos"

Some integration tests expect `~/Videos` to exist. Add `mkdir -p ~/Videos` before running integration tests.

### Bandit failures

Bandit scans are configured in `[tool.bandit]` in `pyproject.toml`. To skip a false positive, add the check code to the `skips` list:

```toml
[tool.bandit]
skips = ["B101", "B108", ...]
```
