# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-10-12

### Added
- **Security & Vulnerability Scanning**:
  - Full OSV.dev advisory hydration via `GET /v1/vulns/{id}` and automatic pagination token following.
  - CVSS v3.1 base score computation with official roundup formula and severity mapping.
  - CI exit code contract: `--fail-on` (`low`, `medium`, `high`, `critical`) and `--fail-on-outdated` (`patch`, `minor`, `major`).
  - Privacy guard preventing public queries for scoped packages, internal git/file URLs, and GOPRIVATE modules.
- **Ecosystem & Lockfile Support**:
  - Python: `uv.lock`, `pdm.lock`, PEP 735 `[dependency-groups]`, `setup.cfg`, and PEP 503 normalization.
  - Node: Yarn Berry (`yarn.lock` with metadata), Bun 1.2+ (`bun.lock`), `npm-shrinkwrap.json`, and npm `package-lock.json` v1.
  - Crates.io and Go proxy module freshness checks with Go case-encoded module path support (`!`).
- **State & System Reliability**:
  - Atomic state writes with temporary files and cross-platform locking (`portalocker`).
  - Corrupt state file quarantine with timestamped backups and `zg state doctor [--prune]`.
  - RFC 3339 UTC timestamps throughout state, history, and cache storage.
  - Version range intersection math for cross-project conflict detection with `zg history list` and `zg history clear`.
- **Toolchain & Deduplication Safety**:
  - Extended version manager probing for `asdf`, `mise`, and `fnm`.
  - Process tree termination on Windows (`taskkill /T /F`) and POSIX process groups.
  - Read-only dedup store permissions (`0o555` directories, `0o444` files) with temporary write context manager.
  - Atomic restore staging in sibling temporary directories preventing link loss on failure.
  - Store integrity verification command: `zg dedup verify [--repair]` and orphan cleanup `zg dedup clean`.
- **Packaging & Repo Hygiene**:
  - PEP 561 `py.typed` marker file for mypy compatibility.
  - Dynamic versioning single-sourced via hatchling from `src/zerogravity/__init__.py`.
  - Official MIT `LICENSE`, `SECURITY.md`, and `CONTRIBUTING.md`.
  - Multi-platform CI release workflow (`release.yml`) and Dependabot monthly updates.

## [0.3.0] - 2026-08-30

### Added
- **New Ecosystems**:
  - **Rust**: Added `CargoParser` supporting `Cargo.toml` manifests and `Cargo.lock` lockfiles with direct/transitive dependency resolution.
  - **Go**: Added `GoParser` supporting `go.mod` module definitions and `go.sum` checksum manifests.
- **8 New CLI Commands**:
  - `zg doctor`: Guided end-to-end diagnostic workflow combining environment audit, project scan, and interactive remediation.
  - `zg why <package>`: Deep dependency origin tracer identifying direct vs. transitive origin, resolved versions, lockfiles, and required system libraries.
  - `zg outdated`: Package registry freshness checker querying npm, PyPI, Crates.io, and Go proxy for outdated dependencies.
  - `zg audit-security`: OSV.dev vulnerability scanner checking dependencies against known CVEs and GHSAs.
  - `zg init`: Interactive and template configuration generator creating `.zerogravity.toml`.
  - `zg dedup scan`: Discovers duplicated dependency trees across workspace projects.
  - `zg dedup analyze`: Calculates potential disk savings and symlink compatibility.
  - `zg dedup optimize`: Executes safe cross-project deduplication via hardlinks and symlinks.
- **Enterprise Reporting**:
  - Added SARIF 2.1.0 output formatter (`--format sarif`) for GitHub Code Scanning integration.
  - Added JUnit XML output formatter (`--format junit`) for CI test suite summary reporting.
- **Container and Devcontainer Awareness**:
  - Automatic detection of `.devcontainer/devcontainer.json`, `Dockerfile`, and `docker-compose.yml`.
  - Host binary warnings suppressed in containerized projects unless explicitly requested via `--check-host-anyway`.
- **Scan Performance and Caching**:
  - Added 3-tier cache invalidation (file mtime, SHA-256 content hashing, ZeroGravity version) for project manifests.
  - Added `--no-cache` CLI flag to force fresh manifest re-parsing.
  - Added `compute_scoped_binaries()` to scope binary and library probing to project-relevant dependencies, eliminating full-catalog probing on `scan`, `heal`, and `doctor`.
  - Added memoization cache in `lib_detector` across unique library names within each scan run.
- **Shell Completion**:
  - Native shell completion support for Bash, Zsh, Fish, and PowerShell via `--install-completion` and `--show-completion`.

### Fixed
- **OpenSSL CLI/Library Collision**:
  - Fixed library probing in `probe_binary` to query `get_library_metadata()` before checking `shutil.which()`, preventing PATH executables (like `/usr/bin/openssl`) from falsely shadowing missing development headers/libraries (`libssl-dev`, `openssl-devel`).
  - Removed `_try_which` from library detection fallback strategies.
  - Updated `openssl` classification to `"type": "library"` in `system_deps.json`.
- **Windows Subprocess Execution**:
  - Added `.cmd`/`.bat` wrapping via `cmd.exe /c` for Windows batch scripts (e.g. `npm.cmd`).
  - Removed `WindowsSelectorEventLoopPolicy` override, allowing default Proactor loop for async I/O.
- **Flaky Tests**:
  - Isolated `--show-completion` test from host `$SHELL` environment variations by mocking shell detection.
  - Mocked `run_scan_sync` in `test_heal_command_executes_nvm_remediation` to guarantee deterministic remediation execution across environments regardless of host Node installation.

## [0.2.0] - 2026-08-12

### Added
- **Core Architecture & Ecosystem Support**:
  - Node.js support (`package.json`, `package-lock.json`) with engine constraint checking (`node`, `npm`).
  - Python support (`requirements.txt`, `pyproject.toml`) with Python version constraint checking.
- **Conflict & System Resolution**:
  - Conflict detection engine identifying missing binaries, engine constraint violations, and version mismatches.
  - Externalized system dependency database (`system_deps.json`) with schema validation.
  - Shared library fallback detection chain using `pkg-config`, `ldconfig`, `dpkg`, `rpm`, and `brew`.
- **Automated Remediation**:
  - Healing engine (`zg heal`) with version manager support for `nvm`, `pyenv`, and `rustup`.
- **CLI Commands**:
  - `zg scan`: Comprehensive project and workspace scanner.
  - `zg audit`: OS environment audit reporting detected binaries, version managers, and environment variables.
  - `zg status`: Instant system health dashboard.

## [0.1.0] - 2026-08-01

### Added
- Initial proof-of-concept release.
