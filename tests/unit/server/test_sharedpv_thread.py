from p4p.nt import NTScalar

from p4pillon.server.thread import Handler, SharedPV


class TestThreadHandler:
    """
    Test Handler open(), post() and close() functions called correctly by SharedPV. Note that:
    - TestRPC, TestFirstLast already test onFirstConnect() and onLastDisconnect().
    - TestGPM, TestPVRequestMask already test put().
    - TestRPC, TestRPC2 already test rpc().
    """

    class HandlerTest(Handler):
        def __init__(self):
            self.last_op = "init"

        def open(self, value):
            self.last_op = "open"
            value["value"] = 17

        def post(self, pv, value):
            self.last_op = "post"
            value["value"] = value["value"] * 2

        def close(self, pv):
            self.last_op = "close"

    def setup_method(self, _method):
        self.handler = self.HandlerTest()
        self.pv = SharedPV(handler=self.handler, nt=NTScalar("d"))

    def test_open(self):
        # Setup sets the initial value to 5, but the Handler open() overrides
        self.pv.open(5)
        assert self.handler.last_op == "open"
        assert self.pv.current() == 17.0

    def test_post(self):
        self.pv.open(5)
        self.pv.post(13.0)
        assert self.handler.last_op == "post"
        assert self.pv.current() == 26.0

    def test_close(self):
        self.pv.open(5)
        self.pv.close(sync=True)
        assert self.handler.last_op == "close"

    def teardown_method(self, _method):
        self.pv.close()
        del self.handler
        del self.pv
