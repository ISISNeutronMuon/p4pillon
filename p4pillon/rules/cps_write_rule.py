"""
Rule to write to a channel on a CPS crate.
"""

import logging

import requests
from p4p import Value

from p4pillon.rules import BaseScalarRule, RulesFlow

logger = logging.getLogger(__name__)


class CPSWriteRule(BaseScalarRule):
    """
    This class implements a rule to write 
    """

    def __init__(self, **kwargs):
        super().__init__()
        self._hw_write = {}

        if ("hw_write" in kwargs 
            and "hw" in kwargs["hw_write"]
            and kwargs["hw_write"]["hw"] == "CPS"
        ):
            self.set_cps_write(kwargs["hw_write"])

    @property
    def _name(self) -> str:
        return "cps_write"

    @property
    def _fields(self) -> None:
        """
        A return value of None means this rule is not dependent on any fields in the PV and
        will thus always be applicable.
        """
        return None

    def set_cps_write(self, hw_write) -> None:
        """
        Set the parameters needed to write the value back to the channel on the crate.
        hw_write is a dictionary of the parameters:
            "ip_addr": the ip address of the crate
            "channel_name": the channel name on the crate to write to

        """

        if "ip_addr" in hw_write and isinstance(hw_write["ip_addr"], str):
            self._hw_write["ip_addr"] = hw_write["ip_addr"]

        if ("channel_name" in hw_write 
            and isinstance(hw_write["channel_name"], str)
        ):
            self._hw_write["channel_name"] = hw_write["channel_name"]

    def init_rule(self, value: Value, **kwargs):
        """
        Method to initialise writing to the CPS crate.
        """
        logger.debug("Evaluating %s.init_rule", self._name)

        # test writing the channel to the crate.
        ret_val = self.cps_write(value["value"])

        return ret_val

    def post_rule(self, oldpvstate: Value, newpvstate: Value) -> RulesFlow:
        """
        Evaluate the calculation.
          The syntax for using pvs in the calc string is to use the pv array, e.g. 'pv[0]' to use the first variable
          in self._variables. This requires the variable below (i.e. pv = self.getVariables()) to have the same name.
        """
        logger.debug("Evaluating %s.post_rule", self._name)

        ret_val = self.cps_write(newpvstate["value"])

        return ret_val

    def cps_write(self, value) -> RulesFlow:
        """
        Compose the XML to update the channel and send it to the crate
        """
        if not self.validate_hw_write():
            raise ValueError("hw_write dictionary not set correctly")

        ret_val = RulesFlow.CONTINUE

        xml_header = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        xml_db = f"<database><channel name=\"{self._hw_write['channel_name']}\"><value>{value}</value></cahnnel></database>"
        xml_string = xml_header + xml_db

        url = f"http://{self._hw_write['ip_addr']}/scripts/database.vi?function=10"

        logger.debug(f"Sending {xml_string} to {url}")

        logger.debug("\n\n\ debugging \n\n")
        r = requests.post(
            url,
            data=xml_string,
            headers={"Content-Type": "text/xml", "Connection": "Keep-Alive"},
        )

        if r.status_code != 200 or r.status_code != 204:
            # request failed
            logging.error(
                f"Sending XML to CPS crate {self._hw_write['ip_addr']} failed with status code {r.status_code}"
            )
            ret_val = RulesFlow.TERMINATE

        return ret_val
    
    def validate_hw_write(self) -> bool:
        """
        Check that the required parameters have been set in the self._hw_write dictinoary
        """

        if ("ip_addr" not in self._hw_write
            or "channel_name" not in self._hw_write
        ):
            logger.error(f"self._hw_write not set correctly self._hw_write={self._hw_write}")
            return False

        return True
