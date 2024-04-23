from typing import Dict, List

from p4p.server import Server, StaticProvider

from .pvs import BasePV
from .utils import validate_pv_name


class ISISServer:
    def __init__(self, prefix="") -> None:
        self.prefix = prefix
        self._provider = StaticProvider()
        self._server = None
        self._pvs = {}

    def start(self):
        # iterate over all the PVs and initialise them if they haven't
        # been already
        # then add them to the provider
        # then start the server
        for pv_name, pv in self._pvs.items():
            pv.initialise()
            self._provider.add(pv_name, pv)

        self._server = Server(providers=[self._provider])
        print(f"Started Server with {self.pvlist}")

    def stop(self):
        # iterate over all the PVs and close them before removing them
        # from the provider and closing the server
        for pv_name, pv in self._pvs.items():
            pv.close()
            self._provider.remove(pv_name)
        self._server.stop()
        print("\nStopped server")

    def addPV(self, pv_name: str, pv_object: BasePV):
        if not pv_name.startswith(self.prefix):
            pv_name = self.prefix + pv_name
        pv_name = validate_pv_name(pv_name)
        self._pvs[pv_name] = pv_object

    def removePV(self, pv_name: str):
        if not pv_name.startswith(self.prefix):
            pv_name = self.prefix + pv_name
        del self._pvs[pv_name]

    @property
    def pvlist(self) -> List[str]:
        return list(self._pvs.keys())
