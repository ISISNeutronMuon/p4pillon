"""
Regression tests verifying that the thread/asyncio "variants" of SharedNT,
pvrecipe, and Server are genuinely distinct and don't leak global state
into one another.

The SharedNT/Server._context checks run in a fresh subprocess, since their
correctness depends on import order/global state that earlier-imported test
modules in the same pytest session may have already disturbed.
"""

import subprocess
import sys

from p4p.server.asyncio import SharedPV as AsyncioSharedPV
from p4p.server.thread import SharedPV as ThreadSharedPV

from p4pillon.definitions import PVTypes


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)


def test_asyncio_sharednt_is_not_the_thread_sharednt():
    """asyncio and thread SharedNT must be distinct classes, each deriving
    from its own flavour's real p4p SharedPV."""
    script = """
from p4pillon.asyncio.sharednt import SharedNT as AsyncioSharedNT
from p4pillon.thread.sharednt import SharedNT as ThreadSharedNT
from p4p.server.asyncio import SharedPV as AsyncioSharedPV
from p4p.server.thread import SharedPV as ThreadSharedPV
assert AsyncioSharedNT is not ThreadSharedNT, (
    'asyncio and thread SharedNT resolved to the same class object')
assert issubclass(AsyncioSharedNT, AsyncioSharedPV), (
    'asyncio SharedNT does not derive from p4p asyncio SharedPV')
assert issubclass(ThreadSharedNT, ThreadSharedPV), (
    'thread SharedNT does not derive from p4p thread SharedPV')
print('OK')
"""
    result = _run(script)
    assert result.returncode == 0, result.stdout + result.stderr


def test_thread_pvrecipe_builds_thread_sharedpv():
    """p4pillon.thread.pvrecipe.PVScalarRecipe.create_pv() must build a PV
    backed by p4p's thread SharedPV, not the asyncio one."""
    from p4pillon.thread.pvrecipe import PVScalarRecipe

    pv = PVScalarRecipe(PVTypes.DOUBLE, "test", 1.0).create_pv()

    assert isinstance(pv, ThreadSharedPV)
    assert not isinstance(pv, AsyncioSharedPV)


async def test_asyncio_pvrecipe_builds_asyncio_sharedpv():
    """p4pillon.asyncio.pvrecipe.PVScalarRecipe.create_pv() must build a PV
    backed by p4p's asyncio SharedPV, not the thread one. Runs as a
    coroutine since asyncio SharedPV construction needs a running loop."""
    from p4pillon.asyncio.pvrecipe import PVScalarRecipe

    pv = PVScalarRecipe(PVTypes.DOUBLE, "test", 1.0).create_pv()

    assert isinstance(pv, AsyncioSharedPV)
    assert not isinstance(pv, ThreadSharedPV)


def test_base_server_context_not_polluted_by_variant_import():
    """Importing p4pillon.asyncio.server / p4pillon.thread.server must not
    mutate the shared p4pillon.server.server.Server._context attribute."""
    script = """
from p4pillon.server.server import Server as BaseServer
from p4p.client.raw import Context as RawContext
assert BaseServer._context is RawContext, (
    f'base Server._context already wrong before any variant import: {BaseServer._context}')
from p4pillon.asyncio.server import Server as AsyncServer
from p4p.client.asyncio import Context as AsyncioContext
assert AsyncServer._context is AsyncioContext
assert BaseServer._context is RawContext, (
    f'importing p4pillon.asyncio.server mutated the base Server._context to {BaseServer._context}')
from p4pillon.thread.server import Server as ThreadServer
from p4p.client.thread import Context as ThreadContext
assert ThreadServer._context is ThreadContext
assert BaseServer._context is RawContext, (
    f'importing p4pillon.thread.server mutated the base Server._context to {BaseServer._context}')
print('OK')
"""
    result = _run(script)
    assert result.returncode == 0, result.stdout + result.stderr
