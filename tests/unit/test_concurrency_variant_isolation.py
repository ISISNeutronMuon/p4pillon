"""
Regression tests verifying that the thread/asyncio "variants" of SharedNT,
pvrecipe, and Server are genuinely distinct and don't leak global state
into one another.

The import-order and Server._context checks run in a fresh subprocess, since
their correctness depends on import order/global state that earlier-imported
test modules in the same pytest session may have already disturbed.
"""

import subprocess
import sys

import pytest
from p4p.server.asyncio import SharedPV as AsyncioSharedPV
from p4p.server.thread import SharedPV as ThreadSharedPV

from p4pillon.definitions import PVTypes


def _run(script: str) -> subprocess.CompletedProcess:
    # S603: script is always a hardcoded literal from this module, never untrusted input.
    # check=False: callers assert on returncode so the script's own output
    # reaches the assertion message.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )


def test_asyncio_sharednt_is_not_the_thread_sharednt():
    """asyncio and thread SharedNT must be distinct classes, each deriving
    from its own flavour's real p4p SharedPV. Class identity is fixed at
    class-creation time under the inheritance design, so unlike the
    import-order tests below this needs no subprocess."""
    from p4pillon.asyncio.sharednt import SharedNT as AsyncioSharedNT
    from p4pillon.thread.sharednt import SharedNT as ThreadSharedNT

    assert AsyncioSharedNT is not ThreadSharedNT, "asyncio and thread SharedNT resolved to the same class object"
    assert issubclass(AsyncioSharedNT, AsyncioSharedPV), "asyncio SharedNT does not derive from p4p asyncio SharedPV"
    assert issubclass(ThreadSharedNT, ThreadSharedPV), "thread SharedNT does not derive from p4p thread SharedPV"


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


def test_records_asyncio_probe_does_not_disable_hooks():
    """The former monkey-patch could even be defeated by p4pillon itself:
    p4pillon.server.records.dynamic._check_pv_factory_is_safe imports
    p4p.server.asyncio directly, which used to freeze the unpatched base
    class if it ran before p4pillon.server.asyncio was first imported."""
    script = """
from p4pillon.server.records.dynamic import _check_pv_factory_is_safe
class Dummy:
    pass
_check_pv_factory_is_safe(Dummy)
from p4pillon.server.asyncio import SharedPV
from p4pillon.server.raw import HandlerHooksMixin
assert issubclass(SharedPV, HandlerHooksMixin)
print('OK')
"""
    result = _run(script)
    assert result.returncode == 0, result.stdout + result.stderr


def test_unflavored_pvrecipe_fails_loudly():
    """The base-module recipes are not bound to a concurrency flavor, and
    must refuse to build a PV rather than silently constructing a raw-flavored
    one (which would run put/rpc handlers on PVA network threads with none of
    the flavors' serialization)."""
    from p4pillon.pvrecipe import PVScalarRecipe

    with pytest.raises(TypeError, match=r"thread\.pvrecipe"):
        PVScalarRecipe(PVTypes.DOUBLE, "test", 1.0).create_pv()


def test_handler_hooks_survive_p4p_imported_first():
    """Regression test for the former monkey-patch architecture: the patch of
    p4p.server.raw.SharedPV silently did nothing if p4p.server.thread/asyncio
    had already been imported, so the open()/post()/close() handler callbacks
    never fired. With HandlerHooksMixin composed by ordinary inheritance,
    import order must not matter."""
    script = """
import p4p.server.thread   # imported BEFORE p4pillon -- used to defeat the patch
import p4p.server.asyncio
from p4p.nt import NTScalar
from p4pillon.server.raw import HandlerHooksMixin
from p4pillon.server.thread import SharedPV

calls = []
class H:
    def open(self, value):
        calls.append('open')
    def post(self, pv, value):
        calls.append('post')
    def close(self, pv):
        calls.append('close')

pv = SharedPV(handler=H(), nt=NTScalar('d'), initial=5.0)
pv.post(6.0)
pv.close()
assert calls == ['open', 'post', 'close'], f'hooks did not all fire: {calls}'

from p4pillon.server.asyncio import SharedPV as AsyncSharedPV
assert issubclass(SharedPV, HandlerHooksMixin)
assert issubclass(AsyncSharedPV, HandlerHooksMixin)
print('OK')
"""
    result = _run(script)
    assert result.returncode == 0, result.stdout + result.stderr


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
