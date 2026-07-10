from p4pillon.server.thread import SharedPV as _SharedPV
from p4pillon.sharednt import SharedNTMixin


class SharedNT(SharedNTMixin, _SharedPV):
    pass
