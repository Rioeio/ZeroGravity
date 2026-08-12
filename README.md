# ZeroGravity

**Bridge the gap between your project dependencies and your local operating system.**

ZeroGravity is a developer tool that scans your project manifests, probes your OS environment, and surfaces conflicts, missing binaries, version mismatches, and deduplication opportunities — all from a single CLI command.

## Features

- **Deep System-Binary Mapping** — Goes beyond `package.json`. Checks if the underlying OS has the system libraries and binaries needed to compile your dependencies (e.g., `gcc`, `openssl`, Python headers).
- **Cross-Project Conflict Radar** — Alerts you when multiple projects on your machine require conflicting runtime versions (e.g., Python 3.8 vs 3.11).
- **Virtualised Symlinking (Smart Deduplication)** — Replaces duplicate `node_modules` and `.venv` directories across projects with OS-level links to a central cache, saving gigabytes of disk space.
- **Automated Environment Self-Healing** — Detects version managers (`nvm`, `pyenv`, `asdf`) and can automatically switch or install the correct runtime version.

## Installation

```bash
pip install zerogravity
```

Or install in development mode:

```bash
git clone https://github.com/zerogravity-dev/zerogravity.git
cd zerogravity
pip install -e ".[dev]"
```

## Quick Start

```bash
# Full project scan — parse manifests, audit OS, detect conflicts
zg scan .

# OS-only audit — list all detected binaries and version managers
zg audit

# Find duplicate dependency folders across projects
zg dedup scan ~/projects/app-a ~/projects/app-b

# Deduplicate a specific dependency folder
zg dedup optimize ./node_modules/lodash

# Quick system health dashboard
zg status
```

## Supported Ecosystems

| Ecosystem | Manifest Files | Lock Files |
|-----------|---------------|------------|
| Node.js   | `package.json` | `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml` |
| Python    | `requirements.txt`, `pyproject.toml` | `poetry.lock`, `Pipfile.lock` |

## License

MIT
