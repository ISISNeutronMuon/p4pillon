"""
Wrapper to SharedPV in p4p to automatically create
"""
from __future__ import annotations

import logging
from collections import OrderedDict

from p4p.nt import NTBase, NTEnum, NTScalar
from p4p.server.raw import Handler
from p4p.server.thread import SharedPV

from p4p_ext.composite_handler import CompositeHandler
from p4p_ext.nthandlers import NTEnumRulesHandler, NTScalarRulesHandler

logger = logging.getLogger(__name__)


class SharedNT(SharedPV):
    """
    SharedNT is a wrapper around SharedPV that automatically adds handler
    functionality to support Normative Type logic.
    """

    def __init__(
        self,
        pre_nthandlers: OrderedDict[str, Handler] | None = None,
        post_nthandlers: OrderedDict[str, Handler] | None = None,
        **kws,
    ):
        # Check if there is a handler specified in the kws, and if not override it
        # with an NT handler.

        # Create a CompositeHandler. If there is no user supplied handler, and this is not
        # an NT type then it won't do anything. But it will still represent a stable interface

        if pre_nthandlers:
            self.handlers = CompositeHandler(pre_nthandlers)
        else:
            self.handlers = CompositeHandler()

        if "nt" in kws:
            nt: NTBase = kws["nt"]
            if isinstance(nt, NTScalar):
                self.handlers["NTScalar"] = NTScalarRulesHandler()
            if isinstance(nt, NTEnum):
                self.handlers["NTEnum"] = NTEnumRulesHandler()

        if post_nthandlers:
            self.handlers = self.handlers | post_nthandlers

        kws["handler"] = self.handlers

        super().__init__(**kws)

    ## Disable handler decorators until we have a solid design.
    # Re-enable when / if possible

    @property
    def onFirstConnect(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def onLastDisconnect(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def on_open(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def on_post(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def put(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def rpc(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def on_close(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    ## Alternative PEP 8 comaptible handler decorators
    # @property
    # def on_first_connect(self):
    #     """Turn a function into an ISISHandler onFirstConnect() method."""

    #     def decorate(fn):
    #         self._handler.onFirstConnect = fn
    #         return fn

    #     return decorate

    # @property
    # def on_last_disconnect(self):
    #     """Turn a function into an ISISHandler onLastDisconnect() method."""

    #     def decorate(fn):
    #         self._handler.onLastDisconnect = fn
    #         return fn

    #     return decorate

    # @property
    # def on_put(self):
    #     """Turn a function into an ISISHandler put() method."""

    #     def decorate(fn):
    #         self._handler.put = fn
    #         return fn

    #     return decorate

    # @property
    # def on_rpc(self):
    #     """Turn a function into an ISISHandler rpc() method."""

    #     def decorate(fn):
    #         self._handler.rpc = fn
    #         return fn

    #     return decorate

    # @property
    # def on_post(self):
    #     """Turn a function into an ISISHandler post() method."""

    #     def decorate(fn):
    #         self._handler.post = fn
    #         return fn

    #     return decorate
