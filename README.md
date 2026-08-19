# ZeroGravity 

<p align="center">
  <b>Bridge the gap between your project dependencies and your local operating system.</b>
</p>

<p align="center">
  <a href="https://github.com/Rioeio/ZeroGravity/actions"><img src="https://img.shields.io/github/actions/workflow/status/Rioeio/ZeroGravity/ci.yml?branch=main&label=CI" alt="CI Status"></a>
  <a href="https://pypi.org/project/zerogravity"><img src="https://img.shields.io/pypi/v/zerogravity" alt="PyPI Version"></a>
  <a href="https://github.com/Rioeio/ZeroGravity/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue" alt="Python Versions"></a>
</p>

---

## Overview

Most developer tools operate in silos: package managers read `package.json` or `requirements.txt`, while disk cleaners delete temporary files blindly. 

**ZeroGravity (`zg`)** connects code manifests directly to your host environment. It parses deep dependency graphs (including lockfile transitive dependencies), probes system binaries, detects cross-project environment conflicts, self-heals runtime mismatches via native version managers (`nvm`, `pyenv`, `rustup`), and safely deduplicates packages across projects using OS-level virtualized linking.

```
                   ┌──────────────────────────────────────┐
                   │          Project Manifests           │
                   │ (package.json, pyproject.toml, etc.) │
                   └──────────────────┬───────────────────┘
                                      │
                                      ▼
  ┌───────────────────────────────────────────────────────────────────────┐
  │                           ZeroGravity Engine                          │
  ├───────────────────────┬───────────────────────┬───────────────────────┤
  │   1. Deep Binary      │  2. Conflict Radar    │   3. Self-Healing     │
  │      Mapping          │     & History         │      & Dedup Store    │
  └───────────────────────┴───────────────────────┴───────────────────────┘
                                      │
                                      ▼
                   ┌──────────────────────────────────────┐
                   │        Local Operating System        │
                   │   (PATH, openssl, pg_config, etc.)   │
                   └──────────────────────────────────────┘
```

---

## Key Features

### 1. Deep System-Binary Mapping
Traditional package managers assume system libraries are pre-installed. ZeroGravity parses both direct and transitive dependencies from lockfiles and cross-references them against required C libraries and system tools (e.g., `cryptography` -> `openssl`, `psycopg2` -> `pg_config`, `canvas` -> `pkg-config`/`cairo`, `sharp` -> `vips`).

### 2. Cross-Project Conflict Radar & Scan History
When working on multiple repositories, runtime requirements often clash (e.g., Project A requiring Node 18 while Project B requires Node 20). `zg scan` maintains a persistent local history ledger (`~/.zerogravity/scan_history.json`) to detect cross-project version conflicts across workspace directories over time.

### 3. Automated Environment Self-Healing (`zg heal`)
ZeroGravity doesn't just surface issues — it resolves them. `zg heal` detects installed version managers (`nvm`, `pyenv`, `rustup`), resolves version range specifiers into clean releases, and executes non-destructive remediation commands (e.g., `nvm install 18 && nvm use 18`, `pyenv install -s 3.11.4 && pyenv local 3.11.4`).

### 4. Multi-Ecosystem Transitive Lockfile Parsing
Performs deep lockfile inspection for:
- **Node.js**: `package-lock.json` (v1/v2/v3), `yarn.lock` (v1 & Berry multi-selectors), `pnpm-lock.yaml` (pnpm 6–11 key schemas).
- **Python**: `requirements.txt`, `pyproject.toml`, `poetry.lock`, `Pipfile.lock`.

### 5. Virtualized Symlinking & Smart Deduplication
Scans projects for duplicate dependency folders (`node_modules`, `.venv`, `vendor`), computes deterministic SHA-256 content hashes, moves packages into a global store (`~/.zerogravity/store`), and creates Windows Junction Points (`mklink /J`) or POSIX symlinks.
- **Read-Only Protection**: Ingested store packages are marked read-only (`chmod 0444`) to prevent accidental cross-project mutation.
- **Concurrency Safety**: Registry operations use SQLite WAL mode (`journal_mode=WAL`) and busy timeouts for process safety.

---

## Installation

Install ZeroGravity globally using `pip` or `pipx`:

```bash
pip install zerogravity
```

Or install from source in editable mode:

```bash
git clone https://github.com/Rioeio/ZeroGravity.git
cd ZeroGravity
pip install -e ".[dev]"
```

---

## Usage & CLI Reference

ZeroGravity provides a unified command line interface accessible via `zg`:

### `zg scan [PATHS...]`
Scan one or more project directories for dependency conflicts, missing binaries, and engine mismatches.

```bash
# Scan current working directory
zg scan

# Scan specific project directories
zg scan ~/projects/frontend ~/projects/backend

# Recursive sub-directory scan (skips vendor/build folders automatically)
zg scan ~/projects --recursive

# Output scan results as JSON for CI/CD pipelines
zg scan . --format json
```

### `zg heal [PATH]`
Interactively plan and execute self-healing remediations.

```bash
# Interactively review and apply remediations
zg heal

# Unattended automated self-healing (for CI or automated setups)
zg heal . --auto-approve
```

### `zg audit`
Audit your host OS environment without requiring a project directory. Shows all detected binaries, version managers, PATH directories, and environment variables.

```bash
zg audit
```

### `zg dedup`
Find and optimize duplicate dependency folders across projects.

```bash
# Scan project folders for duplicate dependency trees
zg dedup scan ~/projects/app-a ~/projects/app-b

# Dry-run optimization preview
zg dedup optimize ./node_modules --dry-run

# Optimize a dependency directory (symlink to central store)
zg dedup optimize ./node_modules

# Restore a linked folder back to a physical copy
zg dedup restore ./node_modules

# View total disk space savings
zg dedup status
```

### `zg status`
Display the system health dashboard at a glance.

```bash
zg status
```

---

## Ecosystem Matrix

| Ecosystem | Manifest Files | Lockfiles Supported | System Binary Dependencies |
| :--- | :--- | :--- | :--- |
| **Node.js** | `package.json` | `package-lock.json`<br>`yarn.lock`<br>`pnpm-lock.yaml` | `python`, `make`, `gcc`, `pkg-config`, `cairo`, `vips` |
| **Python** | `requirements.txt`<br>`pyproject.toml`<br>`Pipfile` | `poetry.lock`<br>`Pipfile.lock` | `openssl`, `pg_config`, `mysql_config`, `libxml2`, `libxslt`, `libsodium`, `libffi`, `gcc` |

---

## Development & Quality Assurance

ZeroGravity is built with high standards of type safety and test coverage:

```bash
# Run unit & integration test suite (96 tests)
pytest tests/

# Run Ruff linter
ruff check .

# Run Mypy static type checker
mypy
```

---

## License

Distributed under the [MIT License](LICENSE)
