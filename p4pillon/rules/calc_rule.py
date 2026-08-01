"""
Rule to implement calc record functionality.
"""

from __future__ import annotations

import logging
import math as m
from typing import TYPE_CHECKING, Any, ClassVar

from p4p import Value
from simpleeval import ModuleWrapper, SimpleEval

from .rules import BaseScalarRule, RulesFlow, SupportedNTTypes

if TYPE_CHECKING:
    from p4pillon.server.server import Server

logger = logging.getLogger(__name__)

# Attributes of the math module that calc expressions are permitted to call, e.g. "m.sin(pv[0])".
_ALLOWED_MATH_ATTRS = frozenset(name for name in dir(m) if not name.startswith("_"))


class CalcRule(BaseScalarRule):
    """
    This class implements a calculation using a string that represents the calculation and
    a list of PV names of the variables used in the calculation.

    The following members need to be initialised in order to use the rule:
        "calc_str" is the string that defines the calculation to perform, e.g "pv[0]+2.12*pv[1]".
                    NB dependent variables are specified using the syntax pv[0], pv[1], ...
                    the math module is imported as m so you can do, e.g. "pv[0]*m.sin(pv[1])"
        "variables" is a string or list of dependent PVs, e.g. "a:pv:name" or ["pv:name:1", "pv:name:2"]
                    NB the order of the PVs in the list corresponds to pv[0], pv[1], ... in calc_str
        "server"  is the Server object to register monitor callbacks with.
        "pv_name" is the name of the pv to be updated. A put is called on this variable when any
                    dependent PV is updated.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._variables: list[str] = []
        self._calc_str: str = ""
        self.set_calc(calc=kwargs)

    name = "calc"
    nttypes: ClassVar[list[SupportedNTTypes] | None] = [SupportedNTTypes.ALL]
    fields: ClassVar[list[str] | None] = []
    add_automatically: bool = False

    class MonitorCB:
        """
        The MonitorCB class is used to provide call back methods for subscribing to Context.monitor
        """

        def __init__(self, server: Server, pv_name: str) -> None:
            """
            This class is used within  rule to provide a call back method for Context.monitor
            The rule_method is the method that the call back will pass the value on to.
            """
            self._server: Server = server
            self._pv_name: str = pv_name

        def cb(self, v: Value) -> None:
            """This callback "cb" is part of the context.monitor() functionality.
            See https://epics-base.github.io/p4p/client.html#monitor for further information."""
            self._server.put_pv_value(self._pv_name, {})

    def set_calc(self, calc: dict[str, Any]) -> None:
        """
        Define the calculation to be performed.
        The required argument calc is a dictionary with the following keys:
        "calc_str", "variables", "server", "pv_name".
        """
        if "calc_str" in calc:
            self._calc_str = calc["calc_str"]

        if "variables" in calc:
            variables = calc["variables"]
            if isinstance(variables, list):
                self._variables = variables
            elif isinstance(variables, str):
                self._variables = [variables]

        if "server" in calc:
            self._server: Server = calc["server"]

        if "pv_name" in calc:
            self._pv_name: str = calc["pv_name"]

    def init_rule(self, newpvstate: Value) -> RulesFlow:
        """
        Method to initialise monitor call backs for the variables to be monitored.
        This should be added as an on start method when creating the pv.
        """
        if (
            self._calc_str == ""
            or self._variables == []
            or type(self._server).__name__ != "Server"
            or self._pv_name == ""
        ):
            logger.error("calc rule not initialised correctly")
            raise ValueError
        logger.debug(f"value is {newpvstate}, calc is {self._calc_str}, variables are {self._variables}")

        self._subs = []
        for pv in self._variables:
            temp_monitor = self.MonitorCB(self._server, self._pv_name)
            self._subs.append(self._server._ctxt.monitor(pv, temp_monitor.cb))

        return RulesFlow.CONTINUE

    def get_variables(self) -> list[Any] | None:
        """
        Return a list of the current values of the pvs in self._variables
        """
        pvs: list[Any] = []

        for pv_name in self._variables:
            try:
                val = self._server.get_pv_value(pv_name)
                if val is None:
                    logger.error("Failed to get pv %s", pv_name)
                    return None
                pvs.append(val)
            except Exception:
                # If there's an error getting the value of a pv return None
                logger.exception("Failed to get pv %s", pv_name)
                return None

        return pvs

    def post_rule(self, oldpvstate: Value, newpvstate: Value) -> RulesFlow:
        """
        Evaluate the calculation.
          The syntax for using pvs in the calc string is to use the pv array, e.g. 'pv[0]' to use the first variable
          in self._variables. This requires the variable below (i.e. pv = self.getVariables()) to have the same name.
        """
        logger.debug("Evaluating %s.post_rule", self.name)
        logger.debug("Calculation is %s\nVariables are: %r", self._calc_str, self._variables)

        ret_val = RulesFlow.CONTINUE
        pv = self.get_variables()
        logger.debug("Values are: %r", pv)

        if pv is None:
            return RulesFlow.ABORT

        evaluator = SimpleEval(names={"pv": pv, "m": ModuleWrapper(m, allowed_attrs=_ALLOWED_MATH_ATTRS)})
        newpvstate["value"] = evaluator.eval(self._calc_str)

        return ret_val
