"""p4p PR #172 functionality -- support for open(), post(), and close()
handler callbacks in addition to p4p's own put()/rpc()/onFirstConnect()/
onLastDisconnect().

`HandlerHooksMixin` carries the added behaviour; each concurrency flavor
composes it with the corresponding p4p class by ordinary inheritance
(`p4pillon.server.thread.SharedPV`, `p4pillon.server.asyncio.SharedPV`, and
the raw-flavored `SharedPV` below). This replaces the previous approach of
monkey-patching ``p4p.server.raw.SharedPV`` before importing
``p4p.server.thread``/``p4p.server.asyncio`` -- that patch silently did
nothing if the p4p module had already been imported by anyone else first,
whereas inheritance is immune to import order.
"""

import threading
from abc import ABC
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import AbstractContextManager, nullcontext
from enum import Enum
from typing import Any

from p4p import Value
from p4p._p4p import SharedPV as _RawSharedPV
from p4p.server.raw import Handler as _P4PHandler
from p4p.server.raw import SharedPV as _SharedPV

from p4pillon.utils import mark_all

__all__ = ("Handler", "HandlerHooksMixin", "InitialUpdate", "SharedPV", "apply_initial_update")

# Stand-in for the lock a plain p4p SharedPV doesn't have; stateless and
# re-entrant, so one shared instance serves every call.
_NO_LOCK = nullcontext()


class InitialUpdate(Enum):
    """What a `SharedPV` puts on the wire for a client's first get/monitor update.

    pvAccess transmits only the fields a `~p4p.Value` has *marked* as changed,
    and a PV's stored mask is the union of everything marked since `open()`.
    ``NTScalar(...).wrap(v)`` marks only ``value``, so a PV that is opened and
    never posted to serves a structure in which ``alarm.*``, ``display.*`` and
    ``valueAlarm.*`` never reach a client at all. A real IOC (QSRV) instead
    sends the complete structure and signals "unset" in-band.

    Clients which zero-fill what they did not receive (pvxs, p4p) hide the
    difference; the Java ``org.epics.pva`` client behind Phoebus/CS-Studio and
    the EPICS Archiver Appliance leaves an untransmitted string as ``null``.
    """

    DEFAULT = "default"
    """Defer to whatever serves this PV. The providers and server of
    `p4pillon.server.records` resolve this to `COMPLETE`; everywhere else it
    falls back to `AS_POSTED`."""

    COMPLETE = "complete"
    """The whole structure, as a real IOC does."""

    AS_POSTED = "as posted"
    """Only the fields marked since `open()` -- p4p's own behaviour."""


class Handler(_P4PHandler, ABC):
    """Skeleton of SharedPV Handler

    Use of this as a base class is optional.

    This is an alternative handler with added open(), post(), and close() to
    the set of functions implemented in p4p; put(), rpc(), onFirstConnect(),
    and onLastDisconnect() are inherited from `p4p.server.raw.Handler`.

    """

    def open(self, value):
        """
        Called each time an Open operation is performed on this Channel

        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).
        """

    def post(self, pv, value):
        """
        Called each time a post operation is performed on this Channel.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).
        """

    def close(self, pv):
        """
        Called when the Channel is closed.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        """


