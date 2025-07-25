"""
Wrapper to SharedPV in p4p to automatically create
"""

import logging

from p4p.nt import NTBase, NTEnum, NTScalar
from p4p.server.thread import SharedPV

from p4p_ext.nthandlers import NTEnumRulesHandler, NTScalarRulesHandler

logger = logging.getLogger(__name__)


class SharedNT(SharedPV):
    """
    SharedNT is a wrapper around SharedPV that automatically adds handler
    functionality to support Normative Type logic.
    """

    def __init__(self, queue=None, **kws):
        # Check if there is a handler specified in the kws, and if not override it
        # with an NT handler.
        # TODO: What if the user supplies their own handler?

        if "nt" in kws:
            if "handler" in kws:
                raise NotImplementedError(
                    "SharedNT does not support custom handlers. Use SharedPV directly if you need a custom handler."
                )

            nt: NTBase = kws["nt"]
            if isinstance(nt, NTScalar):
                kws["handler"] = NTScalarRulesHandler()
            if isinstance(nt, NTEnum):
                kws["handler"] = NTEnumRulesHandler()

        super().__init__(queue=queue, **kws)

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
