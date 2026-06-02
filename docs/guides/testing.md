# Testing Conventions

This guide covers how to write and organize tests for Moment, including the pytest marker system that the CI pipeline depends on.

---

## Test File Structure

All tests live in the `tests/` directory at the project root. Each source module has a corresponding test file:

```
src/moment/core/store.py    → tests/test_store.py
src/moment/ui/widgets/toast.py → tests/test_toast.py
```

Test files must be named `test_*.py`. This is enforced by pytest configuration in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

---

## Test Markers

Moment uses pytest markers to partition tests into categories. The CI pipeline runs each category in a separate job with appropriate setup (e.g., `xvfb` for GUI tests).

### Available Markers

| Marker | Set via | Meaning | CI Job |
|--------|---------|---------|--------|
| *(none)* | Default | Pure unit test — fast, no filesystem, no Qt | `fast` |
| `gui` | `pytestmark = [pytest.mark.gui]` | Creates QWidgets, uses `qapp` or `qtbot` fixtures | `gui` |
| `integration` | `pytestmark = [pytest.mark.integration]` | Real filesystem, SQLite DBs, threads, ffmpeg | `integration` |
| `slow` | `@pytest.mark.slow` on individual tests | Takes >5 seconds | *(excluded everywhere)* |
| `external` | `@pytest.mark.external` on individual tests | Needs real network, GSR, rclone, or OS services | *(excluded everywhere)* |

### How to Set a Marker

**Module-level (recommended):** Use `pytestmark` when every test in the file needs the same marker.

```python
# tests/test_my_widget.py
"""Tests for my_widget.py."""

import pytest

pytestmark = [pytest.mark.gui]   # All tests in this file use qapp/qtbot


class TestMyWidget:
    def test_create(self, qapp) -> None:
        ...

    def test_signals(self, qtbot) -> None:
        ...
```

**Function-level:** Use decorators when only specific tests need a marker.

```python
class TestPipeline:
    def test_fast_encode(self) -> None:
        ...  # Unmarked — runs in fast job

    @pytest.mark.slow
    def test_full_reencode_cycle(self, store) -> None:
        ...  # Only runs when explicitly selecting -m slow

    @pytest.mark.external
    def test_upload_to_r2(self) -> None:
        ...  # Requires real cloud storage — never runs in CI
```

### Choosing the Right Marker

#### Use `gui` when:
- Your test creates a `QWidget`, `QDialog`, `QMainWindow`, or any PyQt6 widget
- Your test function accepts `qapp` or `qtbot` as a fixture parameter
- Your test calls methods that require a running `QApplication`

#### Use `integration` when:
- Your test creates real files on disk (via `tmp_path` or `db_path` fixtures)
- Your test uses the `store` fixture (real SQLite database)
- Your test spawns threads, subprocesses, or uses `ffmpeg`
- Your test touches the filesystem in any way

#### Use `slow` when:
- A single test takes more than ~5 seconds
- It's a performance benchmark
- It does a full encode/upload cycle

Use `@pytest.mark.slow` at the function level (not module-level) so the fast path for other tests in the same file still works.

#### Use `external` when:
- The test needs a real network connection
- The test needs `gpu-screen-recorder` running
- The test needs `rclone` configured with a real remote
- The test needs system services (D-Bus, PulseAudio, etc.)

External tests never run in CI. They're intended for local development only.

#### Leave unmarked when:
- Your test is a pure unit test with no side effects
- No Qt, no filesystem, no threads, no network
- Mocks are used for all external dependencies

### Module-Level `pytestmark` for Common Patterns

Several test modules use both `store` (integration) and `qapp` (gui) fixtures. In this case, you can mark with both:

```python
pytestmark = [pytest.mark.gui, pytest.mark.integration]
```

This causes the tests to be excluded from the `fast` job and included in both `gui` and `integration` jobs. The `gui` job runs them with `xvfb`, and `integration` runs them with `QT_QPA_PLATFORM=offscreen`.

However, **prefer picking one marker** where possible. Mixed-marker files make CI behavior harder to reason about.

---

## Fixtures

All shared fixtures are defined in `tests/conftest.py`. Key fixtures:

### `qapp` (session-scoped)
```python
@pytest.fixture(scope="session")
def qapp() -> QApplication:
```

Returns a `QApplication` instance configured for offscreen rendering. Session-scoped so it's created once per test run. Every test that interacts with Qt widgets should accept `qapp` as a parameter.

> **⚠️ Session-scoped caveat:** One test mutating global Qt state (stylesheet, palette,
> font) can leak into later tests in the same run. Prefer `qtbot` for widget-interaction
> tests when possible, since `qtbot` cleans up widgets between tests.

### `qtbot` (function-scoped)
Provided by `pytest-qt`. Use for testing widget interactions (click, type, signal assertions). Automatically cleans up widgets after each test.

### `store` (function-scoped)
```python
@pytest.fixture
def store(db_path: str) -> Store:
```

Returns a `Store` instance backed by a temp-file SQLite database. Patches `_connect_encrypted` to bypass the `sqlcipher3` requirement. Each test gets a fresh database.

### `db_path` (function-scoped)
```python
@pytest.fixture
def db_path() -> str:
```

Returns a path to a temporary SQLite database file. Cleaned up after the test.

### `wait_until` (helper)
```python
def wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> None:
```

Poll a predicate until it returns truthy or timeout elapses. Use for waiting on async operations in tests.

---

## Run Configuration

### Pytest Settings (from `pyproject.toml`)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
timeout = 30
timeout_method = "thread"
```

- **`timeout = 30`:** Each test has a 30-second timeout. Prevents hung tests from blocking CI.
- **`timeout_method = "thread"`:** Uses thread-based timeouts (`SIGALRM` conflicts with ffmpeg/GSR subprocesses).

### Environment Variables

- **`QT_QPA_PLATFORM=offscreen`:** Set automatically in `conftest.py` via `os.environ.setdefault(...)`. Ensures Qt never tries to open a real display.

---

## Running Tests Locally

### All non-GUI tests (fast + integration)
```bash
QT_QPA_PLATFORM=offscreen python -m pytest -m "not gui and not slow and not external"
```

### GUI tests only
```bash
QT_QPA_PLATFORM=offscreen python -m pytest -m gui
```

### Integration tests only
```bash
QT_QPA_PLATFORM=offscreen python -m pytest -m "integration and not external"
```

### All tests except slow and external
```bash
QT_QPA_PLATFORM=offscreen python -m pytest -m "not slow and not external"
```

### Single test file
```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_store.py -v
```

---

## Adding New Tests

1. Create `tests/test_your_module.py`
2. Import `pytest` and any needed fixtures
3. Add `pytestmark = [pytest.mark.<category>]` at the module level if all tests need the same marker
4. Use the `qapp`/`qtbot` fixtures for GUI tests, `store`/`db_path`/`tmp_path` for integration tests
5. Run locally to verify
6. Push — CI will run all marker-appropriate jobs automatically

### Quick checklist for new test files:
- [ ] File named `test_*.py` and placed in `tests/`
- [ ] `pytestmark` set to `gui`, `integration`, or both (or left unmarked for unit tests)
- [ ] Uses appropriate fixtures (`qapp` for gui, `store` for integration, `tmp_path` for filesystem)
- [ ] Passes locally: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_your_module.py`
- [ ] No `@pytest.mark.external` unless the test genuinely needs external services
