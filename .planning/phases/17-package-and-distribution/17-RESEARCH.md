# Phase 17: Package & Distribution - Research

**Researched:** 2026-05-23
**Domain:** Python packaging, PyPI publishing, CLI distribution, documentation
**Confidence:** HIGH

## Summary

Phase 17 transforms kicad-agent from a repository-only tool into a distributable Python package installable via `pip install kicad-agent`. The project already has a functional `pyproject.toml` with dependencies, a CLI entry point (`kicad_agent.cli:main`), and 918 passing tests. The primary work is completing the packaging metadata, adding a build system, setting up PyPI publishing via Trusted Publishing (OIDC), and creating documentation.

The existing `pyproject.toml` lacks a `[build-system]` section, which is required for `pip install` to work. It also lacks optional dependency groups for documentation tooling. The CLI uses argparse and is functional but relatively simple -- migrating to click is optional and should be evaluated based on whether subcommand complexity justifies the added dependency.

**Primary recommendation:** Add setuptools `[build-system]`, setuptools-scm for version-from-git-tags, keep argparse (the CLI is simple enough), use MkDocs Material for documentation, and configure PyPI Trusted Publishing for zero-token releases.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DIST-01 | `pip install kicad-agent` installs a working package with CLI entry point | Standard Stack: setuptools build-system, setuptools-scm versioning |
| DIST-02 | `kicad-agent` CLI command runs operations, validation, and project context | Architecture Patterns: CLI entry point via `[project.scripts]` |
| DIST-03 | Package metadata (version, description, dependencies) is correct on PyPI | Standard Stack: pyproject.toml metadata, `python -m build`, Trusted Publishing |
| DIST-04 | README and API documentation cover all public interfaces | Standard Stack: MkDocs Material + mkdocstrings-python, README structure |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Package build | Build tooling | -- | setuptools + build module produce sdist/wheel |
| CLI entry point | Package metadata | -- | `[project.scripts]` in pyproject.toml creates console_scripts |
| Version management | Git tags | -- | setuptools-scm derives version from git history |
| PyPI publishing | CI/CD (Phase 18) | -- | Trusted Publishing via GitHub Actions |
| Documentation | Static site | CDN hosting | MkDocs Material builds static HTML |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| setuptools | >=75.0 | Build backend | Standard Python build backend; works with pyproject.toml [VERIFIED: pyproject.toml already uses setuptools conventions] |
| setuptools-scm | 10.0.5 | Version from git tags | Derives version from git tags/commits; no manual version bumping [VERIFIED: pip index] |
| python -m build | 1.2.2 | Build sdist + wheel | Official PEP 517 build frontend; replaces `setup.py sdist` [VERIFIED: installed locally] |
| MkDocs Material | 9.7.6 | Documentation site | Best Python docs theme; search, API reference, syntax highlighting [VERIFIED: pip index] |
| mkdocstrings-python | 2.0.3 | API doc generation | Auto-generates API docs from Python docstrings [VERIFIED: pip index] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| twine | >=6.0 | PyPI upload verification | Manual upload/testing; CI uses Trusted Publishing instead |
| mike | >=2.0 | Versioned docs deployment | When hosting docs on GitHub Pages with version selector |
| click | 8.4.1 | CLI framework (optional) | If subcommand complexity grows beyond argparse comfort zone |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| setuptools + setuptools-scm | hatchling + hatch-vcs | Hatch is newer but less ecosystem familiarity; setuptools is battle-tested |
| MkDocs Material | Sphinx (9.0.4) | Sphinx is more powerful for large C/Java projects; MkDocs is simpler and faster for Python |
| argparse | click | Click adds decorator-based subcommands and color output; argparse works fine for current CLI complexity |
| setuptools | poetry-core | Poetry locks to its own resolver; setuptools uses pip's resolver; project already uses pip |

**Installation:**
```bash
pip install build setuptools-scm
pip install mkdocs-material mkdocstrings-python mike
```

**Version verification:**
```bash
pip index versions setuptools-scm    # 10.0.5
pip index versions mkdocs-material   # 9.7.6
pip index versions mkdocstrings-python  # 2.0.3
```

## Architecture Patterns

### System Architecture Diagram

