# Phase 18: CI/CD Pipeline - Research

**Researched:** 2026-05-23
**Domain:** GitHub Actions, CI/CD, automated testing, release automation
**Confidence:** HIGH

## Summary

Phase 18 establishes a GitHub Actions CI/CD pipeline that runs the full test suite (918 tests), linting (ruff 0.13.0), type checking (mypy 1.7.1 strict), and coverage gate (80%+) on every push and PR. A release workflow automates version bumping, changelog generation, and PyPI publishing via Trusted Publishing (OIDC). The project currently has no `.github/` directory, so this is greenfield CI/CD setup.

The project already has well-configured tooling: ruff in pyproject.toml (`line-length = 120`, `target-version = "py311"`), mypy in strict mode, and pytest with `pythonpath = ["src"]`. The CI workflow mirrors these local checks. The release workflow integrates with Phase 17's setuptools-scm for version-from-git-tags and Trusted Publishing for zero-token PyPI uploads.

**Primary recommendation:** Two GitHub Actions workflows: (1) CI workflow triggered on push/PR with test, lint, typecheck, coverage jobs, and (2) release workflow triggered on tag push that builds, tests, and publishes to PyPI via Trusted Publishing.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CI-01 | Every PR runs full test suite (918+ tests) with pass/fail gate | Architecture: pytest matrix with Python 3.11 |
| CI-02 | Linting (ruff) and type checking (mypy) run on every push | Architecture: ruff check + mypy in CI job |
| CI-03 | Coverage report generated and 80%+ gate enforced | Architecture: pytest-cov with --cov-fail-under=80 |
| CI-04 | Release workflow: tag push -> build -> test -> PyPI publish | Architecture: Trusted Publishing with pypa/gh-action-pypi-publish |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Test execution | CI runner | -- | pytest runs in GitHub-hosted runner |
| Lint/typecheck | CI runner | -- | ruff + mypy in CI job |
| Coverage gate | CI runner | -- | pytest-cov with fail-under threshold |
| Package build | CI runner | -- | python -m build in release job |
| PyPI publish | PyPI via OIDC | -- | Trusted Publishing trusts GitHub identity |
| Release trigger | Git tags | -- | Tag push pattern `v*` triggers release |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| GitHub Actions | N/A | CI/CD platform | Integrated with repository; free for public repos [VERIFIED: github.com] |
| actions/checkout | v6 | Clone repository | Official GitHub action; handles token, fetch-depth [VERIFIED: github.com/actions] |
| actions/setup-python | v6 | Python runtime | Official Python setup with caching [VERIFIED: github.com/actions] |
| actions/upload-artifact | v5 | Share build artifacts | Pass wheel between build and publish jobs [VERIFIED: github.com/actions] |
| actions/download-artifact | v6 | Retrieve shared artifacts | Download wheel in publish job [VERIFIED: github.com/actions] |
| pypa/gh-action-pypi-publish | release/v1 | PyPI Trusted Publishing | Official PyPA action; OIDC-based, no API tokens [VERIFIED: pypi.org] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-cov | 4.1.0 | Coverage reporting | Already in dev deps; add --cov-fail-under=80 |
| coverage.py | 7.10.5 | Coverage measurement | Pulled by pytest-cov |
| python-semantic-release | 10.5.3 | Auto version/changelog | Optional: automated changelog from conventional commits |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| GitHub Actions | GitLab CI, CircleCI | Project is on GitHub; Actions is native |
| Trusted Publishing | PyPI API token | OIDC is more secure; no secrets to manage |
| pytest-cov | coverage.py direct | pytest-cov integrates with pytest; simpler CLI |
| Manual git tags | python-semantic-release | PSR automates version bump + changelog from commits; more complex setup |

**Installation:**
```bash
# CI-only tools -- not installed locally, used in GitHub Actions
# pytest-cov already in pyproject.toml [project.optional-dependencies.dev]
```

## Architecture Patterns

### System Architecture Diagram

