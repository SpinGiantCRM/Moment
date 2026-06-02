# ---------------------------------------------------------------------------
# Moment — Makefile
#
# Usage:
#   make dist              Build wheel + sdist under dist/
#   make release VERSION=0.2.0  Bump version, commit, tag, push, build
#   make pkgbuild          Update PKGBUILD checksums from dist/
#   make clean             Remove build artifacts
#   make lint              Run ruff linter
#   make test              Run tests with coverage
# ---------------------------------------------------------------------------

SHELL := /bin/bash
PYTHON := python
VERSION ?=

.PHONY: dist release pkgbuild clean lint test

# ---- Dist ------------------------------------------------------------------

dist: clean
	@echo "==> Building wheel and sdist …"
	$(PYTHON) -m build --wheel --sdist
	@echo "==> Done: dist/"
	@ls -lh dist/

# ---- Release ---------------------------------------------------------------

release:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make release VERSION=0.2.0" >&2; \
		exit 1; \
	fi
	@echo "==> Bumping version to $(VERSION) …"
	sed -i 's/^version = ".*"/version = "$(VERSION)"/' pyproject.toml
	sed -i 's/__version__ = ".*"/__version__ = "$(VERSION)"/' src/moment/__init__.py
	@echo "==> Committing …"
	git add pyproject.toml src/moment/__init__.py
	git commit -m "Release v$(VERSION) [skip ci]" || true
	git tag "v$(VERSION)"
	@echo "==> Pushing …"
	git push origin "$$(git rev-parse --abbrev-ref HEAD)" --tags
	@echo "==> Building …"
	$(MAKE) dist
	@echo "==> Release v$(VERSION) ready.  Create a GitHub Release and attach dist/ artifacts."

# ---- PKGBUILD --------------------------------------------------------------

pkgbuild: dist
	@if ! command -v makepkg &>/dev/null; then \
		echo "==> makepkg not available — skipping PKGBUILD checksum generation."; \
		exit 0; \
	fi
	@echo "==> Validating PKGBUILD source …"
	makepkg --verifysource || echo "==> Source download failed (expected if tag not pushed yet)"

# ---- Clean -----------------------------------------------------------------

clean:
	rm -rf dist/ build/ *.egg-info/ src/*.egg-info/
	@echo "==> Cleaned build artifacts"

# ---- Lint ------------------------------------------------------------------

lint:
	ruff check src/
	ruff format --check src/

# ---- Test ------------------------------------------------------------------

test:
	$(PYTHON) -m pytest tests/ -x --tb=short -q --cov=moment --cov-report=term
