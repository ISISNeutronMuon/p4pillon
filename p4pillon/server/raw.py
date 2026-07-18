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
from contextlib import AbstractContextManager
from typing import Any

from p4p import Value
from p4p._p4p import SharedPV as _RawSharedPV
from p4p.server.raw import Handler as _P4PHandler
from p4p.server.raw import SharedPV as _SharedPV

__all__ = ("Handler", "HandlerHooksMixin", "SharedPV")


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
        pass

    def post(self, pv, value):
        """
        Called each time a post operation is performed on this Channel.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).
        """
        pass

    def close(self, pv):
        """
        Called when the Channel is closed.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        """
        pass


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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # The base __init__ calls self.open(initial), which acquires the
        # lock, so it must exist first.
        self._hook_lock = threading.RLock()
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
