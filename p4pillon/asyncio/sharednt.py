from p4pillon.server.asyncio import SharedPV as _SharedPV
from p4pillon.sharednt import SharedNTMixin


class SharedNT(SharedNTMixin, _SharedPV):
    pass