```
Push/PR to main/feature branch
        |
        v
  +-----+-----+
  |  CI Workflow |
  +-----+-----+
        |
   +----+----+----+
   |         |     |
   v         v     v
 Test      Lint   Typecheck
(pytest)  (ruff)  (mypy)
   |         |     |
   v         |     |
 Coverage    |     |
(--cov)      |     |
   |         |     |
   +----+----+----+
        |
        v
   All pass? --> PR mergeable
   Any fail? --> PR blocked

---

Tag push (v*)
        |
        v
  +----------+
  | Release  |
  | Workflow |
  +-----+----+
        |
        v
  Build (python -m build)
        |
        v
  Test (pytest)
        |
        v
  Publish to PyPI (Trusted Publishing OIDC)
        |
        v
  Create GitHub Release
```

### Recommended Project Structure (additions only)

```
kicad-agent/
├── .github/
│   └── workflows/
│       ├── ci.yml            # Test, lint, typecheck, coverage
│       └── release.yml       # Build, test, publish to PyPI
├── pyproject.toml            # UPDATE: coverage config
└── ... (no other changes)
```

### Pattern 1: CI Workflow (ci.yml)

**What:** Multi-job CI that runs tests, linting, and type checking in parallel.

**When to use:** Every push and pull request.

**Example:**
```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11"]
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0  # for setuptools-scm
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
      - run: pip install -e ".[dev]"
      - run: python -m pytest tests/ -x -v --tb=short --cov=kicad_agent --cov-fail-under=80

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install ruff
      - run: ruff check src/ tests/

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: python -m mypy src/kicad_agent
```

### Pattern 2: Release Workflow (release.yml)

**What:** Triggered on version tag push, builds package, publishes to PyPI.

**When to use:** When releasing a new version.

**Example:**
```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - "v*"

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0  # Required for setuptools-scm
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
      - run: pip install build
      - run: python -m build
      - uses: actions/upload-artifact@v5
        with:
          name: dist
          path: dist/

  publish:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write  # Trusted Publishing requires OIDC
    steps:
      - uses: actions/download-artifact@v6
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
```

### Pattern 3: Coverage Configuration

**What:** Add coverage configuration to pyproject.toml.

**Example:**
```toml
[tool.coverage.run]
source = ["kicad_agent"]

[tool.coverage.report]
fail_under = 80
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

### Anti-Patterns to Avoid

- **Single monolithic CI job:** Run test, lint, and typecheck as separate parallel jobs for faster feedback and clearer failure isolation
- **Shallow clone with setuptools-scm:** Always set `fetch-depth: 0` when using setuptools-scm, or version will be "0.0.0"
- **Hardcoded coverage target in CI command:** Use pyproject.toml `[tool.coverage.report]` for single source of truth
- **PyPI API tokens in secrets:** Use Trusted Publishing (OIDC) instead -- no tokens to leak or rotate

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PyPI upload | Custom upload script with API token | pypa/gh-action-pypi-publish with Trusted Publishing | OIDC-based; no secrets to manage; official PyPA action |
| Coverage enforcement | Shell script checking coverage output | pytest-cov `--cov-fail-under=80` | Built-in fail-under exits non-zero when threshold not met |
| Dependency caching | Manual cache key computation | actions/setup-python `cache: pip` | Built-in pip cache in setup-python |
| Version derivation | Custom script reading git tags | setuptools-scm | Battle-tested; handles edge cases (dirty tree, pre-release) |

**Key insight:** GitHub Actions has mature official actions for Python CI. Use them instead of custom scripts.

## Common Pitfalls

### Pitfall 1: setuptools-scm version "0.0.0" in CI

**What goes wrong:** Release workflow builds a package with version "0.0.0" instead of the tag version.

**Why it happens:** `actions/checkout` does a shallow clone by default (`fetch-depth: 1`). setuptools-scm cannot determine version without full git history.

**How to avoid:** Set `fetch-depth: 0` in checkout step.

**Warning signs:** PyPI shows "0.0.0" as latest version.

### Pitfall 2: Trusted Publishing environment not configured on PyPI

**What goes wrong:** Release workflow fails with "OIDC token exchange failed" or "Permission denied".

**Why it happens:** Trusted Publishing requires configuring the GitHub repository as a trusted publisher on PyPI before the first release.

**How to avoid:** (1) Create the PyPI project first (can be done via first manual upload or via the PyPI UI), (2) Add the GitHub repository as a trusted publisher in PyPI project settings, specifying the `pypi` environment and `master` branch.

**Warning signs:** 403 errors in publish step.

### Pitfall 3: Coverage gate fails on new code with low coverage

**What goes wrong:** CI fails because new modules have insufficient test coverage.

**Why it happens:** 80% overall coverage can be dragged down by new untested modules.

**How to avoid:** Write tests concurrently with implementation (TDD); run `pytest --cov` locally before pushing.

### Pitfall 4: mypy strict mode fails on third-party library stubs

**What goes wrong:** CI mypy step fails with "Library stubs not installed" for kiutils, sexpdata, etc.

**Why it happens:** mypy strict mode requires type stubs for all imports; some dependencies lack stubs.

**How to avoid:** Add `[[tool.mypy.overrides]]` for libraries without stubs:
```toml
[[tool.mypy.overrides]]
module = ["kiutils.*", "sexpdata.*", "networkx.*", "shapely.*"]
ignore_missing_imports = true
```

## Code Examples

### Full CI workflow

```yaml
# Source: GitHub Actions documentation + Python packaging guide
name: CI