class HandlerHooksMixin:
    """Adds open()/post()/close() handler-callback support (p4p PR #172) to a
    `p4p.server.raw.SharedPV` subclass. Compose it *before* the flavor class
    in the MRO, so its overrides win::

        class SharedPV(HandlerHooksMixin, p4p.server.thread.SharedPV):
            pass

    Unlike put()/rpc(), which p4p dispatches onto the flavor's executor
    (work queue or event loop), the open()/post()/close() callbacks run
    synchronously on the calling thread: they mutate the wrapped
    `~p4p.Value` in place *before* it is handed to the C extension for
    storage, so they cannot be deferred past that hand-off.

    **Threading:** the two regimes could race over shared handler state, so
    ``_hook_lock`` (a per-PV `threading.RLock`) serializes them: open()/post()
    hold it across wrap -> handler hook -> store, and the thread flavor's
    ``_exec()`` runs every executor callable under it too. The lock is
    re-entrant, so a put handler may call ``pv.post()``. Each hook enters the
    lock through the `_hook_guard` seam, which a flavor may override to add
    its own policy -- the asyncio flavor layers an event-loop affinity check
    on top; see `p4pillon.server.asyncio.SharedPV`.

    Lock ordering: the PV lock is always acquired *before* any
    handler-internal lock (e.g. `~p4pillon.composite_handler.CompositeHandler`'s),
    so a handler must never call another PV's open()/post()/close() while
    holding its own lock.
    """

    # Attributes provided by the p4p.server.raw.SharedPV base this mixin is
    # always composed with.
    _handler: Any
    _wrap: Any
    _unwrap: Any

    def __init__(self, *args: Any, initial_update: InitialUpdate = InitialUpdate.DEFAULT, **kwargs: Any) -> None:
        """:param InitialUpdate initial_update: what to put on the wire for a
        client's first update; see `InitialUpdate`.
        """
        # The base __init__ calls self.open(initial), which acquires the lock
        # and reads _initial_update, so both must exist first.
        self._hook_lock = threading.RLock()
        self._initial_update = initial_update
        super().__init__(*args, **kwargs)

    def _hook_guard(self, what: str) -> AbstractContextManager[Any]:  # noqa: ARG002 - `what` is the subclass seam (see asyncio flavor)
        """Serialization guard the ``what`` hook ("open"/"post"/"close") runs
        under. The flavor seam: a subclass may add policy of its own here
        (e.g. the asyncio flavor's event-loop affinity check) instead of
        overriding each hook method."""
        return self._hook_lock

    def _wrap_or_raise(self, value: Any, **kwargs: Any) -> Value:
        """Apply ``self._wrap`` to ``value``, re-raising any failure as a ValueError."""
        try:
            return self._wrap(value, **kwargs)
        except Exception as exc:
            msg = f"Unable to wrap {value} with {self._wrap} and {kwargs}"
            raise ValueError(msg) from exc

    def open(self, value: Any, nt: Any = None, wrap: Any = None, unwrap: Any = None, **kwargs: Any) -> None:
        """Mark the PV as opened an provide its initial value.
        This initial value is later updated with post().

        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).

        Any clients which have begun connecting which began connecting while
        this PV was in the close'd state will complete connecting.

        Only those fields of the value which are marked as changed will be stored.
        """

        with self._hook_guard("open"):
            self._wrap = wrap or (nt and nt.wrap) or self._wrap
            self._unwrap = unwrap or (nt and nt.unwrap) or self._unwrap

            v = self._wrap_or_raise(value, **kwargs)

            # Handlers need not inherit from Handler, so a hook may be absent.
            open_fn = getattr(self._handler, "open", None)
            if open_fn is not None:
                open_fn(v)

            # After the hook, never before: marking first would make every
            # rule's is_applicable() see the whole structure as changed and
            # fire at open (see `p4pillon.rules.rules.BaseRule.is_applicable`).
            if self._initial_update is InitialUpdate.COMPLETE:
                mark_all(v)

            # Bypass p4p.server.raw.SharedPV.open(), which would wrap() v a
            # second time.
            _RawSharedPV.open(self, v)

    def post(self, value: Any, **kwargs: Any) -> None:
        """Provide an update to the Value of this PV.

        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).

        Only those fields of the value which are marked as changed will be stored.

        Any keyword arguments are forwarded to the NT wrap() method (if applicable).
        Common arguments include: timestamp= , severity= , and message= .
        """
        with self._hook_guard("post"):
            v = self._wrap_or_raise(value, **kwargs)

            post_fn = getattr(self._handler, "post", None)
            if post_fn is not None:
                post_fn(self, v)

            # Bypass p4p.server.raw.SharedPV.post(), which would wrap() v a
            # second time.
            _RawSharedPV.post(self, v)

    def _deferred_post(
        self,
        schedule: Callable[[Callable[[], None]], Any],
        value: Any,
        kwargs: dict[str, Any],
    ) -> Future[None]:
        """Shared machinery for both flavors' ``post_deferred``: build a
        single-shot callback that runs ``self.post(value, **kwargs)`` and routes
        its result (or exception) to a returned `~concurrent.futures.Future`,
        then hand that callback to ``schedule`` to run on the flavor's own
        executor (the thread flavor's work queue, the asyncio flavor's event
        loop). Each flavor supplies only ``schedule``, so the cancel/exception
        semantics live in one place and can't drift between the two.
        """
        fut: Future[None] = Future()

        def _post() -> None:
            if not fut.set_running_or_notify_cancel():
                return
            try:
                self.post(value, **kwargs)
            except BaseException as exc:
                fut.set_exception(exc)
                if not isinstance(exc, Exception):
                    raise
            else:
                fut.set_result(None)

        schedule(_post)
        return fut

    def close(self, destroy: bool = False, **kwargs: Any) -> Any:
        """Close PV, disconnecting any clients.
        :param bool destroy: Indicate "permanent" closure.  Current clients will not see
        subsequent open().
        close() with destroy=True or sync=True will not prevent clients from re-connecting.
        New clients may prevent sync=True from succeeding.
        Prevent reconnection by __first__ stopping the Server, removing with
        :py:meth:`StaticProvider.remove()`, or preventing a :py:class:`DynamicProvider`
        from making new channels to this SharedPV.

        Extra keyword arguments (e.g. the thread flavor's sync=/timeout=)
        and the return value are forwarded to/from the flavor class this
        mixin is composed with.
        """
        # The flavor close() stays outside the lock: the thread flavor's
        # close(sync=True) waits for the work queue, whose callables acquire
        # this lock -- holding it here would deadlock.
        with self._hook_guard("close"):
            close_fn = getattr(self._handler, "close", None)
            if close_fn is not None:
                close_fn(self)

        # super().close() resolves to the flavor class this mixin is
        # composed with, invisible to a static check of the mixin alone.
        return super().close(destroy, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]


