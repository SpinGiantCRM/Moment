# Contributing to Moment

## Development Setup

```bash
git clone https://github.com/SpinGiantCRM/moment.git
cd moment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[bot,mcp]"
```

## Prerequisites

- Python 3.11+
- PyQt6
- ffmpeg with NVENC (`h264_nvenc`, `hevc_nvenc` or `av1_nvenc`)
- rclone with a remote configured

Optional but recommended:
- `gpu-screen-recorder` (for capture testing)
- NVIDIA GPU (for NVENC testing)

## Code Quality

### Linting
```bash
make lint              # ruff check + format
ruff check src/        # Check only
ruff format src/       # Auto-format
```

### Type Checking
```bash
# Moment uses runtime type hints with `from __future__ import annotations`
# No static type checker is currently enforced, but all public APIs
# must have complete type annotations.
```

### Testing
```bash
make test              # Full test suite with coverage
python -m pytest tests/ -x --tb=short -q  # Quick run
python -m pytest tests/test_store.py -x --tb=short -v  # Specific module
```

## Pull Request Process

1. **Create an issue** describing the change before starting work
2. **Fork the repository** and create a feature branch (`feature/your-feature`)
3. **Follow coding standards** (see `AGENTS.md` for standards)
4. **Write tests** for new functionality — aim for the test to exist before the implementation
5. **Run the full test suite** — `make test` must pass
6. **Run the linter** — `make lint` must pass
7. **Update documentation** if changing public APIs or architecture
8. **Submit a pull request** with a clear description of changes

## Code Review Checklist

- [ ] Type hints complete on all function signatures
- [ ] Docstrings present for public classes/methods (Google-style)
- [ ] Tests cover success and error paths
- [ ] No bare `except:` or `except Exception:` without logging
- [ ] No `# nosec` without explanatory comment
- [ ] Signal/slot dispatch for cross-thread communication (not direct calls)
- [ ] New config keys added to `_ALLOWED_KEYS` or `_ALLOWED_PREFIXES`
- [ ] Schema changes add migration to `_MIGRATIONS` list in `base.py` + update `SCHEMA_SQL`
- [ ] Secret values use keyring, not env vars or config table
- [ ] New dependencies added to `pyproject.toml` with version constraints

## Testing Guidelines

### Test Structure
- Tests live in `tests/test_<module_name>.py`
- Use `conftest.py` fixtures (store, qapp, sample_clip)
- Mock external dependencies (GSR, ffmpeg, rclone, keyring)
- Use `tmp_path` or `tempfile` for filesystem operations

### What to Test
- **CRUD operations:** Create, read, update, delete for each entity
- **Edge cases:** Empty results, missing files, invalid input
- **Error paths:** Component failures, network errors, corrupt data
- **Concurrency:** Thread safety of shared state (where applicable)
- **Encryption:** Key generation, round-trip encrypt/decrypt

### What NOT to Test
- Qt rendering (use offscreen platform for basic smoke tests)
- External tool behavior (ffmpeg, rclone, GSR — mock these)
- Platform-specific behavior (Linux-only app, no need for cross-platform)

## Documentation Standards

- `AGENTS.md` — AI agent briefing (highest priority for accuracy)
- `ARCHITECTURE.md` — System architecture and request flows
- `SECURITY.md` — Security model and encryption details
- `TRUTH.md` — Current state and aspirations
- `README.md` — Quick start and feature overview
- `docs/` — Detailed guides and references

## Release Process

1. `make release VERSION=x.y.z` — bumps version, commits, tags, pushes, builds
2. Create a GitHub Release with release notes
3. Attach built artifacts from `dist/`
4. CI publishes to PyPI automatically

## Getting Help

- Open an issue for bugs or feature requests
- Check existing issues and discussions before posting
- See `ARCHITECTURE.md` and `AGENTS.md` for system understanding
