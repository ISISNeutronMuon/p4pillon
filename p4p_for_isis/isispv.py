"""
Required to allow post operations trigger handler rules
"""

import logging

from p4p.server.raw import Handler, SharedPV

logger = logging.getLogger(__name__)


class ISISPV(SharedPV):
    """Implementation that applies specified rules to post operations"""

    @property
    def handler(self) -> Handler:
        """Access to handler of this PV"""
        return self._handler

    @handler.setter
    def handler(self, newhandler: Handler):
        self._handler = newhandler

    def post(self, value, **kws) -> None:
        """
        Override parent post method in order to apply post_rules.
        Rules application may be switched off using `rules=False`.
        """

        evaluate_rules = kws.pop("rules", True)

        # Attempt to wrap the user provided value
        try:
            newval = self._wrap(value, **kws)
        except Exception as err:
            raise ValueError(f"Unable to wrap {value} with {self._wrap} and {kws}") from err

        # Apply rules unless they've been switched off
        if evaluate_rules:
            self._handler.post(self, newval)  # type: ignore

        super().post(newval, **kws)
