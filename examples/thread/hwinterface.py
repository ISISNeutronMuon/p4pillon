"""
A simple example of using the SharedNT class to setup a set and readback from
"simulated" hardware.
"""

import random
from collections import OrderedDict
from time import sleep

from p4p import Value
from p4p.nt import NTScalar
from p4p.server import Server, ServerOperation

from p4pillon.nthandlers import Handler
from p4pillon.thread.sharednt import SharedNT


class SimulatedHardware:
    """
    Our simulated hardware is simple a gaussian random number generator
    where we change the mean value.
    """

    def __init__(self, value=0.0):
        self.value = value

    def poll(self):
        """
        Return a different random value each time the "hardware" is polled.
        """
        return self.value + random.gauss(0, 2.0)


class UserReportHandler(Handler):
    """
    Simply prints the user account attempting to perform a put operation.
    """

    def put(self, pv: SharedNT, op: ServerOperation):
        print(f"Operation attempted by user {op.account()} on pv {op.name()}")


class HWWriteHandler(Handler):
    """
    An example of a handler that would write to hardware.
    Note that it is important that this be the last handler in the chain, otherwise
    important functionality like control limits will not be applied.
    TODO: This should actually be the second last handler, the timestamp handler
          ought to be last, but the current design does not allow that.
    """

    def __init__(self, hardware: SimulatedHardware):
        self.hardware = hardware

    def post(self, pv: SharedNT, value: Value):
        if value.changed("value"):
            self.hardware.value = value["value"]

    def put(self, pv: SharedNT, op: ServerOperation):
        pass


def main():
    """
    Construct the Normative Type PVs, start the server, and update the hardware
    readback every 0.5 seconds.
    """

    hw = SimulatedHardware(4.5)  # Set initial value of simulated hardware

    # Create a SharedNT for readback from the hardware and another for the setpoint.
    # The readback is read-only, the setpoint is writable.
    # The readback is set to trigger an alarm if its value is over 17.
    # The setpoint is limited to a maximum value of 25.
    pv_hwget = SharedNT(
        nt=NTScalar(
            "d",
            valueAlarm=True,
        ),
        initial={
            "value": hw.poll(),
            "valueAlarm.active": True,
            "valueAlarm.highAlarmLimit": 17,
            "valueAlarm.highAlarmSeverity": 2,  # Not obvious, but without this the highAlarmLimit above will not work
        },
    )
    pv_hwget.handler.read_only = True  # Make the readback read-only

    pv_hwset = SharedNT(
        nt=NTScalar(
            "d",
            control=True,
        ),  # scalar double
        initial={"value": hw.poll(), "control.limitHigh": 25},
        auth_handlers=OrderedDict({"spy": UserReportHandler()}),
        user_handlers=OrderedDict({"hwwrite": HWWriteHandler(hw)}),
    )

    pvs = {
        "demo:hw_set": pv_hwset,  # PV name only appears here
        "demo:hw_get": pv_hwget,  # PV name only appears here
    }

    with Server(
        providers=[pvs],
    ):
        print("Server starting. Press Ctrl+C (or equivalent) to stop.")
        print("Server is providing PVs: ")
        for pv_name, pv in pvs.items():
            print(f"  {pv_name} with handlers {list(pv.handler.keys())}")

        try:
            while True:
                pv_hwget.post({"value": hw.poll()})
                sleep(0.5)

        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
