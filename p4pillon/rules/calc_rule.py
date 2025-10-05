"""
Rule to implement calc record functionality.
"""

import ast
import logging
import math as m  # noqa: F401

from p4p import Value

from .rules import BaseScalarRule, RulesFlow

logger = logging.getLogger(__name__)


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

    def __init__(self, **kwargs):
        super().__init__()
        self._variables = []
        self._calc_str: str = ""
        if "calc" in kwargs:
            self.set_calc(kwargs["calc"])

    @property
    def name(self) -> str:
        return "calc"

    @property
    def fields(self) -> None:
        """
        A return value of None means this rule is not dependent on any fields in the PV and
        will thus always be applicable.
        """
        return None

    class MonitorCB:
        """
        The MonitorCB class is used to provide call back methods for subscribing to Context.monitor
        """

        def __init__(self, server, pv_name):
            """
            This class is used within  rule to provide a call back method for Context.monitor
            The rule_method is the method that the call back will pass the value on to.
            """
            self._server = server
            self._pv_name = pv_name

        def cb(self, v: Value):
            """This callback "cb" is part of the context.monitor() functionality.
            See https://epics-base.github.io/p4p/client.html#monitor for further information."""
            self._server.put_pv_value(self._pv_name, {})

    def set_calc(self, calc) -> None:
        """
        Define the calculation to be performed.
        The required argument calc is a dictionary with the following keys:
        "calc_str", "variables", "server", "pv_name".
        """
        if "calc_str" in calc:
            self._calc_str = calc["calc_str"]

        if "variables" in calc:
            if type(calc["variables"]) is list:
                self._variables = calc["variables"]
            if type(calc["variables"]) is str:
                self._variables = [calc["variables"]]

        if "server" in calc:
            self._server = calc["server"]

        if "pv_name" in calc:
            self._pv_name = calc["pv_name"]

    def init_rule(self, value: Value, **kwargs):
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
        logger.debug(f"value is {value}, calc is {self._calc_str}, variables are {self._variables}")

        self._subs = []
        for pv in self._variables:
            temp_monitor = self.MonitorCB(self._server, self._pv_name)
            self._subs.append(self._server._ctxt.monitor(pv, temp_monitor.cb))

    def get_variables(self):
        """
        Return a list of the current values of the pvs in self._variables
        """
        pvs = []

        for pv_name in self._variables:
            try:
                val = self._server.get_pv_value(pv_name)
                if val is None:
                    logging.error("Failed to get pv %s", pv_name)
                    return None
                pvs.append(val)
            except Exception:
                # If there's an error getting the value of a pv return None
                logging.error("Failed to get pv %s", pv_name)
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

        node = ast.parse(self._calc_str, mode="eval")

        newpvstate["value"] = eval(compile(node, "<string>", "eval"))

        return ret_val
