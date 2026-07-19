"""Schema for the fields common to every EPICS record (dbCommon.dbd), plus
DTYP, RTYP, and NAME, and the logic to build each field's initial `~p4p.Value`.

See the `p4pillon.server.records` package docstring for the rationale behind
each field's default. `StaticRecordProvider` (`.static`) and
`DynamicRecordFields`/`IOCMimicProvider` (`.dynamic`) all build on the logic
here to actually serve these as "RECORD.FIELD" sub-PVs.
"""

import functools
import warnings
from typing import TYPE_CHECKING, Any, NoReturn, TypedDict

from p4p import Value
from p4p.server.raw import SharedPV as _SharedPVBase

from p4pillon.nt import NTEnum, NTScalar
from p4pillon.nt.identify import NTType, id_nttype_type

if TYPE_CHECKING:
    import weakref

__all__ = (
    "COMMON_FIELDS",
    "FIELD_NAMES",
    "MENU_ALARM_SEVR",
    "MENU_ALARM_STAT",
    "MENU_PINI",
    "MENU_PRIORITY",
    "MENU_SCAN",
    "MENU_YES_NO",
    "STRING_FIELDS",
    "RecordFieldOverrides",
    "RegistryEntry",
    "build_record_fields",
    "infer_rtyp",
)

# --- menu choice lists, copied verbatim from EPICS Base's dbd/menu*.dbd,
#     in declaration order (the order fixes each choice's index) ---

MENU_SCAN: list[str] = [
    "Passive",
    "Event",
    "I/O Intr",
    "10 second",
    "5 second",
    "2 second",
    "1 second",
    ".5 second",
    ".2 second",
    ".1 second",
]
MENU_PINI: list[str] = ["NO", "YES", "RUN", "RUNNING", "PAUSE", "PAUSED"]
MENU_PRIORITY: list[str] = ["LOW", "MEDIUM", "HIGH"]
MENU_ALARM_STAT: list[str] = [
    "NO_ALARM",
    "READ",
    "WRITE",
    "HIHI",
    "HIGH",
    "LOLO",
    "LOW",
    "STATE",
    "COS",
    "COMM",
    "TIMEOUT",
    "HWLIMIT",
    "CALC",
    "SCAN",
    "LINK",
    "SOFT",
    "BAD_SUB",
    "UDF",
    "DISABLE",
    "SIMM",
    "READ_ACCESS",
    "WRITE_ACCESS",
]
MENU_ALARM_SEVR: list[str] = ["NO_ALARM", "MINOR", "MAJOR", "INVALID"]
MENU_YES_NO: list[str] = ["NO", "YES"]

# Every field declared in dbCommon.dbd with an external (gettable) IOC
# representation. A menu-kind field has 'choices'; others have 'valtype'
# (p4p NTScalar type code, see documentation/values.rst) and 'default'
# (dbCommon.dbd's initial(), or the type's zero value). DTYP/RTYP/NAME don't
# follow this pattern and are handled separately. Link fields (TSEL, SDIS,
# FLNK) are exposed as their textual link spec (valtype 's'), same as pvxs
# (see ioc/channel.cpp).

COMMON_FIELDS: dict[str, dict[str, Any]] = {
    "ASG": {"valtype": "s", "default": ""},
    "SCAN": {"choices": MENU_SCAN, "default": "Passive"},
    "PINI": {"choices": MENU_PINI, "default": "NO"},
    "PHAS": {"valtype": "h", "default": 0},
    "EVNT": {"valtype": "s", "default": ""},
    "TSE": {"valtype": "h", "default": 0},
    "TSEL": {"valtype": "s", "default": ""},
    "DISV": {"valtype": "h", "default": 1},
    "DISA": {"valtype": "h", "default": 0},
    "SDIS": {"valtype": "s", "default": ""},
    "DISP": {"valtype": "B", "default": 0},
    "PROC": {"valtype": "B", "default": 0},
    "STAT": {"choices": MENU_ALARM_STAT, "default": "UDF"},
    "SEVR": {"choices": MENU_ALARM_SEVR, "default": "NO_ALARM"},
    "AMSG": {"valtype": "s", "default": ""},
    "NSTA": {"choices": MENU_ALARM_STAT, "default": "NO_ALARM"},
    "NSEV": {"choices": MENU_ALARM_SEVR, "default": "NO_ALARM"},
    "NAMSG": {"valtype": "s", "default": ""},
    "ACKS": {"choices": MENU_ALARM_SEVR, "default": "NO_ALARM"},
    "ACKT": {"choices": MENU_YES_NO, "default": "YES"},
    "DISS": {"choices": MENU_ALARM_SEVR, "default": "NO_ALARM"},
    "LCNT": {"valtype": "B", "default": 0},
    "PACT": {"valtype": "B", "default": 0},
    "PUTF": {"valtype": "B", "default": 0},
    "RPRO": {"valtype": "B", "default": 0},
    "PRIO": {"choices": MENU_PRIORITY, "default": "LOW"},
    "TPRO": {"valtype": "B", "default": 0},
    "UDF": {"valtype": "B", "default": 1},
    "UDFS": {"choices": MENU_ALARM_SEVR, "default": "INVALID"},
    "UTAG": {"valtype": "L", "default": 0},
    "FLNK": {"valtype": "s", "default": ""},
}