class SharedPV(HandlerHooksMixin, _SharedPV):
    """Shared state Process Variable.  Callback based implementation.

    .. note:: if initial=None, the PV is initially **closed** and
              must be :py:meth:`open()`'d before any access is possible.

    :param handler: A object which will receive callbacks when eg. a Put operation is requested.
                    May be omitted if the decorator syntax is used.
    :param Value initial: An initial Value for this PV.  If omitted, :py:meth:`open()`s must be
                          called before client access is possible.
    :param nt: An object with methods wrap() and unwrap().  eg :py:class:`p4p.nt.NTScalar`.
    :param callable wrap: As an alternative to providing 'nt=', A callable to transform Values
                          passed to open() and post().
    :param callable unwrap: As an alternative to providing 'nt=', A callable to transform Values
                            returned Operations in Put/RPC handlers.
    :param dict options: A dictionary of configuration options.

    Creating a PV in the open state, with no handler for Put or RPC (attempts will error). ::

        from p4p.nt import NTScalar
        pv = SharedPV(nt=NTScalar('d'), value=0.0)
        # ... later
        pv.post(1.0)

    The full form of a handler object is: ::

        class MyHandler:
            def put(self, pv, op):
                pass
            def rpc(self, pv, op):
                pass
            def onFirstConnect(self): # may be omitted
                pass
            def onLastDisconnect(self): # may be omitted
                pass
    pv = SharedPV(MyHandler())

    Alternatively, decorators may be used. ::

        pv = SharedPV()
        @pv.put
        def onPut(pv, op):
            pass

    The nt= or wrap= and unwrap= arguments can be used as a convience to allow
    the open(), post(), and associated Operation.value() to be automatically
    transform to/from :py:class:`Value` and more convienent Python types.
    See :ref:`unwrap`
    """


def apply_initial_update(pv: _RawSharedPV, mode: InitialUpdate) -> None:
    """Resolve `pv`'s `~InitialUpdate.DEFAULT` to `mode`, retroactively if it is
    already open.

    The seam every "decided by whatever serves this PV" opt-in point calls, just
    before it starts serving `pv`. A PV constructed with an explicit
    `~InitialUpdate.COMPLETE` or `~InitialUpdate.AS_POSTED` keeps it -- the
    caller's choice outranks the server's -- and so is left untouched.

    Retroactive because `p4p.server.raw.SharedPV.__init__` calls
    ``self.open(initial)``: a PV built with ``initial=`` is already open, with
    its change mask already fixed, before any provider sees it. Setting the
    attribute alone would only take effect on a subsequent `open()`.

    Accepts a plain p4p `~p4p.server.raw.SharedPV` too; that just can't carry
    the setting across a `close()`/`open()`, since it has no `HandlerHooksMixin`
    `open()` to read it.
    """
    if mode is InitialUpdate.DEFAULT:
        return

    # None distinguishes "no HandlerHooksMixin, so no attribute to carry the
    # setting" from "has one, still on DEFAULT".
    current = getattr(pv, "_initial_update", None)
    if current is not None:
        if current is not InitialUpdate.DEFAULT:
            return  # explicitly set by the caller; not ours to override
        pv._initial_update = mode  # the attribute this seam exists to set

    if mode is not InitialUpdate.COMPLETE or not pv.isOpen():
        return

    # Deliberately bypasses the handlers: this corrects the wire format, it
    # does not change a value, so no rule should re-stamp it or re-evaluate an
    # alarm for it. _hook_lock rather than _hook_guard("post") -- the asyncio
    # flavor's guard asserts event-loop affinity, and a provider's add()
    # legitimately runs off-loop.
    with getattr(pv, "_hook_lock", None) or _NO_LOCK:
        _RawSharedPV.post(pv, mark_all(_RawSharedPV.current(pv)))
