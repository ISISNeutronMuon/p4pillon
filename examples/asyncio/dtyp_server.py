"""Demo server for `p4pillon.server.records`, which serves per-field "sub-PVs" for
DTYP, RTYP, NAME, and the fields common to every EPICS record -- see that
module's docstring for the full rationale.

Uses `IOCChannelProvider`, the primary/recommended way to use this: every
"<name>.<FIELD>" sub-PV is built and registered up front, when `add()` is
called, automatically matching the flavor of the base PV passed to it --
the asyncio `SharedPV` imported below, in this example.

in another terminal use
 `python -m p4p.client.cli get EXAMPLE:PV`
 `python -m p4p.client.cli get EXAMPLE:PV.DTYP`
 `python -m p4p.client.cli get EXAMPLE:PV.RTYP`
 `python -m p4p.client.cli get EXAMPLE:PV.NAME`
 `python -m p4p.client.cli get EXAMPLE:PV.SCAN`
 `python -m p4p.client.cli get EXAMPLE:PV.DESC`
"""

import asyncio

from p4p.nt import NTScalar
from p4p.server import Server

from p4pillon.server.asyncio import SharedPV
from p4pillon.server.records import FIELD_NAMES, IOCChannelProvider


async def main():
    base = IOCChannelProvider("base")
    base.add("EXAMPLE:PV",
              SharedPV(nt=NTScalar('d', display=True),
                       initial={"value": 1.234,
                                "display": {"description": "An example ai-like record"}}),
              dtyp_choices=["Soft Channel", "Raw Soft Channel"],
              fields={"SCAN": "1 second"})
    base.add("EXAMPLE:PV2", SharedPV(nt=NTScalar('i'), initial=0))

    with Server(providers=[base]):
        print("Serving:", list(base.keys()))
        print("Also serving <PV>.<FIELD> for FIELD in:", ", ".join(sorted(FIELD_NAMES)))
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    asyncio.run(main())
