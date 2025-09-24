from p4p.client.thread import Context

from p4pillon.server.server import Server as _Server


class Server(_Server):
    _context = Context
