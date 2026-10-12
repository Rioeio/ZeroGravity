"""Central state layer: atomic writes, cross-process locking, and corruption quarantine."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class LockTimeoutError(Exception):
    """Raised when acquiring a state file lock times out."""
    pass


def get_state_dir() -> Path:
    """Resolve the central state directory, honoring ZEROGRAVITY_HOME."""
    env_dir = os.environ.get("ZEROGRAVITY_HOME")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".zerogravity"


def ensure_state_dir(state_dir: Path | None = None) -> Path:
    """Ensure state directory exists with 0700 permissions where supported."""
    p = (state_dir or get_state_dir()).resolve()
    p.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        try:
            p.chmod(0o700)
        except OSError:
            pass
    return p


def get_lock_path(file_path: Path) -> Path:
    """Return corresponding lock file path."""
    return file_path.with_suffix(file_path.suffix + ".lock")


@contextmanager
def file_lock(lock_path: Path, timeout: float = 5.0) -> Generator[None, None, None]:
    """Acquire a cross-process exclusive lock on lock_path within timeout seconds."""
    ensure_state_dir(lock_path.parent)
    start_time = time.monotonic()
    f = open(lock_path, "a+b")
    try:
        acquired = False
        while not acquired:
            try:
                if sys.platform == "win32":
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() - start_time >= timeout:
                    raise LockTimeoutError(
                        f"Could not acquire lock on {lock_path} within {timeout}s"
                    ) from None
                time.sleep(0.02)
        try:
            yield
        finally:
            try:
                if sys.platform == "win32":
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        f.close()


def load_json(file_path: Path, default: Any = None) -> Any:
    """Load JSON from file_path, quarantining corrupt files to <name>.corrupt-<timestamp>."""
    if not file_path.exists():
        return default if default is not None else {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            raise json.JSONDecodeError("File is empty", "", 0)
        return json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        ts = int(time.time())
        corrupt_name = f"{file_path.name}.corrupt-{ts}"
        corrupt_path = file_path.parent / corrupt_name
        counter = 1
        while corrupt_path.exists():
            corrupt_path = file_path.parent / f"{file_path.name}.corrupt-{ts}_{counter}"
            counter += 1

        try:
            os.replace(file_path, corrupt_path)
        except OSError:
            pass

        logger.warning(
            "Corrupted state file '%s' detected (%s). Quarantined to '%s'. Starting fresh.",
            file_path.name,
            exc,
            corrupt_path.name,
        )
        return default if default is not None else {}
    except OSError as err:
        logger.warning("Error reading state file '%s': %s", file_path.name, err)
        return default if default is not None else {}


def atomic_write_json(file_path: Path, data: Any, indent: int = 2) -> None:
    """Write JSON data to a sibling temporary file and atomically replace target."""
    ensure_state_dir(file_path.parent)
    temp_file = file_path.with_name(
        f"{file_path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, file_path)
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