# String-valued field names -- each gets a "<FIELD>$" long-string alias (see
# the package docstring). DTYP is deliberately excluded: it's a menu/choice
# field (NTEnum), not a string. DESC isn't in COMMON_FIELDS (see
# _build_one_field's DESC case) but is still string-valued, so it's added here.
STRING_FIELDS: frozenset[str] = frozenset(
    fieldname for fieldname, spec in COMMON_FIELDS.items() if spec.get("valtype") == "s"
) | {"NAME", "RTYP", "DESC"}

# Every field name servable through build_record_fields()/StaticRecordProvider.
# ADEL/MDEL are only included when _field_applies() says so (see below).
FIELD_NAMES: frozenset[str] = (
    frozenset(COMMON_FIELDS)
    | {"DTYP", "RTYP", "NAME", "ADEL", "MDEL", "DESC"}
    | {f"{fieldname}$" for fieldname in STRING_FIELDS}
)

# Static-typing counterpart to FIELD_NAMES, checked at runtime by
# _validate_fields. Must be kept in sync with FIELD_NAMES by hand -- pyright
# rejects a dict comprehension here, so this can't be generated -- guarded
# by TestRecordFieldOverridesTyping.test_matches_field_names. Every value is
# `Any` since an override's shape differs (choice name vs raw value).
RecordFieldOverrides = TypedDict(
    "RecordFieldOverrides",
    {
        "DESC": Any,
        "DESC$": Any,
        "ASG": Any,
        "ASG$": Any,
        "SCAN": Any,
        "PINI": Any,
        "PHAS": Any,
        "EVNT": Any,
        "EVNT$": Any,
        "TSE": Any,
        "TSEL": Any,
        "TSEL$": Any,
        "DISV": Any,
        "DISA": Any,
        "SDIS": Any,
        "SDIS$": Any,
        "DISP": Any,
        "PROC": Any,
        "STAT": Any,
        "SEVR": Any,
        "AMSG": Any,
        "AMSG$": Any,
        "NSTA": Any,
        "NSEV": Any,
        "NAMSG": Any,
        "NAMSG$": Any,
        "ACKS": Any,
        "ACKT": Any,
        "DISS": Any,
        "LCNT": Any,
        "PACT": Any,
        "PUTF": Any,
        "RPRO": Any,
        "PRIO": Any,
        "TPRO": Any,
        "UDF": Any,
        "UDFS": Any,
        "UTAG": Any,
        "FLNK": Any,
        "FLNK$": Any,
        "DTYP": Any,
        "RTYP": Any,
        "RTYP$": Any,
        "NAME": Any,
        "NAME$": Any,
        "ADEL": Any,
        "MDEL": Any,
    },
    total=False,
)
RecordFieldOverrides.__doc__ = """Shape of the `fields` override dict accepted by
`build_record_fields`, `StaticRecordProvider.add`, and `IOCMimicProvider.add`.
Every key is optional; a present key's value is a raw value for scalar-kind
fields, or a choice name (str) for menu-kind fields including DTYP and RTYP.
An unrecognized key is ignored and emits a `UserWarning` (see `_validate_fields`).
"""


class _RegistryEntryRequired(TypedDict):
    valtype: str


