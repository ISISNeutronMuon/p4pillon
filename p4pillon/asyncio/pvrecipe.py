"""Concrete implementations of PVRecipe using ascyncio"""

from __future__ import annotations

from p4pillon.definitions import PVTypes
from p4pillon.nthandlers import NTEnumRulesHandler, NTScalarArrayRulesHandler, NTScalarRulesHandler
from p4pillon.pvrecipe import BasePVRecipe
from p4pillon.pvrecipe import PVScalarRecipe as _PVScalarRecipe
from p4pillon.server.asyncio import SharedPV


class PVScalarRecipe(_PVScalarRecipe):
    """
    A recipe for creating a PV of type NTScalar.

    This class is used to create a PV that represents a scalar value,
    allowing for the definition of initial values, descriptions, and other properties.
    """

    def create_pv(self, pv_name: str | None = None) -> SharedPV:
        """Turn the recipe into an actual NTScalar, NTEnum, or
        other BasePV derived object"""

        self._config_display()
        self._config_control()
        self._config_alarm_limit()

        handler = NTScalarRulesHandler()

        return super().build_pv(SharedPV, handler, pv_name)


class PVScalarArrayRecipe(_PVScalarRecipe):
    """
    A recipe for creating a PV of type NTScalar.

    This class is used to create a PV that represents an array of scalar values,
    allowing for the definition of initial values, descriptions, and other properties.
    """

    def create_pv(self, pv_name: str | None = None) -> SharedPV:
        """Turn the recipe into an actual NTScalar with an array"""

        self._config_display()
        self._config_control()
        self._config_alarm_limit()

        handler = NTScalarArrayRulesHandler()

        if not isinstance(self.initial_value, list):
            self.initial_value = [self.initial_value]

        return super().build_pv(SharedPV, handler, pv_name)


class PVEnumRecipe(BasePVRecipe):
    """
    A recipe for creating a PV of type NTEnum.

    This class is used to create a PV that represents an enumeration type,
    allowing for the definition of enum values and their corresponding labels.
    """

    def __post_init__(self):
        super().__post_init__()
        if self.pvtype != PVTypes.ENUM:
            raise ValueError(f"Unsupported pv type {self.pvtype} for class {{self.__class__.__name__}}")

    def create_pv(self, pv_name: str | None = None) -> SharedPV:
        """Turn the recipe into an actual NTEnum"""

        handler = NTEnumRulesHandler()

        return super().build_pv(SharedPV, handler, pv_name)
