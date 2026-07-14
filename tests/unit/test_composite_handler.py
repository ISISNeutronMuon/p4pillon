"""
Test p4pillon/handler.py
WARNING: AI generated code, replace with proper test cases.
"""

import unittest
from collections import OrderedDict
from unittest.mock import MagicMock

import pytest

from p4pillon.composite_handler import AbortHandlerError, CompositeHandler


class DummyHandler:
    def __init__(self):
        self.calls = []

    def open(self, value):
        self.calls.append(("open", value))

    def put(self, pv, op):
        self.calls.append(("put", pv, op))

    def post(self, pv, value):
        self.calls.append(("post", pv, value))

    def rpc(self, pv, op):
        self.calls.append(("rpc", pv, op))

    def onFirstConnect(self, pv):
        self.calls.append(("onFirstConnect", pv))

    def onLastDisconnect(self, pv):
        self.calls.append(("onLastDisconnect", pv))

    def close(self, pv):
        self.calls.append(("close", pv))


class DummyPV:
    def post(self, value):
        pass


class DummyOp:
    def __init__(self):
        self.done = MagicMock()

    def value(self):
        return None


class DummyValue:
    pass


class TestCompositeHandler(unittest.TestCase):
    def setUp(self):
        self.h1 = DummyHandler()
        self.h2 = DummyHandler()
        self.handlers = OrderedDict([("h1", self.h1), ("h2", self.h2)])
        self.comp = CompositeHandler(self.handlers)
        self.pv = DummyPV()
        self.op = DummyOp()
        self.value = DummyValue()

    def test_init_no_handlers(self):
        comp = CompositeHandler()
        with pytest.raises(KeyError):
            comp["any"]

    def test_getitem_valid(self):
        assert self.comp["h1"] is self.h1
        assert self.comp["h2"] is self.h2

    def test_getitem_invalid(self):
        with pytest.raises(KeyError):
            _ = self.comp["missing"]

    def test_open_calls_all(self):
        self.comp.open(self.value)
        assert self.h1.calls[0] == ("open", self.value)
        assert self.h2.calls[0] == ("open", self.value)

    def test_open_no_handlers(self):
        comp = CompositeHandler()
        comp.open(self.value)  # Should not raise

    def test_put_calls_all(self):
        self.comp.put(self.pv, self.op)
        assert self.h1.calls[0][0] == "put"
        assert self.h2.calls[0][0] == "put"
        self.op.done.assert_called_once_with()

    def test_put_abort_exception(self):
        def abort_put(_pv, _op):
            raise AbortHandlerError("abort!")  # noqa: EM101 - fixed message asserted on below

        self.h1.put = abort_put
        self.comp.put(self.pv, self.op)
        self.op.done.assert_called_once_with(error="abort!")
        # h2 should not be called
        assert len(self.h2.calls) == 0

    def test_post_calls_all(self):
        self.comp.post(self.pv, self.value)
        assert self.h1.calls[0] == ("post", self.pv, self.value)
        assert self.h2.calls[0] == ("post", self.pv, self.value)

    def test_post_no_handlers(self):
        comp = CompositeHandler()
        comp.post(self.pv, self.value)  # Should not raise

    def test_rpc_calls_all(self):
        self.comp.rpc(self.pv, self.op)
        assert self.h1.calls[0][0] == "rpc"
        assert self.h2.calls[0][0] == "rpc"
        self.op.done.assert_called_once_with(error=None)

    def test_rpc_abort_exception(self):
        def abort_rpc(_pv, _op):
            raise AbortHandlerError("rpc abort!")  # noqa: EM101, TRY003 - fixed message asserted on below

        self.h2.rpc = abort_rpc
        self.comp.rpc(self.pv, self.op)
        self.op.done.assert_called_once_with(error="rpc abort!")
        # h2 should be called, but not after abort
        assert self.h2.calls == []

    def test_on_first_connect_calls_all(self):
        self.comp.on_first_connect(self.pv)
        assert self.h1.calls[0] == ("onFirstConnect", self.pv)
        assert self.h2.calls[0] == ("onFirstConnect", self.pv)

    def test_on_first_connect_no_handlers(self):
        comp = CompositeHandler()
        comp.on_first_connect(self.pv)  # Should not raise

    def test_on_first_connect_camel_case_deprecated(self):
        self.comp.onFirstConnect(self.pv)
        assert self.h1.calls[0] == ("onFirstConnect", self.pv)

    def test_on_last_disconnect_calls_all(self):
        self.comp.on_last_disconnect(self.pv)
        assert self.h1.calls[0] == ("onLastDisconnect", self.pv)
        assert self.h2.calls[0] == ("onLastDisconnect", self.pv)

    def test_on_last_disconnect_no_handlers(self):
        comp = CompositeHandler()
        comp.on_last_disconnect(self.pv)  # Should not raise

    def test_on_last_disconnect_camel_case_deprecated(self):
        self.comp.onLastDisconnect(self.pv)
        assert self.h1.calls[0] == ("onLastDisconnect", self.pv)

    def test_close_calls_all(self):
        self.comp.close(self.pv)
        assert self.h1.calls[0] == ("close", self.pv)
        assert self.h2.calls[0] == ("close", self.pv)

    def test_close_no_handlers(self):
        comp = CompositeHandler()
        comp.close(self.pv)  # Should not raise


if __name__ == "__main__":
    unittest.main()
