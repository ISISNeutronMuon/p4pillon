from p4pillon.sharednt import SharedNT # noqa: I001

from p4pillon.server.thread import SharedPV as _SharedPV

SharedNT.SharedPV = _SharedPV
