"""
Required to allow post operations trigger handler rules
"""

import logging
from collections.abc import Callable

from p4p import Value
from p4p.server.raw import _SharedPV
from p4p.server.thread import Handler, SharedPV

# from p4p_for_isis.server import ISISServer

logger = logging.getLogger(__name__)


class ISISHandler(Handler):
    """The ISISHandler added open(), post(), and close() methods to the p4p Handler class."""

    def open(self, value, **kws):
        """
        Called each time an Open operation is performed on this Channel

        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).
        """

    def post(self, pv: "ISISPV", value: Value, **kws):
        """
        Called each time a client issues a post
        operation on this Channel.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).
        :param dict options: A dictionary of configuration options.
        """

    def close(self, pv):
        """
        Called when the Channel is closed.

        :param SharedPV pv: The :py:class:`SharedPV` which this Handler is associated with.
        """


class ISISPV(SharedPV):
    """Implementation that applies specified rules to post operations"""

    def __init__(self, **kws):
        super().__init__(**kws)
        self.on_start_methods: list[Callable] = []

    def set_start_methods(self, method: Callable) -> None:
        """
        Add method to the list of methods to be called when an ISISServer containing this pv is started
        """
        self.on_start_methods.append(method)

    def on_server_start(self, server) -> None:
        """
        This method is called by the ISISServer when the server is started and can be used for any initialisation that
        needs to be done after all pvs for the server have been created.
        This is primarily used to do things like identify which pvs are local for pvs that include forward links or
        for calc pvs by adding the appropriate method using set_start_methods().
        """

        for method in self.on_start_methods:
            method(server)

    @property
    def handler(self) -> ISISHandler:
        """Access to handler of this PV"""
        return self._handler

    @handler.setter
    def handler(self, newhandler: ISISHandler) -> None:
        self._handler = newhandler

    def open(self, value, nt=None, wrap=None, unwrap=None, **kws) -> None:
        """Mark the PV as opened and provide its initial value.
        This initial value is later updated with post().

        :param value:  A Value, or appropriate object (see nt= and wrap= of the constructor).

        Any clients which have begun connecting which began connecting while
        this PV was in the close'd state will complete connecting.

        Only those fields of the value which are marked as changed will be stored.
        """

        self._wrap = wrap or (nt and nt.wrap) or self._wrap
        self._unwrap = unwrap or (nt and nt.unwrap) or self._unwrap

        # Intercept all arguments that start with 'handler_open_' and remove them from
        # the arguments that go to the wrap and send them instead to the handler.open()
        post_kws = {x: kws.pop(x) for x in [y for y in kws if y.startswith("handler_open_")]}

        try:
            wrapped_value = self._wrap(value, **kws)
        except Exception as err:  # py3 will chain automatically, py2 won't
            raise ValueError(f"Unable to wrap {value} with {self._wrap} and {kws}") from err

        # Guard goes here because we can have handlers that don't inherit from
        # the Handler base class
        try:
            self._handler.open(wrapped_value, **post_kws)
        except AttributeError:
            pass

        _SharedPV.open(self, wrapped_value)

    def post(self, value, **kws) -> None:
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
            wrapped_value: Value = self._wrap(value, **kws)
        except Exception as err:
            raise ValueError(f"Unable to wrap {value} with {self._wrap} and {kws}") from err

        # Guard goes here because we can have handlers that don't inherit from
        # the Handler base class
        try:
            self._handler.post(self, wrapped_value, **post_kws)
        except AttributeError:
            pass

        _SharedPV.post(self, wrapped_value)

    def close(self, destroy=False, sync=False, timeout=None) -> None:
        """Close PV, disconnecting any clients.

        :param bool destroy: Indicate "permanent" closure.  Current clients will not see subsequent open().
        :param bool sync: When block until any pending onLastDisconnect() is delivered (timeout applies).
        :param float timeout: Applies only when sync=True.  None for no timeout, otherwise a non-negative
            floating point value.

        close() with destroy=True or sync=True will not prevent clients from re-connecting.
        New clients may prevent sync=True from succeeding.
        Prevent reconnection by __first__ stopping the Server, removing with :py:meth:`StaticProvider.remove()`,
        or preventing a :py:class:`DynamicProvider` from making new channels to this SharedPV.
        """
        try:
            self._handler.close(self)
        except AttributeError:
            pass

        _SharedPV.close(self)

    class _WrapHandler(SharedPV._WrapHandler):  # pylint: disable=protected-access
        "Wrapper around user Handler which logs exceptions"

        def post(self, value: Value, **kws) -> None:
            """Call the user handler's post() method, potentially logging this."""
            logger.debug("POST %s %s", self._pv, value)
            try:
                self._pv._exec(None, self._real.post, self._pv, value, **kws)  # pylint: disable=protected-access
            except AttributeError:
                pass

    @property
    def on_first_connect(self):
        """Turn a function into an ISISHandler onFirstConnect() method."""

        def decorate(fn):
            self._handler.onFirstConnect = fn
            return fn

        return decorate

    @property
    def on_last_disconnect(self):
        """Turn a function into an ISISHandler onLastDisconnect() method."""

        def decorate(fn):
            self._handler.onLastDisconnect = fn
            return fn

        return decorate

    @property
    def on_put(self):
        """Turn a function into an ISISHandler put() method."""

        def decorate(fn):
            self._handler.put = fn
            return fn

        return decorate

    @property
    def on_rpc(self):
        """Turn a function into an ISISHandler rpc() method."""

        def decorate(fn):
            self._handler.rpc = fn
            return fn

        return decorate

    @property
    def on_post(self):
        """Turn a function into an ISISHandler post() method."""

        def decorate(fn):
            self._handler.post = fn
            return fn

        return decorate
