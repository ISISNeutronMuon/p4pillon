from p4pillon.sharednt import SharedNT  # noqa: I001

from p4pillon.server.asyncio import SharedPV as _SharedPV

SharedNT.SharedPV = _SharedPV
