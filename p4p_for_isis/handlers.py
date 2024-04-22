import time

from p4p import Value
from p4p.server import ServerOperation
from p4p.server.thread import Handler, SharedPV

from .utils import time_in_seconds_and_nanoseconds


class BaseHandler(Handler):
    def __init__(self) -> None:
        super().__init__()

    def _update_timestamp(self, value: Value) -> Value:
        if not value.changed("timeStamp"):
            seconds, nanoseconds = time_in_seconds_and_nanoseconds(time.time())
            value.timeStamp = {"secondsPastEpoch": seconds, "nanoseconds": nanoseconds}
        return value


class RWHandler(BaseHandler):
    """A handler that allows two methods of changing the value of a PV"""

    def put(self, pv_: SharedPV, op: ServerOperation):
        """This callback is run whenever you do `ctx.put` on the PV"""
        print("RW handler")
        value = self._update_timestamp(op.value())
        pv_.post(value)
        op.done()
