"""Demo server for `p4pillon.server.records`, which serves per-field "sub-PVs" for
DTYP, RTYP, NAME, and the fields common to every EPICS record -- see that
module's docstring for the full rationale.

Uses `IOCRecordServer`, which builds "<name>.<FIELD>" sub-PVs for free for
any base PV in a providers=[] entry -- either an explicit `IOCRecordProvider`
(needed for per-PV overrides, as for EXAMPLE:PV's dtyp_choices/fields below;
passed directly below, same as any other provider -- `IOCRecordServer`
unpacks it internally even though it isn't itself a single provider), or,
for the common case needing no overrides, a plain {name: pv} dict,
same as any ordinary p4p server (see EXAMPLE:PV2 below). Every sub-PV is built
lazily, on first client connection, as a plain thread-flavored SharedPV --
regardless of the base PV's own flavor (the asyncio `SharedPV` imported below,
in this example) -- and, unlike `StaticRecordProvider`'s eager sub-PVs, won't show
up in a plain channel-list query (e.g. the `pvlist` tool); only the base PVs
will. See `IOCRecordProvider`'s docstring for the full set of tradeoffs
against the eager path.

in another terminal use
 `python -m p4p.client.cli get EXAMPLE:PV`
 `python -m p4p.client.cli get EXAMPLE:PV.DTYP`
 `python -m p4p.client.cli get EXAMPLE:PV.RTYP`
 `python -m p4p.client.cli get EXAMPLE:PV.NAME`
 `python -m p4p.client.cli get EXAMPLE:PV.SCAN`
 `python -m p4p.client.cli get EXAMPLE:PV.DESC`
 `python -m p4p.client.cli get EXAMPLE:PV2`
 `python -m p4p.client.cli get EXAMPLE:PV2.RTYP`
"""

import asyncio

from p4p.nt import NTScalar

from p4pillon.server.asyncio import SharedPV
from p4pillon.server.records import FIELD_NAMES, IOCRecordProvider, IOCRecordServer


async def main():
    base = IOCRecordProvider("base")
    base.add(
        "EXAMPLE:PV",
        SharedPV(
            nt=NTScalar("d", display=True),
            initial={"value": 1.234, "display": {"description": "An example ai-like record"}},
        ),
        dtyp_choices=["Soft Channel", "Raw Soft Channel"],
        fields={"SCAN": "1 second"},
    )
    pvs = {"EXAMPLE:PV2": SharedPV(nt=NTScalar("i"), initial=0)}

    with IOCRecordServer(providers=[base, pvs]):
        print("Serving:", list(base.providers[0].keys()) + list(pvs.keys()))
        print("Also serving <PV>.<FIELD> for FIELD in:", ", ".join(sorted(FIELD_NAMES)))
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    asyncio.run(main())
