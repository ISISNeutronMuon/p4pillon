"""
Patch in p4p PR #172 - support for open(), post(), and close() handler functions
"""

import logging

from p4p.server.raw import SharedPV as _SharedPV

_log = logging.getLogger(__name__)


class Handler:
    """Skeleton of SharedPV Handler

    Use of this as a base class is optional.

    This is an alternative handler with added open(), post(), and close() to the set of functions implemented in p4p.

    """

    def open(self, value):
        """
        Called each time an Open operation is performed on this Channel

        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).
        """
        pass

    def put(self, pv, op):
        """
        Called each time a client issues a Put
        operation on this Channel.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        :param ServerOperation op: The operation being initiated.
        """
        op.done(error="Not supported")

    def post(self, pv, value):
        """
        Called each time a client issues a post
        operation on this Channel.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).
        :param dict options: A dictionary of configuration options.
        """
        pass

    def rpc(self, pv, op):
        """
        Called each time a client issues a Remote Procedure Call
        operation on this Channel.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        :param ServerOperation op: The operation being initiated.
        """
        op.done(error="Not supported")

    def onFirstConnect(self, pv):
        """
        Called when the first Client channel is created.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        """
        pass

    def onLastDisconnect(self, pv):
        """
        Called when the last Client channel is closed.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        """
        pass

    def close(self, pv):
        """
        Called when the Channel is closed.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        """
        pass


class SharedPV(_SharedPV):
    """Shared state Process Variable.  Callback based implementation.

    .. note:: if initial=None, the PV is initially **closed** and
              must be :py:meth:`open()`'d before any access is possible.

    :param handler: A object which will receive callbacks when eg. a Put operation is requested.
                    May be omitted if the decorator syntax is used.
    :param Value initial: An initial Value for this PV.  If omitted, :py:meth:`open()`s must be called before client access is possible.
    :param nt: An object with methods wrap() and unwrap().  eg :py:class:`p4p.nt.NTScalar`.
    :param callable wrap: As an alternative to providing 'nt=', A callable to transform Values passed to open() and post().
    :param callable unwrap: As an alternative to providing 'nt=', A callable to transform Values returned Operations in Put/RPC handlers.
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

    def open(self, value, nt=None, wrap=None, unwrap=None, **kws):
        """Mark the PV as opened an provide its initial value.
        This initial value is later updated with post().

        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).

        Any clients which have begun connecting which began connecting while
        this PV was in the close'd state will complete connecting.

        Only those fields of the value which are marked as changed will be stored.
        """

        self._wrap = wrap or (nt and nt.wrap) or self._wrap
        self._unwrap = unwrap or (nt and nt.unwrap) or self._unwrap

        try:
            V = self._wrap(value, **kws)
        except Exception as exc:  # py3 will chain automatically, py2 won't
            raise ValueError(f"Unable to wrap {value} with {self._wrap} and {kws}") from exc

        # Guard goes here because we can have handlers that don't inherit from
        # the Handler base class
        try:
            open_fn = self._handler.open
        except AttributeError:
            pass
        else:
            open_fn(V)

        _SharedPV.open(self, V)

    def post(self, value, **kws):
        """Provide an update to the Value of this PV.

        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).

        Only those fields of the value which are marked as changed will be stored.

        Any keyword arguments are forwarded to the NT wrap() method (if applicable).
        Common arguments include: timestamp= , severity= , and message= .
        """
        try:
            V = self._wrap(value, **kws)
        except Exception as exc:  # py3 will chain automatically, py2 won't
            raise ValueError(f"Unable to wrap {value} with {self._wrap} and {kws}") from exc

        # Guard goes here because we can have handlers that don't inherit from
        # the Handler base class
        try:
            post_fn = self._handler.post
        except AttributeError:
            pass
        else:
            post_fn(self, V)

        _SharedPV.post(self, V)

    def close(self, destroy=False):
        """Close PV, disconnecting any clients.
        :param bool destroy: Indicate "permanent" closure.  Current clients will not see subsequent open().
        close() with destory=True or sync=True will not prevent clients from re-connecting.
        New clients may prevent sync=True from succeeding.
        Prevent reconnection by __first__ stopping the Server, removing with :py:meth:`StaticProvider.remove()`,
        or preventing a :py:class:`DynamicProvider` from making new channels to this SharedPV.
        """
        try:
            close_fn = self._handler.close
        except AttributeError:
            pass
        else:
            close_fn(self)

        _SharedPV.close(self)

    class _WrapHandler(_SharedPV._WrapHandler):  # pylint: disable=W0212
        "Wrapper around user Handler which logs exceptions"

        def open(self, value):
            _log.debug("OPEN %s %s", self._pv, value)
            try:
                self._pv._exec(None, self._real.open, value)
            except AttributeError:
                pass

        def post(self, value):
            _log.debug("POST %s %s", self._pv, value)
            try:
                self._pv._exec(None, self._real.post, self._pv, value)
            except AttributeError:
                pass

        def close(self):
            _log.debug("CLOSE %s", self._pv)
            try:
                self._pv._exec(None, self._real.close, self._pv)
            except AttributeError:
                pass