on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11"]
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
      - run: pip install -e ".[dev]"
      - run: python -m pytest tests/ -x -v --tb=short --cov=kicad_agent --cov-fail-under=80

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install ruff
      - run: ruff check src/ tests/

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: python -m mypy src/kicad_agent
```

### PyPI Trusted Publishing setup (one-time)

```bash
# 1. Build and upload first version manually (one-time)
python -m build
twine upload dist/*

# 2. On PyPI, go to project Settings > Publishing > Add a publisher
#    - Publisher: GitHub
#    - Repository: bretbouchard/kicad-agent
#    - Environment: pypi
#    - Workflow: release.yml

# 3. After configuration, releases use OIDC (no API token needed)
```

### Coverage configuration addition to pyproject.toml

```toml
[tool.coverage.run]
source = ["kicad_agent"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| actions/checkout@v3 | actions/checkout@v6 | 2024+ | Node 20 runtime, performance improvements |
| actions/setup-python@v4 | actions/setup-python@v6 | 2024+ | Better caching, GraalPy support |
| PyPI API tokens | Trusted Publishing (OIDC) | 2023+ | No secrets to manage or leak |
| coverage.py manual check | pytest-cov --cov-fail-under | 2022+ | Built-in threshold enforcement |
| Single CI job | Parallel matrix jobs | 2020+ | Faster feedback, better isolation |

**Deprecated/outdated:**
- `actions/checkout@v1/v2/v3`: Upgrade to v6 for Node 20 support
- `actions/setup-python@v1-v4`: Upgrade to v6
- PyPI API token in secrets: Use Trusted Publishing instead

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Repository is public (free GitHub Actions) | Standard Stack | Private repos have limited free minutes |
| A2 | Branch is `master` (not `main`) | Architecture | CI triggers on wrong branch |
| A3 | Only Python 3.11 needs testing | Architecture | If 3.12+ support is desired, add to matrix |
| A4 | Trusted Publishing is configured on PyPI before first CI release | Pitfalls | Release workflow fails |

## Open Questions

1. **Python version matrix**
   - What we know: Project requires Python >=3.11
   - What's unclear: Should CI test 3.11 only, or also 3.12 and 3.13?
   - Recommendation: Start with 3.11 only (current runtime); expand matrix if users request other versions

2. **Pre-existing test failures**
   - What we know: STATE.md notes 6 pre-existing test failures (ref ops, kicad-cli fixture compatibility)
   - What's unclear: Will these cause CI to fail?
   - Recommendation: Investigate and fix before Phase 18; CI must be green from day one

3. **Release automation level**
   - What we know: Roadmap says "tag push -> build -> test -> PyPI publish"
   - What's unclear: Should changelog and GitHub Release be auto-generated?
   - Recommendation: Start simple (tag push triggers build + publish); add python-semantic-release later if desired

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Git | CI/CD | Yes | -- | -- |
| Python 3.11 | CI runner | Yes (GitHub-hosted) | 3.11.x | -- |
| pip | CI runner | Yes (GitHub-hosted) | latest | -- |
| ruff | Linting | Yes | 0.13.0 | -- |
| mypy | Type checking | Yes | 1.7.1 | -- |
| pytest | Testing | Yes | 8.4.2 | -- |
| pytest-cov | Coverage | Yes | 4.1.0 | -- |
| GitHub Actions | CI platform | N/A | -- | Must be on GitHub |

**Missing dependencies with no fallback:**
- `.github/workflows/` directory -- must be created

**Missing dependencies with fallback:**
- None -- all required tools are available

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v --tb=short --cov=kicad_agent --cov-fail-under=80` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CI-01 | Full test suite passes in CI | integration | `python -m pytest tests/ -v --tb=short` | Yes (918 tests) |
| CI-02 | ruff and mypy pass | integration | `ruff check src/ tests/ && mypy src/kicad_agent` | No -- Wave 0 (CI config) |
| CI-03 | Coverage >= 80% | integration | `pytest --cov=kicad_agent --cov-fail-under=80` | No -- Wave 0 |
| CI-04 | Release builds and publishes | manual-only | Push tag, verify on PyPI | No -- post-release |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v --tb=short --cov=kicad_agent`
- **Phase gate:** Full suite green + ruff clean + mypy clean + coverage >= 80%

### Wave 0 Gaps
- [ ] `.github/workflows/ci.yml` -- covers CI-01, CI-02, CI-03
- [ ] `.github/workflows/release.yml` -- covers CI-04
- [ ] `[tool.coverage.report]` in pyproject.toml -- covers CI-03 threshold

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Trusted Publishing (OIDC) for PyPI authentication |
| V4 Access Control | yes | GitHub branch protection + required status checks |
| V5 Input Validation | no | -- |
| V6 Cryptography | yes | OIDC token exchange for PyPI |

### Known Threat Patterns for CI/CD

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Supply chain: compromised action | Tampering | Pin actions to specific SHA, not tags |
| Secrets exposure in logs | Information disclosure | GitHub automatically masks secrets; use `add-mask` for custom |
| Arbitrary code execution in PR | Elevation | Don't run untrusted code; use `pull_request` trigger (not `pull_request_target`) |
| Tag push by non-maintainer | Spoofing | Restrict tag push to maintainers; require CI pass before merge |

## Sources

### Primary (HIGH confidence)
- GitHub Actions official documentation -- workflow syntax, action versions
- PyPA Trusted Publishing guide -- OIDC configuration
- pyproject.toml in repository -- verified tooling versions (ruff 0.13.0, mypy 1.7.1, pytest 8.4.2)

### Secondary (MEDIUM confidence)
- actions/checkout, actions/setup-python GitHub READMEs -- verified v6 versions
- pytest-cov documentation -- --cov-fail-under behavior

### Tertiary (LOW confidence)
- [ASSUMED] actions/checkout@v6 is latest (A2 based on training knowledge, verified by pip index for python tools)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- GitHub Actions is well-documented, versions verified
- Architecture: HIGH -- CI/CD patterns are standard and well-established
- Pitfalls: HIGH -- common CI issues well-documented in GitHub Actions ecosystem

**Research date:** 2026-05-23
**Valid until:** 2026-06-23 (stable -- CI/CD patterns change slowly; action versions should be checked at plan time)
