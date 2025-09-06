"""
An example of using pvrecipe with asyncio to create an NTScalar PV.
The created PV will be called 'demo:pv:name' and will have a default value of 17.5.
It will also have a description and alarm thresholds. If the value is changed, the
alarm secverity will automatically update.
"""

import asyncio
import logging

from p4p.server import Server, StaticProvider

from p4pillon.asyncio.pvrecipe import PVScalarRecipe
from p4pillon.definitions import PVTypes

DEFAULT_TIMEOUT = 1


class AsyncProviderWrapper:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._provider = StaticProvider()

        self._loop.run_until_complete(asyncio.wait_for(self.asyncSetUp(), DEFAULT_TIMEOUT))

    @property
    def providers(self) -> tuple[StaticProvider]:
        return (self._provider,)

    async def asyncSetUp(self):
        logging.info("Async set up.")

        pvrecipe_double1 = PVScalarRecipe(PVTypes.DOUBLE, "An example double PV", 5.0)
        pvrecipe_double1.initial_value = 17.5
        pvrecipe_double1.description = "A different default value for the PV"
        # try setting a different value for the timestamp
        pvrecipe_double1.set_timestamp(1729699237.8525229)
        pvrecipe_double1.set_alarm_limits(low_warning=2, high_alarm=9)

        pv_double1 = pvrecipe_double1.create_pv()

        self._provider.add("demo:pv:name", pv_double1)


def main():
    loop = asyncio.new_event_loop()
    provider_wrapper = AsyncProviderWrapper(loop)

    try:
        # `Server.forever()` is for p4p threading and shouldn't
        # be used with async.
        server = Server(provider_wrapper.providers)
        with server:
            done = asyncio.Event()

            # loop.add_signal_handler(signal.SIGINT, done.set)
            # loop.add_signal_handler(signal.SIGTERM, done.set)
            loop.run_until_complete(done.wait())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