class RegistryEntry(_RegistryEntryRequired, total=False):
    """Shape of each value in the `registry` dict passed to `DynamicRecordFields`.
    Only 'valtype' is required; 'dtyp_choices', 'fields', and 'description'
    are optional, same as the corresponding `build_record_fields` parameters.

    DESC is resolved per `makeChannel()` call: from the base PV's live
    ``display.description`` when 'pv_ref' (a `weakref.ref` to the base PV) is
    present and still alive, else from 'description'. `IOCMimicProvider.add`
    and `IOCMimicServer`'s plain-dict shorthand set 'pv_ref' so DESC tracks
    the base PV automatically for new connections; a hand-built registry can
    instead update 'description' in place. See the package docstring's DESC
    note.
    """

    dtyp_choices: list[str] | None
    fields: RecordFieldOverrides
    description: str
    pv_ref: "weakref.ref[_SharedPVBase]"


# NTScalar type codes for which ADEL/MDEL are meaningful -- a plain numeric
# scalar (see the package docstring's ADEL/MDEL bullet). Excludes 's'
# (string), '?' (bool), and array codes.
_ADEL_MDEL_VALTYPES: frozenset[str] = frozenset("bBhHiIlLfd")


def _field_applies(fieldname: str, valtype: str) -> bool:
    """Whether `fieldname` applies to a base PV of the given `valtype`.

    True for every name except ADEL/MDEL, which need a numeric scalar
    `valtype` (see `_ADEL_MDEL_VALTYPES`).
    """
    if fieldname in ("ADEL", "MDEL"):
        return valtype in _ADEL_MDEL_VALTYPES
    return True


# Sentinel `valtype` for an NTEnum-backed PV: unlike a scalar there's no p4p
# value-type code, so this marker is threaded through the valtype pipeline
# (`_infer_valtype_of_pv` -> registry/build_record_fields) purely to select the
# enum RTYP default and to keep ADEL/MDEL from applying (it's not a numeric
# code; see `_ADEL_MDEL_VALTYPES`/`_field_applies`).
_ENUM_VALTYPE = "enum"


def infer_rtyp(valtype: str) -> str:
    """Guess a plausible RTYP from an NTScalar value type code, or from the
    `_ENUM_VALTYPE` sentinel for an NTEnum-backed PV. See the package
    docstring's RTYP note for when this is used."""
    if valtype == _ENUM_VALTYPE:
        # mbbi (multi-state binary *input*): its DBF_ENUM VAL is the same
        # index+choices shape as an NTEnum, and the input side matches the
        # scalar leans ('d'->ai, not ao). See the package docstring's RTYP note.
        return "mbbi"
    if valtype[:1] == "a":
        return "waveform"
    if valtype == "s":
        return "stringin"
    if valtype == "?":
        return "bi"
    if valtype in ("f", "d"):
        return "ai"
    if valtype in ("l", "L"):
        # 64-bit: longin's VAL is DBF_LONG (32-bit) and would truncate, so use
        # int64in (VAL DBF_INT64), matching pvxs (ioc/typeutils.cpp). Its
        # ADEL/MDEL, like longin's, keep 'l'/'L' in _ADEL_MDEL_VALTYPES.
        return "int64in"
    return "longin"  # b, B, h, H, i, I -- all fit DBF_LONG without loss


def _infer_valtype_of_pv(pv: _SharedPVBase) -> str | None:
    """The NTScalar value type code `pv` was built with, the `_ENUM_VALTYPE`
    sentinel for an NTEnum-backed PV, or `None` if it can't be determined
    without guessing (`pv.nt` unset/non-scalar and no enum structure) --
    callers should then require an explicit `valtype`."""
    nt = getattr(pv, "nt", None)
    if isinstance(nt, NTScalar):
        return nt.type["value"]
    if isinstance(nt, NTEnum):
        return _ENUM_VALTYPE
    if nt is not None:
        # Some other declared NT (NTTable/NTNDArray/...): no scalar code, and
        # not RTYP-inferrable anyway (see _check_rtyp_inferrable).
        return None
    # pv.nt unset (e.g. a hand-built Value with no nt=): recognise an enum
    # structurally, mirroring _check_rtyp_inferrable's fallback. A hand-built
    # scalar keeps the historical 'd' default applied by the caller.
    raw = _raw_current_or_none(pv)
    if raw is not None and id_nttype_type(raw.type()) == NTType.NTENUM:
        return _ENUM_VALTYPE
    return None


@functools.cache
def _scalar_nt(valtype: str) -> NTScalar:
    return NTScalar(valtype)


def _menu_pv(choices: list[str], default_name: str, override: str | None) -> Value:
    # A fresh NTEnum per call, not a shared module-level instance: unlike
    # NTScalar, NTEnum is stateful (wrap() caches value.choices on the
    # instance for unwrap()), and this runs both on user threads (add()) and
    # the server's I/O thread (DynamicRecordFields.makeChannel()).
    return NTEnum().wrap(default_name if override is None else override, choices=choices)


