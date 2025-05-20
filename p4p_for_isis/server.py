"""
ISISServer is used to create PVs and manage their lifetimes
"""

import logging
from typing import List, Union

from p4p.client.thread import Context
from p4p.server import Server, StaticProvider
from p4p.server.thread import SharedPV

from p4p_for_isis.pvrecipe import BasePVRecipe

from .utils import validate_pv_name

logger = logging.getLogger(__name__)


class ISISServer:
    """Creates PVs and manages their lifetimes"""

    def __init__(self, ioc_name: str, section: str, description: str, prefix="") -> None:
        """
        Initialize the ISIS Server instance.

        Parameters:
        - ioc_name (str): A PV naming convention compatible name for the IOC
                          (Input/Output Controller).
        - section (str):  The section or group responsible for the server
                          e.g. Controls Software Applications, Diagnostics etc.
        - description (str): A detailed description of the server and what it does.
        - prefix (str, optional): The prefix to be added to the PVs (Process Variables)
                          of the server e.g. DEV: Defaults to "".

        Attributes:
        - ioc_name (str): The name of the IOC (Input/Output Controller).
        - section (str): The section of the server.
        - description (str): A description of the server.
        - prefix (str): The prefix to be added to the PVs (Process Variables) of the server.
        - _provider (StaticProvider): The provider responsible for serving PVs.
        - _server (None): Placeholder for the server instance.
        - _pvs (dict): Dictionary to store PVs. NOTE these do not necessarily have to be
                       initialised or opened yet
        """
        # provide information for IOC stats PVs
        self.ioc_name = ioc_name
        self.section = section
        self.description = description
        # the prefix determines the prefix of the PVs to be added to the server e.g. DEV:
        self.prefix = prefix
        self._provider = StaticProvider()
        self._server: Union[Server, None] = None
        self._pvs: dict[str, SharedPV] = {}

        self._running = False

        self._ctxt = Context("pva")

    def start(self) -> None:
        """Start the ISISServer"""

        # iterate over all the PVs and initialise them if they haven't
        # been already, add them to the provider and start the server
        # this means that PVs are only 'opened' and given a time stamp
        # at the time the server itself is started
        for pv_name, pv in self._pvs.items():
            self._provider.add(pv_name, pv)

        self._server = Server(providers=[self._provider])

        for pv_name, pv in self._pvs.items():
            for method in pv.on_start_methods:
                logger.debug("Applying on server start method for pv %s method %s", pv_name, method)
                method(server=self, pv_name=pv_name, pv=pv)

        logger.debug("Started Server with %s", self.pvlist)

        self._running = True

    def stop(self) -> None:
        """Stop the ISISServer"""

        # iterate over all the PVs and close them before removing them
        # from the provider and closing the server
        for pv_name, pv in self._pvs.items():
            pv.close()
            self._provider.remove(pv_name)
        if self._server:
            self._server.stop()
        logger.debug("\nStopped server")

        self._running = False

    def add_pv(self, pv_name: str, pv_recipe: BasePVRecipe) -> SharedPV:
        """Add a PV to the server"""

        if not pv_name.startswith(self.prefix):
            pv_name = self.prefix + pv_name
        pv_name = validate_pv_name(pv_name)
        returnval = self._pvs[pv_name] = pv_recipe.create_pv(pv_name)

        # If the server is already running then we need to add this PV to
        # the live system
        if self._running:
            self._provider.add(pv_name, returnval)
            logger.debug("Added %s to server", pv_name)

        return returnval

    def remove_pv(self, pv_name: str) -> None:
        """Remove a PV from the server"""

        if not pv_name.startswith(self.prefix):
            pv_name = self.prefix + pv_name

        # TODO: Consider the implications if this throws an exception
        pv = self._pvs.pop(pv_name)
        pv.close()
        if self._running:
            # If the server is already running then we need to remove this PV
            # from the live system
            self._provider.remove(pv_name)
        logger.debug("Removed %s from server", pv_name)

    @property
    def pvlist(self) -> List[str]:
        """Return all the PVs managed by the server"""
        return list(self._pvs.keys())

    def __getitem__(self, pv_name: str) -> Union[SharedPV, None]:
        """Return one of the PVs managed by the server given its name"""
        if not pv_name.startswith(self.prefix):
            pv_name = self.prefix + pv_name
        return self._pvs.get(pv_name)

    def get_pv_value(self, pv_name: str):
        """
        Get the value of a PV using SharedPV.current() if the PV is on this server
        or Context.get() if it is not.
        """
        if pv_name in self.pvlist:
            logger.debug("Getting value using SharedPV for pv %s", pv_name)
            shared_pv = self._pvs.get(pv_name, None)
            if shared_pv:
                return shared_pv.current()

        logger.debug("Doing Context.get() for pv %s", pv_name)
        return self._ctxt.get(pv_name)

    def put_pv_value(self, pv_name: str, value):
        """
        Put the value to a PV using the server Context member self._ctxt
        """
        logger.debug("Trying putting value %r to pv %s", value, pv_name)
        self._ctxt.put(pv_name, value)
