"""Schema for the fields common to every EPICS record (dbCommon.dbd), plus
DTYP, RTYP, and NAME, and the logic to build each field's initial `~p4p.Value`.

See the `p4pillon.server.records` package docstring for the rationale behind
each field's default. `StaticRecordProvider` (`.static`) and
`DynamicRecordFields`/`IOCRecordProvider` (`.dynamic`) all build on the logic
here to actually serve these as "RECORD.FIELD" sub-PVs.
"""

import functools
import warnings
from typing import Any, NoReturn, TypedDict

from p4p import Value
from p4p.server.raw import SharedPV as _SharedPVBase

from p4pillon.nt import NTEnum, NTScalar
from p4pillon.nt.identify import NTType, id_nttype_type

__all__ = (
    "MENU_SCAN",
    "MENU_PINI",
    "MENU_PRIORITY",
    "MENU_ALARM_STAT",
    "MENU_ALARM_SEVR",
    "MENU_YES_NO",
    "COMMON_FIELDS",
    "STRING_FIELDS",
    "FIELD_NAMES",
    "RecordFieldOverrides",
    "RegistryEntry",
    "infer_rtyp",
    "build_record_fields",
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

# --- every field declared in dbCommon.dbd that has an external (gettable)
#     representation on a real IOC.  A menu-kind field has 'choices'; every
#     other field has 'valtype', its p4p NTScalar value type code (see
#     documentation/values.rst).  'default' gives the value dbCommon.dbd's
#     own initial() implies (or the type's zero value, where none is
#     declared), absent a per-PV override.  DTYP, RTYP and NAME are handled
#     separately since none of them follow this pattern.
#
# link fields (DBF_INLINK/DBF_OUTLINK/DBF_FWDLINK: TSEL, SDIS, FLNK) are
# exposed as their textual link specification (valtype 's'), same as pvxs
# does (see ioc/channel.cpp).

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
# the package docstring and _build_one_field).  DTYP is deliberately excluded:
# it's a menu/choice field (NTEnum), not a string, despite dbCommon.dbd
# storing its choice as DBF_MENU rather than DBF_STRING either.  DESC is
# excluded from COMMON_FIELDS itself (see _build_one_field's DESC special
# case) but is still string-valued, so it's added here explicitly.
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

# Static-typing counterpart to the runtime FIELD_NAMES check
# (_validate_fields): lets mypy/pyright flag a typo'd key in a
# `fields={...}` literal before the code ever runs. TypedDict's functional
# form requires a literal dict (pyright rejects a dict comprehension:
# "Expected simple dictionary entry"), so this must be kept in sync with
# FIELD_NAMES by hand -- guarded by
# TestRecordFieldOverridesTyping.test_matches_field_names, which fails if
# they drift apart. Every value is `Any`: this only catches unknown *keys*,
# not value-type mismatches (a menu-kind field's override is a choice name
# while a scalar-kind field's is a raw value, so no single type fits all).
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


class _RegistryEntryRequired(TypedDict):
    valtype: str


class RegistryEntry(_RegistryEntryRequired, total=False):
    """Shape of each value in the `registry` dict passed to `DynamicRecordFields`.
    Only 'valtype' is required; 'dtyp_choices', 'fields', and 'description'
    are optional, same as the corresponding `build_record_fields` parameters.
    'description' is a snapshot only -- re-read once per `makeChannel()` call
    (i.e. once per client connect to that record's fields). Update it via
    `~p4pillon.server.records.IOCRecordProvider.set_description` if this
    registry is one it manages; a hand-built registry can just mutate this
    key directly, same effect.
    """

    dtyp_choices: list[str] | None
    fields: RecordFieldOverrides
    description: str


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


def infer_rtyp(valtype: str) -> str:
    """Guess a plausible RTYP from an NTScalar value type code. Only used
    when 'fields' doesn't set 'RTYP' explicitly and the base PV is
    NTScalar-shaped -- enforced by `_check_rtyp_inferrable`, since e.g.
    `~p4p.nt.NTTable`/`~p4p.nt.NTNDArray` have no plausible guess (real
    IOCs have no "table" record type either).
    """
    if valtype[:1] == "a":
        return "waveform"
    if valtype == "s":
        return "stringin"
    if valtype == "?":
        return "bi"
    if valtype in ("f", "d"):
        return "ai"
    return "longin"  # b, B, h, H, i, I, l, L


def _infer_valtype_of_pv(pv: _SharedPVBase) -> str | None:
    """The NTScalar value type code `pv` was built with, or `None` if it
    can't be determined without guessing.

    Only checks `pv.nt` (set by `SharedPV(nt=...)`) -- authoritative when
    present. `None` (never a guessed ``'d'``) when `pv.nt` is unset (a
    hand-built PV using `wrap=`/`unwrap=`) or isn't an NTScalar; callers
    are then expected to pass `valtype` explicitly, same as for
    `fields={'RTYP': ...}` (see `_check_rtyp_inferrable`).
    """
    nt = getattr(pv, "nt", None)
    if isinstance(nt, NTScalar):
        return nt.type["value"]
    return None


# Every menu-kind field shares the same NTEnum schema (only 'choices', a data
# value not a type parameter, differs between them), and every scalar-kind
# field reuses one of a handful of NTScalar valtypes -- so a single instance
# per schema is built lazily and reused, rather than reparsing the same
# pvxs structure definition on every field/PV/connection.
_menu_nt = NTEnum()


@functools.cache
def _scalar_nt(valtype: str) -> NTScalar:
    return NTScalar(valtype)


def _menu_pv(choices: list[str], default_name: str, override: str | None) -> Value:
    return _menu_nt.wrap(default_name if override is None else override, choices=choices)


def _scalar_pv(valtype: str, default: Any, override: Any) -> Value:
    return _scalar_nt(valtype).wrap(default if override is None else override)


# infer_rtyp() has no plausible guess for anything but a scalar or scalar
# array -- checked only on the _check_rtyp_inferrable() slow path, via
# p4pillon.nt.identify's structural NT classifier (the same mechanism used
# everywhere else in the codebase to tell NT flavors apart) rather than a
# second, hand-maintained ID-to-NT-flavor mapping.
_SCALAR_LIKE_NT_TYPES: frozenset[NTType] = frozenset((NTType.NTSCALAR, NTType.NTSCALARARRAY, NTType.UNKNOWN))


def _raise_rtyp_not_inferrable(desc: str) -> NoReturn:
    raise ValueError(f"Cannot infer RTYP for {desc}; pass fields={{'RTYP': ...}} explicitly.")


def _raw_current_or_none(pv: _SharedPVBase) -> Any | None:
    # Best-effort raw Value of pv's live current(), for when pv.nt is None (a
    # hand-built PV using a plain Value, or wrap=/unwrap() were used instead).
    # None means "unknown" (not open()'d yet, or pv.current() itself failed)
    # -- shared by _check_rtyp_inferrable and _description_of_pv's slow path,
    # both of which need the same "fetch current(), unwrap .raw" step.
    try:
        current = pv.current()
    except Exception:
        return None
    return getattr(current, "raw", current)


def _description_of_pv(pv: _SharedPVBase) -> str:
    # One-time snapshot of pv's display.description, or "" if absent. Shared
    # by StaticRecordProvider.add, IOCRecordProvider.add, and the
    # DynamicProvider built for IOCRecordServer's dict shorthand, so it
    # lives here rather than in any one of those.
    nt = getattr(pv, "nt", None)
    if nt is not None and "display.description" not in nt.type:
        return ""

    raw = _raw_current_or_none(pv)
    if raw is None:
        return ""
    try:
        if "display.description" not in raw:
            return ""
        return raw.get("display.description", "") or ""
    except TypeError:
        # raw isn't Value-like (e.g. a hand-rolled unwrap= returning
        # something else).
        return ""


def _check_rtyp_inferrable(pv: _SharedPVBase) -> None:
    # pv.nt tells us the PV's actual type with no further access, when set.
    nt = getattr(pv, "nt", None)
    if nt is not None:
        if not isinstance(nt, NTScalar):
            _raise_rtyp_not_inferrable(f"a {type(nt).__name__}-backed PV")
        return

    # pv.nt is None (hand-built with a plain Value, or wrap=/unwrap= was
    # used) -- fall back to classifying the live Value's own structure.
    # `None` (pv.current() unavailable) is treated as NTType.UNKNOWN, i.e.
    # never rejected.
    raw = _raw_current_or_none(pv)
    # id_nttype_type (not id_nttype) deliberately: id_nttype's Value-dispatch
    # branch reads `value.type` as a property, but p4p.wrapper.Value.type is
    # a *method* -- passing a raw Value there silently misclassifies it. Call
    # raw.type() ourselves and classify the resulting Type instead.
    nttype = id_nttype_type(raw.type()) if raw is not None else NTType.UNKNOWN
    if nttype not in _SCALAR_LIKE_NT_TYPES:
        _raise_rtyp_not_inferrable(f"a {nttype.name}-shaped PV")


def _validate_fields(fields: RecordFieldOverrides, name: str) -> None:
    # Shared by build_record_fields (per add()/call) and
    # DynamicRecordFields.__init__ (once per registry entry, eagerly at
    # construction time rather than lazily on first client connect) so a
    # typo'd key is warned about the same way regardless of entry point.
    unknown = fields.keys() - FIELD_NAMES
    if unknown:
        warnings.warn(
            f"fields override for {name!r} has unrecognized field name(s) "
            f"{sorted(unknown)!r}; ignored. See FIELD_NAMES for valid names.",
            stacklevel=3,
        )


def _build_one_field(
    fieldname: str,
    name: str,
    valtype: str,
    dtyp_choices: list[str] | None,
    fields: RecordFieldOverrides,
    description: str,
) -> Value:
    if fieldname.endswith("$"):
        # '<FIELD>$' is a long-string alias for '<FIELD>' (see the module
        # docstring) -- delegate to build the same value, override included.
        # Only reached from DynamicRecordFields.makeChannel(), which builds
        # one field at a time on demand; build_record_fields's eager path
        # builds every "$" alias itself as a separate, non-recursive step.
        return _build_one_field(fieldname[:-1], name, valtype, dtyp_choices, fields, description)

    if fieldname == "DTYP":
        choices = list(dtyp_choices) if dtyp_choices else ["Soft Channel"]
        return _menu_pv(choices, choices[0], fields.get("DTYP"))

    if fieldname == "RTYP":
        # Inferrability is validated once by build_record_fields, not here --
        # this runs twice per add() (RTYP and RTYP$), and pv.current() isn't free.
        return _scalar_pv("s", infer_rtyp(valtype), fields.get("RTYP"))

    if fieldname == "NAME":
        # NAME always mirrors the record's own PV name -- not overridable,
        # same as dbCommon.dbd's special(SPC_NOMOD) on this field.
        return _scalar_nt("s").wrap(name)

    if fieldname == "DESC":
        # Mirrors the base PV's display.description -- not overridable via
        # `fields`, same as NAME. See the package docstring's DESC bullet.
        return _scalar_nt("s").wrap(description)

    if fieldname in ("ADEL", "MDEL"):
        # Same DBF/valtype as VAL itself (see the package docstring).
        # Callers are responsible for only requesting this when
        # _field_applies() agrees.
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
    `FIELD_NAMES` (DTYP, RTYP, NAME, DESC, the fields common to every EPICS
    record, ADEL/MDEL where `valtype` supports them, and a "<FIELD>$"
    long-string alias -- identical value to "<FIELD>" -- for each name in
    `STRING_FIELDS`).

    :param str name: The base PV name (used verbatim as the NAME field's value).
    :param str valtype: NTScalar value type code of the base PV, used to infer a
                        default RTYP (see `infer_rtyp`).
    :param list dtyp_choices: Menu choices for DTYP.  Defaults to ``["Soft Channel"]``.
    :param dict fields: Per-field overrides.  A raw value for scalar-kind fields,
                        or a choice name (str) for menu-kind fields including DTYP
                        and RTYP.  A key not in `FIELD_NAMES` is ignored (never
                        applies to any built field) and emits a `UserWarning`.
    :param pv: The base PV, if available -- used to check whether RTYP can
              plausibly be inferred (see `_check_rtyp_inferrable`); raises
              `ValueError` if not, unless `fields` gives ``"RTYP"`` explicitly.
    :param str description: The value for DESC/DESC$ -- typically the base PV's
                        own ``display.description``, if it has one (see the
                        package docstring's DESC bullet).  Not settable via
                        `fields` (same as NAME).  Defaults to ``""``.
    :returns: dict mapping field name to an initial `~p4p.Value`.  Only includes
             "ADEL"/"MDEL" when `valtype` is a plain numeric scalar code (see
             `_field_applies`) -- omitted entirely otherwise, same as the
             DBF_NOACCESS fields never appear (see the package docstring).

    Values are plain `~p4p.Value` (as built by `~p4p.nt.NTScalar.wrap`/
    `~p4p.nt.NTEnum.wrap`), suitable to pass directly as a `~p4p.server.thread.SharedPV`'s
    ``initial=``.
    """
    fields = fields or {}
    _validate_fields(fields, name)
    if pv is not None and fields.get("RTYP") is None:
        # pv is None when called from DynamicRecordFields.makeChannel() (no
        # live PV to check). Checked once here, not per-field, since RTYP
        # and RTYP$ would otherwise each re-read pv.current().
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


def _resolve_valtype_and_description(pv: _SharedPVBase, valtype: str | None) -> tuple[str, str]:
    """(valtype, description) for `pv`, applying the same inference
    `StaticRecordProvider.add`, `IOCRecordProvider.add`, and
    `IOCRecordServer`'s plain-dict shorthand all use: `valtype` falls back to
    `_infer_valtype_of_pv(pv)` (then ``'d'``) when not given explicitly;
    `description` is always a one-time snapshot of `pv`'s
    ``display.description`` (see `_description_of_pv`).
    """
    if valtype is None:
        valtype = _infer_valtype_of_pv(pv) or "d"
    return valtype, _description_of_pv(pv)
