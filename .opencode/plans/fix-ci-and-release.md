# Plan: Fix CI and Release Pipeline (OPEN)

## Problem

Three things block v0.3.x from reaching users:

1. **CI lint fails** — `tests/` directory has ~80 ruff errors (I001 unsorted imports, E501 line length, W605 escape seqs, F841 unused vars). No master commit can go green.
2. **Release preflight runs `pytest -m "not external"`** — this includes `gui` and `integration` markers that need a display + sqlcipher3 wheels, neither available in the GitHub Actions runner for those markers. Preflight fails, publish step never executes.
3. **No v0.3.0/v0.3.1 on PyPI** — consequence of (2).

## Fix descriptions

### 1. Auto-fix `tests/` lint

Run `ruff check --fix tests/ && ruff format tests/`. This handles I001, E401, F841, W605, and format. Manual fix for any remaining E501 (long lines) that ruff can't auto-fix — wrap or split strings.

### 2. Fix release preflight

The `-m "not external"` marker includes `gui` + `integration` + `slow` tests which fail in CI. Split into fast-only tests (matching CI's `fast` job: `-m "not gui and not integration and not slow and not external"`). A separate build+twine step doesn't need tests at all — `build` + `twine check` is enough for the release preflight.

### 3. Tag + publish v0.3.2

After fixes land on master, tag v0.3.2 and let the fixed release workflow publish to PyPI.

## Files to touch

| File | Change |
|------|--------|
| `tests/*.py` | Auto-fix lint (ruff --fix + ruff format) |
| `.github/workflows/release.yml` | Replace `-m "not external"` with `-m "not gui and not integration and not slow and not external"` (same as CI fast job) |

## Acceptance criteria

```bash
cd ~/Projects/moment && make lint
# → exit 0, no ruff errors

cd ~/Projects/moment && python -m pytest -m "not gui and not integration and not slow and not external" --tb=short -q
# → tests pass (what preflight will run)

cd ~/Projects/moment && git diff --stat .github/workflows/release.yml
# → confirms only the pytest marker line changed

cd ~/Projects/moment && python -m pytest -m "not external" --co 2>&1 | tail -5
# → confirms slow/gui/integration tests exist but are NOT excluded
```

## Stop when

- All acceptance criteria pass
- OR `make lint` still has errors after ruff --fix (means manual edits needed — stop and report remaining errors)