```
Git Tags ──> setuptools-scm ──> version in package
                                    |
                                    v
pyproject.toml ──> python -m build ──> dist/*.whl + *.tar.gz
                                    |
                                    v
                          [project.scripts] ──> kicad-agent CLI entry point
                                    |
                                    v
                          pip install kicad-agent ──> ~/.local/bin/kicad-agent

Source code + docstrings ──> MkDocs Material ──> Static HTML docs
                                    |
                                    v
                              mike deploy ──> GitHub Pages (versioned)
```

### Recommended Project Structure (changes from current)

```
kicad-agent/
├── pyproject.toml          # ADD: [build-system], [tool.setuptools_scm], docs deps
├── LICENSE                 # CREATE: MIT or Apache-2.0
├── README.md               # UPDATE: full package docs, install, usage
├── mkdocs.yml              # CREATE: MkDocs configuration
├── docs/                   # CREATE: documentation source
│   ├── index.md            # Landing page
│   ├── getting-started.md  # Installation and quick start
│   ├── cli.md              # CLI reference
│   ├── api/                # Auto-generated from docstrings
│   │   ├── parser.md
│   │   ├── ops.md
│   │   └── ...
│   └── examples/           # Usage examples
│       └── ...
├── src/
│   └── kicad_agent/
│       ├── __init__.py     # UPDATE: add __version__ from setuptools-scm
│       ├── cli.py          # EXISTS: argparse CLI (no changes needed)
│       └── ...
└── tests/
    └── ...
```

### Pattern 1: Build System Configuration

**What:** Add `[build-system]` to pyproject.toml with setuptools backend and setuptools-scm for dynamic versioning.

**When to use:** Required for any pip-installable package.

**Example:**
```toml
# Source: https://packaging.python.org/en/latest/guides/modernize-setup-py-project/
[build-system]
requires = ["setuptools>=75.0", "setuptools-scm>=10.0"]
build-backend = "setuptools.build_meta"

[project]
name = "kicad-agent"
dynamic = ["version"]  # version from setuptools-scm
description = "AI-safe structural editing of KiCad schematic, PCB, symbol, and footprint files"
requires-python = ">=3.11"
# ... existing fields ...

[tool.setuptools_scm]
# Derives version from git tags (e.g., v0.1.0 -> "0.1.0")
# Untagged commits get dev suffix: 0.1.1.dev5+gabcdef
fallback_version = "0.0.0"
```

### Pattern 2: CLI Entry Point (already working)

**What:** The `[project.scripts]` section creates a console script wrapper.

**When to use:** Already configured -- verify it works after build-system is added.

**Example:**
```toml
[project.scripts]
kicad-agent = "kicad_agent.cli:main"
```

### Pattern 3: MkDocs Configuration

**What:** Documentation site built from Markdown with auto-generated API references.

**Example:**
```yaml
# mkdocs.yml
site_name: kicad-agent
theme:
  name: material
  features:
    - navigation.sections
    - search.suggest
    - content.code.copy

plugins:
  - mkdocstrings:
      handlers:
        python:
          paths: [src]
          options:
            show_source: true
            show_root_heading: true

nav:
  - Home: index.md
  - Getting Started: getting-started.md
  - CLI Reference: cli.md
  - API Reference:
    - api/parser.md
    - api/ops.md
    - api/validation.md
```

### Anti-Patterns to Avoid

- **Static version in pyproject.toml**: Use `dynamic = ["version"]` with setuptools-scm instead of hardcoding; avoids version desync between git tags and package metadata
- **Including tests in wheel**: setuptools should exclude `tests/` from the wheel; configure `[tool.setuptools.packages.find]` with `where = ["src"]`
- **README as only documentation**: README covers quick-start; full API docs need MkDocs with mkdocstrings
- **Missing LICENSE file**: PyPI requires a license identifier; create LICENSE file and add `license` field to pyproject.toml

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Version management | Manual version bumping in pyproject.toml | setuptools-scm | Derives from git tags; handles dev versions, dirty working tree |
| PyPI authentication | API token stored as secret | Trusted Publishing (OIDC) | No tokens to manage; PyPI trusts GitHub Actions identity |
| API documentation | Hand-written doc pages | mkdocstrings-python | Auto-generates from Python docstrings; stays in sync with code |
| Wheel building | Custom build script | `python -m build` | Handles PEP 517 build isolation, sdist + wheel in one command |