def _scalar_pv(valtype: str, default: Any, override: Any) -> Value:
    # default/override's type depends on valtype (str, int, float, bool, ...)
    # -- not worth a union that has to track every valtype this supports.
    return _scalar_nt(valtype).wrap(default if override is None else override)


# The NT flavors infer_rtyp() has a plausible guess for: a scalar, scalar
# array, or enum (NTEnum -> mbbi); anything else (NTTable, NTNDArray, ...) needs
# an explicit RTYP. Classified via p4pillon.nt.identify's structural NT
# classifier (used elsewhere in the codebase too) rather than a second,
# hand-maintained ID-to-NT-flavor mapping.
_RTYP_INFERRABLE_NT_TYPES: frozenset[NTType] = frozenset(
    (NTType.NTSCALAR, NTType.NTSCALARARRAY, NTType.NTENUM, NTType.UNKNOWN)
)


def _raise_rtyp_not_inferrable(desc: str) -> NoReturn:
    msg = f"Cannot infer RTYP for {desc}; pass fields={{'RTYP': ...}} explicitly."
    raise ValueError(msg)


def _raw_current_or_none(pv: _SharedPVBase) -> Value | None:
    # Best-effort raw Value of pv's live current(), used when pv.nt is None.
    # None means "unknown" (not open()'d yet, current() failed, or an
    # unwrap= with no .raw) -- shared by _check_rtyp_inferrable and
    # _description_of_pv.
    try:
        current = pv.current()
    except Exception:
        return None
    # p4p's own NT wrappers guarantee `.raw` is a real Value; a hand-rolled
    # unwrap= makes no such promise (see test_rtyp_check_tolerates_non_value_unwrap).
    raw = getattr(current, "raw", current)
    return raw if isinstance(raw, Value) else None


def _description_of_pv(pv: _SharedPVBase) -> str:
    nt = getattr(pv, "nt", None)
    if nt is not None and "display.description" not in nt.type:
        return ""

    raw = _raw_current_or_none(pv)
    if raw is None or "display.description" not in raw:
        return ""
    return raw.get("display.description", "") or ""


def _rtyp_inferrable(pv: _SharedPVBase) -> bool:
    """Whether `infer_rtyp` has a plausible RTYP for `pv`'s NT flavor: True for
    an NTScalar/NTScalarArray/NTEnum (or an unclassifiable hand-built Value,
    treated as scalar-like), False for a structural NT (NTTable, NTNDArray, ...)
    that corresponds to no single EPICS record type.

    A provider serving a False PV omits its record fields entirely -- the base
    PV is still served, mirroring how a real IOC serves a Q:group (which exposes
    no dbCommon fields) -- unless an explicit ``fields={'RTYP': ...}`` opts it
    into record treatment. The strict `build_record_fields` builder instead
    raises for such a PV (see `_check_rtyp_inferrable`).
    """
    # pv.nt already gives the type -- skip the current()-based fallback below.
    nt = getattr(pv, "nt", None)
    if nt is not None:
        return isinstance(nt, (NTScalar, NTEnum))

    # pv.nt unset -- classify the live Value's structure instead; an
    # unavailable current() counts as NTType.UNKNOWN (treated as inferrable).
    raw = _raw_current_or_none(pv)
    # id_nttype_type (not id_nttype) deliberately: id_nttype's Value-dispatch
    # branch reads `value.type` as a property, but p4p.wrapper.Value.type is
    # a *method* -- passing a raw Value there silently misclassifies it. Call
    # raw.type() ourselves and classify the resulting Type instead.
    nttype = id_nttype_type(raw.type()) if raw is not None else NTType.UNKNOWN
    return nttype in _RTYP_INFERRABLE_NT_TYPES


def _check_rtyp_inferrable(pv: _SharedPVBase) -> None:
    # Strict builder-level guard: a direct `build_record_fields` caller asking
    # to build fields for a non-record PV with no explicit RTYP gets a clear
    # error (it can't invent one). The providers instead pre-check
    # `_rtyp_inferrable` and simply omit the fields, so this only fires for a
    # direct caller.
    if _rtyp_inferrable(pv):
        return
    nt = getattr(pv, "nt", None)
    if nt is not None:
        _raise_rtyp_not_inferrable(f"a {type(nt).__name__}-backed PV")
    raw = _raw_current_or_none(pv)
    nttype = id_nttype_type(raw.type()) if raw is not None else NTType.UNKNOWN
    _raise_rtyp_not_inferrable(f"a {nttype.name}-shaped PV")


