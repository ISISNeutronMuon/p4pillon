import time

from p4p import Value
from p4p.server import ServerOperation
from p4p.server.thread import Handler, SharedPV

from .utils import time_in_seconds_and_nanoseconds


class ROHandler(Handler):
    def __init__(self) -> None:
        super().__init__()

    def put(self, pv_: SharedPV, op: ServerOperation):
        """This callback is run whenever you do `ctx.put` on the PV"""
        print(f"{op.name()} is read-only from a client perspective. Values can only be changed from within the server.")
        op.done()


class RWHandler(Handler):
    """Example handler for processing updates to PVs"""

    def __init__(self) -> None:
        super().__init__()

    def _update_timestamp(self, value: Value) -> Value:
        if not value.changed("timeStamp"):
            seconds, nanoseconds = time_in_seconds_and_nanoseconds(time.time())
            value.timeStamp = {"secondsPastEpoch": seconds, "nanoseconds": nanoseconds}
        return value

    def process_update(self, value: Value) -> Value:
        value = self._update_timestamp(value)
        return value

    def put(self, pv_: SharedPV, op: ServerOperation):
        """This callback is run whenever you do `ctx.put` on the PV"""
        # NOTE op.peer() and op.account() can be used to get access to IP address
        # and account owner of the client request
        pv_, op = self.on_put(pv_, op)
        pv_.post(op.value())
        op.done()

    def on_put(self, pv_: SharedPV, op: ServerOperation):
        return pv_, op
