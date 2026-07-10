from typing import TypeVar

from p4pillon.pvrecipe import BasePVRecipe  # noqa: F401
from p4pillon.pvrecipe import PVEnumRecipe as _PVEnumRecipe
from p4pillon.pvrecipe import PVScalarArrayRecipe as _PVScalarArrayRecipe
from p4pillon.pvrecipe import PVScalarRecipe as _PVScalarRecipe
from p4pillon.server.thread import SharedPV as _SharedPV
from p4pillon.thread.sharednt import SharedNT as _SharedNT

SharedPV = _SharedPV

SharedPvT = TypeVar("SharedPvT", bound=_SharedPV)


class PVScalarRecipe(_PVScalarRecipe):
    _sharednt_cls = _SharedNT


class PVScalarArrayRecipe(_PVScalarArrayRecipe):
    _sharednt_cls = _SharedNT


class PVEnumRecipe(_PVEnumRecipe):
    _sharednt_cls = _SharedNT