def _should_serve_record_fields(pv: _SharedPVBase, fields: RecordFieldOverrides | None) -> bool:
    """Whether a base PV should be given "<name>.<FIELD>" sub-PVs: yes when its
    RTYP is inferrable, or an explicit ``fields={'RTYP': ...}`` opts a
    non-record-like PV (NTTable/NTNDArray/... -> a Q:group, no dbCommon fields)
    into record treatment. Shared by the eager (`.static`) and lazy (`.dynamic`,
    `.server`) providers' add paths so the two can't diverge -- see the package
    docstring's RTYP note."""
    if fields and fields.get("RTYP") is not None:
        return True
    return _rtyp_inferrable(pv)


def _dtyp_choices(dtyp_choices: list[str] | None) -> list[str]:
    """DTYP's menu choices: the caller-supplied list, or the ``["Soft Channel"]``
    default (a plain p4p PV's implicit device support) when none is given."""
    return list(dtyp_choices) if dtyp_choices else ["Soft Channel"]


def _menu_choices_for(fieldname: str, dtyp_choices: list[str] | None) -> list[str] | None:
    """The valid choice names for a menu-kind field, or `None` for a
    scalar-kind (or unknown) field name."""
    if fieldname == "DTYP":
        return _dtyp_choices(dtyp_choices)
    spec = COMMON_FIELDS.get(fieldname)
    if spec is not None and "choices" in spec:
        return spec["choices"]
    return None


def _validate_fields(fields: RecordFieldOverrides, name: str, dtyp_choices: list[str] | None = None) -> None:
    # Shared by build_record_fields, DynamicRecordFields.__init__, and
    # IOCMimicProvider.add so a typo'd key warns (and a bad menu choice
    # raises) the same way regardless of entry point.
    unknown = fields.keys() - FIELD_NAMES
    if unknown:
        warnings.warn(
            f"fields override for {name!r} has unrecognized field name(s) "
            f"{sorted(unknown)!r}; ignored. See FIELD_NAMES for valid names.",
            stacklevel=3,
        )
    for fieldname, override in fields.items():
        if override is None:
            continue
        choices = _menu_choices_for(fieldname, dtyp_choices)
        if choices is not None and override not in choices:
            # Without this, the typo would surface much later as NTEnum.assign's
            # fallback int() parse -- "invalid literal for int() with base 0".
            msg = (
                f"fields override {fieldname}={override!r} for {name!r} is not a valid "
                f"choice name; expected one of {choices!r}."
            )
            raise ValueError(msg)


def _build_one_field(
    fieldname: str,
    name: str,
    valtype: str,
    dtyp_choices: list[str] | None,
    fields: RecordFieldOverrides,
    description: str,
) -> Value:
    if fieldname.endswith("$"):
        # '<FIELD>$' is a long-string alias -- same value as '<FIELD>'.
        return _build_one_field(fieldname[:-1], name, valtype, dtyp_choices, fields, description)

    if fieldname == "DTYP":
        choices = _dtyp_choices(dtyp_choices)
        return _menu_pv(choices, choices[0], fields.get("DTYP"))

    if fieldname == "RTYP":
        # Inferrability is validated once by build_record_fields, not here.
        return _scalar_pv("s", infer_rtyp(valtype), fields.get("RTYP"))

    if fieldname == "NAME":
        # Mirrors the record's own PV name -- not overridable, same as
        # dbCommon.dbd's special(SPC_NOMOD) on this field.
        return _scalar_nt("s").wrap(name)

    if fieldname == "DESC":
        # Mirrors display.description -- not overridable, same as NAME.
        return _scalar_nt("s").wrap(description)

    if fieldname in ("ADEL", "MDEL"):
        # Same DBF/valtype as VAL itself. Caller must have already checked
        # _field_applies() before requesting this.
        return _scalar_pv(valtype, 0, fields.get(fieldname))

    spec = COMMON_FIELDS[fieldname]
    override = fields.get(fieldname)
    if "choices" in spec:
        return _menu_pv(spec["choices"], spec["default"], override)
    return _scalar_pv(spec["valtype"], spec["default"], override)


