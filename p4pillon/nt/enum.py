"""
Monkey patch in required changes to NTEnum
"""

# pylint: disable=unused-wildcard-import, wildcard-import
from p4p import version as __p4p_version
from p4p.nt.enum import *  # pyright: ignore[reportWildcardImportFromLibrary] # noqa: F403
from p4p.nt.enum import NTEnum
from p4p.nt.scalar import ntwrappercommon
from p4p.wrapper import Value

if __p4p_version > "4.2.1":
    pass
else:

    def __wrap(self, value, choices=None, **kws):
        """Pack python value into Value

        Accepts dict to explicitly initialize fields by name.
        Any other type is assigned to the 'value' field via
        the self.assign() method.
        """
        if isinstance(value, Value):
            pass
        elif isinstance(value, ntwrappercommon):
            kws.setdefault("timestamp", value.timestamp)
            value = value.raw
        elif isinstance(value, dict):
            # if index, choices not in value.keys(), then
            # use value dict to initalize fields by name
            if {"index", "choices"}.isdisjoint(value):
                value = self.Value(self.type, value)
            # if value = {'index': ..., 'choices': ...}, then
            # assign these to value.index, value.choices
            else:
                value = self.Value(self.type, {"value": value})
        else:
            # index or string
            V = self.type()
            if choices is not None:
                V["value.choices"] = choices
            self.assign(V, value)
            value = V

        # pylint: disable=W0212
        self._choices = value["value.choices"] or self._choices  # pyright: ignore[reportOptionalSubscript]
        return self._annotate(value, **kws)  # pylint: disable=W0212

    NTEnum.Value = Value  # pyright: ignore[reportAttributeAccessIssue]
    NTEnum.wrap = __wrap