**Key insight:** The Python packaging ecosystem has standardized around pyproject.toml + build frontends. Don't fight it -- follow the conventions.

## Common Pitfalls

### Pitfall 1: Missing build-system causes silent pip install failure

**What goes wrong:** `pip install .` works in development but `pip install kicad-agent` from PyPI fails or installs without the package code.

**Why it happens:** Without `[build-system]`, pip uses legacy setuptools behavior that may not discover the `src/` layout correctly.

**How to avoid:** Add `[build-system]` with `setuptools.build_meta` backend and configure `[tool.setuptools.packages.find]` with `where = ["src"]`.

**Warning signs:** `pip install .` succeeds but `import kicad_agent` fails in a fresh venv.

### Pitfall 2: setuptools-scm version is "0.0.0" on CI

**What goes wrong:** Build on CI produces version "0.0.0" because git history is shallow.

**Why it happens:** GitHub Actions `actions/checkout` does a shallow clone by default (`fetch-depth: 1`).

**How to avoid:** Either set `fetch-depth: 0` in checkout, or configure `version_scheme = "no-guess-dev"` in setuptools-scm, or ensure git tags are fetched.

**Warning signs:** `python -m setuptools_scm` returns "0.0.0" in CI logs.

### Pitfall 3: README not rendering on PyPI

**What goes wrong:** PyPI shows raw Markdown or plain text instead of rendered README.

**Why it happens:** PyPI requires README to be specified in pyproject.toml with the correct content type.

**How to avoid:** Add `readme = "README.md"` and ensure the file is valid CommonMark.

### Pitfall 4: Long description content type mismatch

**What goes wrong:** PyPI displays README as raw text.

**Why it happens:** Missing `readme` field or wrong content_type.

**How to avoid:** Use `readme = {file = "README.md", content-type = "text/markdown"}` in pyproject.toml.

## Code Examples

### pyproject.toml additions (minimal)

```toml
# Source: https://packaging.python.org/en/latest/guides/modernize-setup-py-project/
[build-system]
requires = ["setuptools>=75.0", "setuptools-scm>=10.0"]
build-backend = "setuptools.build_meta"

[project]
name = "kicad-agent"
dynamic = ["version"]
readme = {file = "README.md", content-type = "text/markdown"}
license = "MIT"
requires-python = ">=3.11"
description = "AI-safe structural editing of KiCad schematic, PCB, symbol, and footprint files"
dependencies = [
    "kiutils>=1.4.8",
    "sexpdata>=1.0.0",
    "networkx>=3.0",
    "httpx>=0.28.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.0",
    "mypy>=1.7",
    "ruff>=0.13",
]
docs = [
    "mkdocs-material>=9.7",
    "mkdocstrings-python>=2.0",
]

[project.scripts]
kicad-agent = "kicad_agent.cli:main"

[project.urls]
Homepage = "https://github.com/bretbouchard/kicad-agent"
Documentation = "https://bretbouchard.github.io/kicad-agent"
Repository = "https://github.com/bretbouchard/kicad-agent"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools_scm]
fallback_version = "0.0.0"
```

### __init__.py version pattern

```python
# Source: setuptools-scm documentation
"""kicad-agent: AI-safe structural editing of KiCad files."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kicad-agent")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"
```

### Verify package build

