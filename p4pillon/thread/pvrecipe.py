from typing import TypeVar

from p4p.server.thread import SharedPV as _SharedPV

from p4pillon.pvrecipe import *  # noqa: F403

SharedPV = _SharedPV

SharedPvT = TypeVar("SharedPvT", bound=_SharedPV)
