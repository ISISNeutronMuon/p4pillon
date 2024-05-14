from typing import Dict, List

from p4p.nt import NTBase
from p4p.server import Server, StaticProvider

from p4p_for_isis.pvrecipe import PVScalarRecipe

from .utils import validate_pv_name


class ISISServer:
    def __init__(
        self, ioc_name: str, section: str, description: str, prefix=""
    ) -> None:
        """
        Initialize the ISIS Server instance.

        Parameters:
        - ioc_name (str): A PV naming convention compatible name for the IOC (Input/Output Controller).
        - section (str): The section or group responsible for the server e.g. Controls Software Applications, Diagnostics etc.
        - description (str): A detailed description of the server and what it does.
        - prefix (str, optional): The prefix to be added to the PVs (Process Variables) of the server e.g. DEV: Defaults to "".

        Attributes:
        - ioc_name (str): The name of the IOC (Input/Output Controller).
        - section (str): The section of the server.
        - description (str): A description of the server.
        - prefix (str): The prefix to be added to the PVs (Process Variables) of the server.
        - _provider (StaticProvider): The provider responsible for serving PVs.
        - _server (None): Placeholder for the server instance.
        - _pvs (dict): Dictionary to store PVs. NOTE these do not necessarily have to be initialised or opened yet
        """
        # provide information for IOC stats PVs
        self.ioc_name = ioc_name
        self.section = section
        self.description = description
        # the prefix determines the prefix of the PVs to be added to the server e.g. DEV:
        self.prefix = prefix
        self._provider = StaticProvider()
        self._server = None
        self._pvs = {}

    def start(self):
        # iterate over all the PVs and initialise them if they haven't
        # been already, add them to the provider and start the server
        # this means that PVs are only 'opened' and given a time stamp
        # at the time the server itself is started
        for pv_name, pv in self._pvs.items():
            # pv.initialise()
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

    def addPV(self, pv_name: str, pv_recipe: PVScalarRecipe) -> NTBase:
        if not pv_name.startswith(self.prefix):
            pv_name = self.prefix + pv_name
        pv_name = validate_pv_name(pv_name)
        returnval = self._pvs[pv_name] = pv_recipe.create_pv(pv_name)

        return returnval

    def removePV(self, pv_name: str):
        if not pv_name.startswith(self.prefix):
            pv_name = self.prefix + pv_name
        del self._pvs[pv_name]

    @property
    def pvlist(self) -> List[str]:
        return list(self._pvs.keys())

    def __getitem__(self, pv_name: str) -> NTBase:
        if not pv_name.startswith(self.prefix):
            pv_name = self.prefix + pv_name
        return self._pvs.get(pv_name)