```bash
# Build sdist + wheel
python -m build

# Verify contents
tar -tzf dist/kicad_agent-*.tar.gz | head -20
unzip -l dist/kicad_agent-*.whl | head -20

# Test install in fresh venv
python -m venv /tmp/test-env && source /tmp/test-env/bin/activate
pip install dist/kicad_agent-*.whl
kicad-agent --schema | python -m json.tool | head -5
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| setup.py | pyproject.toml + [build-system] | PEP 517/518 (2019+) | No setup.py needed; build isolation |
| setup.py sdist/bdist_wheel | python -m build | 2021+ | PEP 517 build frontend |
| API tokens for PyPI | Trusted Publishing (OIDC) | 2023+ | No secrets management |
| Sphinx for Python docs | MkDocs Material + mkdocstrings | 2022+ | Faster builds, Markdown-native |
| Manual version bumping | setuptools-scm from git tags | 2018+ | Single source of truth |

**Deprecated/outdated:**
- `setup.py` as primary config: Use pyproject.toml instead; setup.py can be removed
- `twine upload` in CI: Use Trusted Publishing with `pypa/gh-action-pypi-publish@release/v1`
- `bumpversion`/`bump2version`: Use setuptools-scm or python-semantic-release instead

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Project will use MIT license | Standard Stack | License field in pyproject.toml needs correct identifier |
| A2 | GitHub Pages will host documentation | Architecture | Deployment config differs for other hosts |
| A3 | Repository URL is github.com/bretbouchard/kicad-agent | Code Examples | project.urls need correction |
| A4 | argparse CLI is sufficient for current needs | Standard Stack | If click migration is desired, additional dependency + refactor needed |

## Open Questions

1. **License choice**
   - What we know: Project has no LICENSE file currently
   - What's unclear: MIT vs Apache-2.0 vs other
   - Recommendation: MIT is standard for Python tools; confirm with user

2. **Documentation hosting**
   - What we know: No docs directory exists
   - What's unclear: GitHub Pages vs ReadTheDocs vs other
   - Recommendation: GitHub Pages (free, integrated with repo)

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python >=3.11 | Runtime | Yes | 3.11.11 | -- |
| python -m build | Package build | Yes | 1.2.2 | pip install build |
| ruff | Linting | Yes | 0.13.0 | -- |
| mypy | Type checking | Yes | 1.7.1 | -- |
| pytest | Testing | Yes | 8.4.2 | -- |
| setuptools-scm | Version mgmt | No | -- | pip install in plan |
| MkDocs Material | Docs | No | -- | pip install in plan |
| twine | Upload verification | No | -- | pip install in plan |

**Missing dependencies with no fallback:**
- setuptools-scm, MkDocs Material -- install during plan execution

**Missing dependencies with fallback:**
- twine -- only needed for manual upload; CI uses Trusted Publishing

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v --tb=short` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DIST-01 | pip install produces working package | integration | `python -m build && pip install dist/*.whl && kicad-agent --schema` | No -- Wave 0 |
| DIST-02 | CLI entry point runs all commands | integration | `python -m pytest tests/test_cli.py -x` | Yes (existing) |
| DIST-03 | Package metadata correct on PyPI | manual-only | Verify on pypi.org after publish | No -- post-release |
| DIST-04 | Documentation builds without errors | integration | `mkdocs build --strict` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green + `python -m build` succeeds + `mkdocs build --strict` passes

### Wave 0 Gaps
- [ ] `tests/test_packaging.py` -- covers DIST-01 (build + install verification)
- [ ] `mkdocs.yml` -- docs build configuration
- [ ] `docs/` directory -- documentation source files

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | -- |
| V3 Session Management | no | -- |
| V4 Access Control | no | -- |
| V5 Input Validation | yes | Pydantic v2 models for operation validation |
| V6 Cryptography | no | -- |

### Known Threat Patterns for Python Packaging

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Supply chain: typo-squatting | Spoofing | Register package name on PyPI early |
| Dependency confusion | Tampering | Pin exact versions in pyproject.toml |
| Trusted Publishing misconfig | Elevation | Restrict to main branch, require approval |

## Sources

### Primary (HIGH confidence)
- pyproject.toml in repository -- verified current state
- pip index versions output -- verified setuptools-scm 10.0.5, MkDocs Material 9.7.6, mkdocstrings-python 2.0.3
- Python packaging guide (packaging.python.org) -- standard PEP 517/518 patterns

### Secondary (MEDIUM confidence)
- PyPI Trusted Publishing documentation -- OIDC-based publishing from GitHub Actions
- setuptools-scm documentation -- version scheme configuration

### Tertiary (LOW confidence)
- [ASSUMED] Repository URL structure (A3)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all versions verified via pip index, patterns from official Python packaging guide
- Architecture: HIGH -- pyproject.toml conventions well-established, project already has most structure
- Pitfalls: HIGH -- common packaging issues well-documented in Python ecosystem

**Research date:** 2026-05-23
**Valid until:** 2026-06-23 (stable -- packaging tools change slowly)
