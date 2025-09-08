"""
Test p4pillon/handler.py
WARNING: AI generated code, replace with proper test cases.
"""

import unittest
from collections import OrderedDict
from unittest.mock import MagicMock

from p4pillon.composite_handler import AbortHandlerException, CompositeHandler


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
        with self.assertRaises(KeyError):
            comp["any"]

    def test_getitem_valid(self):
        self.assertIs(self.comp["h1"], self.h1)
        self.assertIs(self.comp["h2"], self.h2)

    def test_getitem_invalid(self):
        with self.assertRaises(KeyError):
            _ = self.comp["missing"]

    def test_open_calls_all(self):
        self.comp.open(self.value)
        self.assertEqual(self.h1.calls[0], ("open", self.value))
        self.assertEqual(self.h2.calls[0], ("open", self.value))

    def test_open_no_handlers(self):
        comp = CompositeHandler()
        comp.open(self.value)  # Should not raise

    def test_put_calls_all(self):
        self.comp.put(self.pv, self.op)
        self.assertEqual(self.h1.calls[0][0], "put")
        self.assertEqual(self.h2.calls[0][0], "put")
        self.op.done.assert_called_once_with()

    def test_put_abort_exception(self):
        def abort_put(pv, op):
            raise AbortHandlerException("abort!")

        self.h1.put = abort_put
        self.comp.put(self.pv, self.op)
        self.op.done.assert_called_once_with(error="abort!")
        # h2 should not be called
        self.assertEqual(len(self.h2.calls), 0)

    def test_post_calls_all(self):
        self.comp.post(self.pv, self.value)
        self.assertEqual(self.h1.calls[0], ("post", self.pv, self.value))
        self.assertEqual(self.h2.calls[0], ("post", self.pv, self.value))

    def test_post_no_handlers(self):
        comp = CompositeHandler()
        comp.post(self.pv, self.value)  # Should not raise

    def test_rpc_calls_all(self):
        self.comp.rpc(self.pv, self.op)
        self.assertEqual(self.h1.calls[0][0], "rpc")
        self.assertEqual(self.h2.calls[0][0], "rpc")
        self.op.done.assert_called_once_with(error=None)

    def test_rpc_abort_exception(self):
        def abort_rpc(pv, op):
            raise AbortHandlerException("rpc abort!")

        self.h2.rpc = abort_rpc
        self.comp.rpc(self.pv, self.op)
        self.op.done.assert_called_once_with(error="rpc abort!")
        # h2 should be called, but not after abort
        self.assertEqual(self.h2.calls, [])

    def test_on_first_connect_calls_all(self):
        self.comp.on_first_connect(self.pv)
        self.assertEqual(self.h1.calls[0], ("onFirstConnect", self.pv))
        self.assertEqual(self.h2.calls[0], ("onFirstConnect", self.pv))

    def test_on_first_connect_no_handlers(self):
        comp = CompositeHandler()
        comp.on_first_connect(self.pv)  # Should not raise

    def test_onFirstConnect_deprecated(self):
        self.comp.onFirstConnect(self.pv)
        self.assertEqual(self.h1.calls[0], ("onFirstConnect", self.pv))

    def test_on_last_connect_calls_all(self):
        self.comp.on_last_connect(self.pv)
        self.assertEqual(self.h1.calls[0], ("onFirstConnect", self.pv))
        self.assertEqual(self.h2.calls[0], ("onFirstConnect", self.pv))

    def test_on_last_connect_no_handlers(self):
        comp = CompositeHandler()
        comp.on_last_connect(self.pv)  # Should not raise

    def test_onLastDisconnect_deprecated(self):
        self.comp.onLastDisconnect(self.pv)
        self.assertEqual(self.h1.calls[0], ("onFirstConnect", self.pv))

    def test_close_calls_all(self):
        self.comp.close(self.pv)
        self.assertEqual(self.h1.calls[0], ("close", self.pv))
        self.assertEqual(self.h2.calls[0], ("close", self.pv))

    def test_close_no_handlers(self):
        comp = CompositeHandler()
        comp.close(self.pv)  # Should not raise


if __name__ == "__main__":
    unittest.main()
