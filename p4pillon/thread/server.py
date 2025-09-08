"""
SimpleServer is used to create PVs and manage their lifetimes
"""

from __future__ import annotations

import logging

from p4p.client.thread import Context
from p4p.server import Server, StaticProvider

from p4pillon.pvrecipe import BasePVRecipe
from p4pillon.server.simpleserver import BaseSimpleServer
from p4pillon.server.thread import SharedPV

logger = logging.getLogger(__name__)


class SimpleServer(BaseSimpleServer):
    """
    Creates PVs and manages their lifetimes
    """

    def __init__(self, prefix: str = "") -> None:
        """
        Initialize the SimpleServer instance.

        :param prefix: The prefix to be added to the PVs (Process Variables) of the server e.g. DEV: Defaults to "".
        """
        super().__init__(prefix)

        self._provider = StaticProvider()
        self._server: Server | None = None

        self._running = False

        self._ctxt = Context("pva")

    def start(self) -> None:
        """Start the SimpleServer"""

        # iterate over all the PVs and initialise them if they haven't
        # been already, add them to the provider and start the server
        # this means that PVs are only 'opened' and given a time stamp
        # at the time the server itself is started
        for pv_name, pv in self._pvs.items():
            self._provider.add(pv_name, pv)

        self._server = Server(providers=[self._provider])

        logger.debug("Started Server with %s", self.pvlist)

        self._running = True

    def stop(self) -> None:
        """Stop the SimpleServer"""

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
        """
        Add a PV to the server

        :param pv_name: The name of the PV to be added.
        :param pv_recipe: The recipe with instructions for creating the PV.
        :return: The created PV.
        """

        if not pv_name.startswith(self.prefix):
            pv_name = self.prefix + pv_name
        returnval = self._pvs[pv_name] = pv_recipe.create_pv(pv_name)

        # If the server is already running then we need to add this PV to
        # the live system
        if self._running:
            self._provider.add(pv_name, returnval)
            logger.debug("Added %s to server", pv_name)

        return returnval

    def remove_pv(self, pv_name: str) -> None:
        """
        Remove a PV from the server

        :param pv_name: The name of the PV to be removed.
        :raises KeyError: If the PV is not found in the list managed by the server.
        """

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
