"""
Required to allow post operations trigger handler rules
"""

import logging

from p4p import Value
from p4p.server import ServerOperation
from p4p.server.raw import Handler, ServOpWrap, SharedPV, _SharedPV

logger = logging.getLogger(__name__)


class ISISPV(SharedPV):
    """Implementation that applies specified rules to post operations"""

    @property
    def handler(self) -> Handler:
        """Access to handler of this PV"""
        return self._handler

    @handler.setter
    def handler(self, newhandler: Handler):
        self._handler = newhandler

    def post(self, value, **kws):
        """Provide an update to the Value of this PV.

        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).

        Only those fields of the value which are marked as changed will be stored.

        Any keyword arguments are forwarded to the NT wrap() method (if applicable).
        Common arguments include: timestamp= , severity= , and message= .
        """
        # Intercept all arguments that start with 'handler_post_' and remove them from
        # the arguments that go to the wrap and send them instead to the handler.post()
        post_kws = {x: kws.pop(x) for x in [y for y in kws if y.startswith("handler_post_")]}

        try:
            V: Value = self._wrap(value, **kws)
        except Exception as err:
            raise ValueError(f"Unable to wrap {value} with {self._wrap} and {kws}") from err

        # Guard goes here because we can have handlers that don't inherit from
        # the Handler base class
        try:
            self._handler.post(self, V, **post_kws)
        except AttributeError:
            pass

        _SharedPV.post(self, V)

    class _WrapHandler:
        "Wrapper around user Handler which logs exceptions"

        def __init__(self, pv: "ISISPV", real):
            self._pv = pv  # this creates a reference cycle, which should be collectable since SharedPV supports GC
            self._real = real

        def onFirstConnect(self):
            logger.debug("ONFIRSTCONNECT %s", self._pv)
            self._pv._exec(None, self._pv._onFirstConnect, None)
            try:  # user handler may omit onFirstConnect()
                M = self._real.onFirstConnect
            except AttributeError:
                return
            self._pv._exec(None, M, self._pv)

        def onLastDisconnect(self):
            logger.debug("ONLASTDISCONNECT %s", self._pv)
            try:
                M = self._real.onLastDisconnect
            except AttributeError:
                pass
            else:
                self._pv._exec(None, M, self._pv)
            self._pv._exec(None, self._pv._onLastDisconnect, None)

        def put(self, op: ServerOperation):
            logger.debug("PUT %s %s", self._pv, op)
            try:
                self._pv._exec(op, self._real.put, self._pv, ServOpWrap(op, self._pv._wrap, self._pv._unwrap))
            except AttributeError:
                op.done(error="Put not supported")

        def rpc(self, op: ServerOperation):
            logger.debug("RPC %s %s", self._pv, op)
            try:
                self._pv._exec(op, self._real.rpc, self._pv, op)
            except AttributeError:
                op.done(error="RPC not supported")

        def post(self, value: Value, **kws):
            logger.debug("POST %s %s", self._pv, value)
            try:
                self._pv._exec(None, self._real.rpc, self._pv, value, **kws)
            except AttributeError:
                pass

    @property
    def on_first_connect(self):
        def decorate(fn):
            self._handler.onFirstConnect = fn
            return fn

        return decorate

    @property
    def on_last_disconnect(self):
        def decorate(fn):
            self._handler.onLastDisconnect = fn
            return fn

        return decorate

    @property
    def on_put(self):
        def decorate(fn):
            self._handler.put = fn
            return fn

        return decorate

    @property
    def on_rpc(self):
        def decorate(fn):
            self._handler.rpc = fn
            return fn

        return decorate

    @property
    def on_post(self):
        def decorate(fn):
            self._handler.post = fn
            return fn

        return decorate

    # Aliases for decorators to maintain consistent new style
    # Required because post is already used and on_post seemed the best
    # alternative.
    put = on_put
    rpc = on_rpc
    onFirstConnect = on_first_connect
    onLastDisconnect = on_last_disconnect
