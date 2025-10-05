"""
Identify Normative Types based on their Type information
"""

import re
from enum import Enum, auto

from p4p import Type, Value

from p4pillon.nt import NTBase, NTEnum, NTNDArray, NTScalar, NTTable
from p4pillon.nt.specs import (
    ntenum_required,
    ntndarray_required,
    ntscalar_required,
    ntscalararray_required,
    nttable_required,
)


class NTType(Enum):
    """
    Normative Types in the Specification Document, excluding those in Appendix A
    """

    NTSCALAR = auto()
    NTSCALARARRAY = auto()
    NTENUM = auto()
    NTMATRIX = auto()
    NTURI = auto()
    NTNAMEVARIABLE = auto()
    NTTABLE = auto()
    NTATTRIBUTE = auto()

    NTMULTICHANNEL = auto()
    NTNDARRAY = auto()
    NTCONTINUUM = auto()
    NTHISTOGRAM = auto()
    NTAGGREGATE = auto()

    UNKNOWN = auto()


NTTypeIds = list[tuple[dict[str, re.Pattern[str]] | dict[str, dict[str, re.Pattern[str]]], NTType]]


def id_nttype_obj(type_to_id: NTBase) -> NTType:
    """
    Identify a Normative Type based on the instantiated class.
    """
    if isinstance(type_to_id, NTScalar):
        # We have to use the Type info to distinguish between an NTScalar and an
        # NTScalarArray as the NTScalar instance may not have been opened and so
        # won't have a value to inspect
        if "a" in type_to_id.type["value"]:
            return NTType.NTSCALARARRAY

        return NTType.NTSCALAR

    if isinstance(type_to_id, NTEnum):
        return NTType.NTENUM

    if isinstance(type_to_id, NTTable):
        return NTType.NTTABLE

    if isinstance(type_to_id, NTNDArray):
        return NTType.NTNDARRAY

    return NTType.UNKNOWN


def id_nttype_type(type_to_id: Type) -> NTType:
    """
    Identify a Normative Type from its Type information.
    We try to avoid using the id string to make the identification, but sometimes it's necessary.
    """

    # All known NTs are supposed to have a mandatory value field
    if not type_to_id.has("value"):
        return NTType.UNKNOWN

    tests: NTTypeIds = [
        (ntscalar_required, NTType.NTSCALAR),
        (ntscalararray_required, NTType.NTSCALARARRAY),
        (ntenum_required, NTType.NTENUM),
        (ntndarray_required, NTType.NTNDARRAY),
        (nttable_required, NTType.NTTABLE),
    ]

    nttype = matchtype(type_to_id, tests)

    return nttype


def matchtype(type_to_id: Type, potential_matches: NTTypeIds) -> NTType:
    """Given a list of specifications attempt to match the type against them."""
    # NOTE: Currently we only search two levels deep.

    # Default to not knowing the Type
    nttype = NTType.UNKNOWN

    for potential_match in potential_matches:
        match = False
        for fieldname, fieldspec in potential_match[0].items():
            if fieldname in type_to_id:
                # Plain type
                if isinstance(type_to_id[fieldname], str) and isinstance(fieldspec, re.Pattern):
                    match = bool(re.match(fieldspec, type_to_id[fieldname]))

                # Nested Type
                if isinstance(type_to_id[fieldname], Type) and isinstance(fieldspec, dict):
                    # If there's no fieldspec then we just need the field to exist
                    if not fieldspec:
                        match = True
                        continue

                    subtype_to_id = type_to_id[fieldname]
                    for fieldname2, fieldspec2 in fieldspec.items():
                        match = bool(fieldname2 in subtype_to_id and re.match(fieldspec2, subtype_to_id[fieldname2]))

                # More complex type such as a Union
                if isinstance(type_to_id[fieldname], tuple) and isinstance(fieldspec, dict):
                    if (
                        type_to_id[fieldname][0] == "U"  # Union
                        or type_to_id[fieldname][0] == "aS"  # Weird hack to support NTNDArray dimensions?
                    ):
                        union_dict = dict(type_to_id[fieldname][2])
                        match = union_dict == fieldspec

                if not match:
                    break
            else:
                match = False
                break

        if match:
            nttype = potential_match[1]
            break

    return nttype


def id_nttype(to_id: NTBase | Type | Value) -> NTType:
    """
    Identify a Normative Types type, e.g. NTScalar, NTEnum
    """
    if isinstance(to_id, NTBase):
        return id_nttype_obj(to_id)

    if isinstance(to_id, Value):
        to_id_type = to_id.type
        return id_nttype_type(to_id_type)

    if isinstance(to_id, Type):
        return id_nttype_type(to_id)

    return NTType.UNKNOWN