def build_record_fields(
    name: str,
    valtype: str,
    dtyp_choices: list[str] | None = None,
    fields: RecordFieldOverrides | None = None,
    pv: _SharedPVBase | None = None,
    description: str = "",
) -> dict[str, Value]:
    """Build the "<name>.<FIELD>" values for every applicable field in
    `FIELD_NAMES`. See the package docstring for which fields those are and
    how each default is chosen.

    :param str name: The base PV name (used verbatim as the NAME field's value).
    :param str valtype: NTScalar value type code of the base PV (or the
                        ``_ENUM_VALTYPE`` sentinel for an NTEnum), used to infer a
                        default RTYP (see `infer_rtyp`).
    :param list dtyp_choices: Menu choices for DTYP.  Defaults to ``["Soft Channel"]``.
    :param dict fields: Per-field overrides.  A raw value for scalar-kind fields,
                        or a choice name (str) for menu-kind fields including DTYP
                        and RTYP.  An unknown key is ignored and emits a `UserWarning`.
    :param pv: The base PV, if available -- used to check whether RTYP can
              plausibly be inferred; raises `ValueError` if not, unless
              `fields` gives ``"RTYP"`` explicitly.
    :param str description: The value for DESC/DESC$.  Not settable via `fields`
                        (same as NAME).  Defaults to ``""``.
    :returns: dict mapping field name to an initial `~p4p.Value`, suitable to pass
             directly as a `~p4p.server.thread.SharedPV`'s ``initial=``.
    """
    fields = fields or {}
    _validate_fields(fields, name, dtyp_choices)
    if pv is not None and fields.get("RTYP") is None:
        # pv is None from DynamicRecordFields.makeChannel() (no live PV to
        # check). Checked once here, not per-field -- pv.current() isn't free.
        _check_rtyp_inferrable(pv)
    return {
        fieldname: _build_one_field(fieldname, name, valtype, dtyp_choices, fields, description)
        for fieldname in FIELD_NAMES
        if _field_applies(fieldname, valtype)
    }


@functools.cache
def _default_pv_factory() -> type[_SharedPVBase]:
    # Lazy + cached: importing p4pillon.server.thread at module scope would
    # force a hard dependency on it for callers who only use
    # build_record_fields() or always pass their own pv_factory.
    from p4pillon.server.thread import SharedPV

    return SharedPV


def _field_shared_pv(value: Value, pv_factory: type[_SharedPVBase] | None = None) -> _SharedPVBase:
    return (pv_factory or _default_pv_factory())(initial=value)


def _flavor_matched_pv_factory(pv: _SharedPVBase) -> type[_SharedPVBase]:
    """The p4pillon SharedPV class matching `pv`'s concurrency flavor (thread
    vs asyncio), for building "<name>.<FIELD>" sub-PVs.

    Deliberately NOT ``type(pv)``: a concrete subclass like
    `~p4pillon.thread.sharednt.SharedNT` attaches its own rule handlers in
    ``__init__``, which would make every sub-PV built from it client-writable
    (CompositeHandler.put accepts puts) and timestamp-rewritten -- the
    opposite of the read-only mirror these fields are documented to be. Only
    the concurrency flavor is matched.
    """
    from p4p.server.asyncio import SharedPV as _RawAsyncioSharedPV

    if isinstance(pv, _RawAsyncioSharedPV):
        from p4pillon.server.asyncio import SharedPV as _AsyncioSharedPV

        return _AsyncioSharedPV
    return _default_pv_factory()


def _resolve_registry_description(entry: RegistryEntry) -> str:
    """The DESC value for a `RegistryEntry`: the base PV's live
    ``display.description`` when 'pv_ref' is present and alive, else the
    'description' snapshot. See `RegistryEntry`'s docstring."""
    pv_ref = entry.get("pv_ref")
    if pv_ref is not None:
        pv = pv_ref()
        if pv is not None:
            return _description_of_pv(pv)
    return entry.get("description") or ""


def _resolve_valtype_and_description(pv: _SharedPVBase, valtype: str | None) -> tuple[str, str]:
    """(valtype, description) for `pv`, shared by every `add()`/shorthand
    that builds record fields: `valtype` falls back to
    `_infer_valtype_of_pv(pv)` (then ``'d'``) when not given explicitly;
    `description` is a snapshot of `pv`'s ``display.description``.
    """
    if valtype is None:
        valtype = _infer_valtype_of_pv(pv) or "d"
    return valtype, _description_of_pv(pv)
