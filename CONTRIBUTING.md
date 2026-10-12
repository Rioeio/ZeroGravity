# Contributing to ZeroGravity

Thank you for your interest in contributing to ZeroGravity!

## Development Setup

1. **Prerequisites**:
   - Python >= 3.11
   - `uv` (recommended) or `pip` / `virtualenv`

2. **Clone and Install**:
   ```bash
   git clone https://github.com/Rioeio/ZeroGravity.git
   cd ZeroGravity
   python -m venv .venv
   source .venv/bin/activate  # Or on Windows: .venv\Scripts\Activate.ps1
   pip install -e ".[dev]"
   ```

## Test Expectations

- All unit and integration tests must pass cleanly before opening a pull request:
  ```bash
  python -m pytest
  ```
- Type safety and linting are strictly enforced:
  ```bash
  python -m ruff check .
  python -m mypy src tests
  ```
- Any new features or bug fixes must include corresponding regression tests.

## Pull Request Guidelines

1. **Commit Messages**: Follow Conventional Commits format (`feat(...)`, `fix(...)`, `test(...)`, etc.).
2. **Hermeticity**: Tests must not touch real home directories or unmocked networks.
3. **Subprocess Management**: Always use `zerogravity.scanner.subprocess_utils.run_command` for executing child processes.
4. **Scope**: Keep pull requests focused on a single change or fix.
