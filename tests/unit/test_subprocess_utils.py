from __future__ import annotations

import asyncio
import gc
import sys
import warnings

import pytest

from zerogravity.scanner.subprocess_utils import run_command

SLEEPER = [sys.executable, "-c", "import time; time.sleep(30)"]


@pytest.fixture
def spawned(monkeypatch):
    created = []
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        proc = await real(*args, **kwargs)
        created.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    return created


async def test_run_command_returns_output(spawned):
    code, out, _ = await run_command([sys.executable, "-c", "print('hi')"], timeout=10)
    assert code == 0
    assert out.decode().strip() == "hi"


async def test_run_command_reports_nonzero_exit(spawned):
    code, _, _ = await run_command([sys.executable, "-c", "raise SystemExit(3)"], timeout=10)
    assert code == 3


async def test_timeout_kills_and_reaps_child(spawned):
    with pytest.raises(asyncio.TimeoutError):
        await run_command(SLEEPER, timeout=0.5)
    assert spawned[0].returncode is not None


async def test_transport_closed_after_success(spawned):
    await run_command([sys.executable, "-c", "pass"], timeout=10)
    assert spawned[0]._transport.is_closing()


async def test_transport_closed_after_timeout(spawned):
    with pytest.raises(asyncio.TimeoutError):
        await run_command(SLEEPER, timeout=0.5)
    assert spawned[0]._transport.is_closing()


def test_timeout_leaves_no_unclosed_transport_warning():
    """Regression: a timed-out probe used to leak its transport and emit
    'unclosed transport' / 'Event loop is closed' noise at shutdown."""

    async def go():
        with pytest.raises(asyncio.TimeoutError):
            await run_command(SLEEPER, timeout=0.5)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(go())
        gc.collect()

    leaked = [w for w in caught if "unclosed transport" in str(w.message)]
    assert not leaked
