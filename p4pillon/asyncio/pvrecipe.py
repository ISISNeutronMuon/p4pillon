from typing import TypeVar

from p4pillon.pvrecipe import *  # noqa: F403
from p4pillon.server.thread import SharedPV as _SharedPV

SharedPV = _SharedPV

SharedPvT = TypeVar("SharedPvT", bound=_SharedPV)
