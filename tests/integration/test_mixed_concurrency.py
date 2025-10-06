import asyncio
import sys
import unittest
from asyncio import sleep

from p4p.client.asyncio import Context as AsyncioContext
from p4p.client.thread import Context as ThreadContext
from p4p.server import Server

from p4pillon.asyncio.sharednt import SharedNT as AsyncioSharedNT
from p4pillon.nt import NTScalar
from p4pillon.thread.sharednt import SharedNT as ThreadSharedNT


class testMixedConcurrency(unittest.IsolatedAsyncioTestCase):
    async def start_server(self):
        a = AsyncioSharedNT(nt=NTScalar("d"), initial=5.5)
        b = ThreadSharedNT(nt=NTScalar("d"), initial=9.9)

        self.running = True
        with Server(
            providers=[
                {
                    "demo:a": a,
                    "demo:b": b,
                }
            ]
        ):
            while self.running:
                await sleep(0.1)

    async def asyncSetUp(self):
        if sys.version_info>=(3,11,0):
            async with asyncio.timeout(delay=2):
                asyncio.create_task(self.start_server())
                await asyncio.sleep(0.1)
        else:
            asyncio.create_task(self.start_server())
            await asyncio.sleep(0.1)

    async def test_asyncio(self):
        context = AsyncioContext("pva")
        if sys.version_info>=(3,11,0):
            async with asyncio.timeout(delay=2):
                value = await context.get("demo:a")
        else:
            value = await context.get("demo:a")

        assert value == 5.5

        self.running = False

    def test_thread(self):
        context = ThreadContext("pva")
        value = context.get("demo:b", timeout=1)

        assert value == 9.9

        self.running = False
