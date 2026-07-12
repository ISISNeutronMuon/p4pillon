"""Serve per-field "sub-PVs" for the fields common to every EPICS record
(dbCommon.dbd), plus DTYP, RTYP, and NAME, mimicking the IOC/QSRV
convention where "RECORD.FIELD" resolves as its own channel independent of
the record's own value type (e.g. NTScalar for "RECORD" itself).

Unlike an IOC, a plain p4p server has no database or dbChannel layer to
parse a "RECORD.FIELD" name automatically. `IOCChannelProvider` (a
`~p4p.server.StaticProvider` subclass) and `DynamicRecordFields` (a
`~p4p.server.DynamicProvider` handler) both provide this, without adding
any of these fields to the base record's own NTScalar/NTEnum structure.

Field defaults are taken from EPICS Base wherever it defines one:
 - menu fields (SCAN, PINI, STAT, SEVR, ...) default to the same choice
   dbCommon.dbd's initial() gives a freshly iocInit'd record (e.g. STAT
   starts as "UDF", UDFS as "INVALID", ACKT as "YES"), or choice 0 where
   no initial() is declared.
 - RTYP has no single correct default (a plain p4p PV isn't really any
   EPICS record type), so it is *inferred* from the base PV's NTScalar
   value type code via `infer_rtyp` (e.g. valtype='d' suggests "ai").
   Non-scalar PVs (`~p4p.nt.NTTable`, `~p4p.nt.NTNDArray`, ...) have no
   plausible guess; `IOCChannelProvider.add` rejects these unless 'fields'
   gives 'RTYP' explicitly.
 - DTYP's choices are inherently per-record-type (they mirror whichever
   device supports were built for it), so unlike the other menu fields
   there is no global default list -- callers supply their own
   'dtyp_choices'.
 - ADEL/MDEL (archive/monitor deadband) aren't in dbCommon.dbd either --
   only record types whose VAL is a plain numeric scalar (ai, ao, calc,
   calcout, dfanout, longin, longout, int64in, int64out, sel, sub; *not*
   bi/bo/mbbi/mbbo/stringin/stringout/waveform/...) declare them, always
   with the same DBF type as VAL. So `build_record_fields` includes them
   only when `valtype` is one of those numeric codes (see
   `_field_applies`), defaulting to 0.
 - DESC always mirrors the base PV's own `display.description` sub-field
   (present only when built with e.g. ``NTScalar(..., display=True)``),
   the same way an IOC's dbChannel layer resolves "RECORD.DESC" from the
   record's own DESC member rather than a separately-settable value --
   like NAME, DESC isn't settable via 'fields'. `IOCChannelProvider.add`
   keeps DESC live as display.description changes (p4pillon-flavored base
   PVs only -- see `_DescriptionSyncHandler`); `DynamicRecordFields` only
   snapshots the registry's 'description' entry per connection. Absent a
   display.description field entirely, DESC is always "".
Any of these can be overridden via the 'fields' dict accepted by
`build_record_fields`/`IOCChannelProvider.add`, e.g.
{"SCAN": "1 second", "RTYP": "ai"}.

Every string-valued field (DESC, ASG, EVNT, TSEL, SDIS, AMSG, NAMSG, FLNK,
NAME, RTYP) is additionally servable as "<name>.<FIELD>$", returning the
same value as "<name>.<FIELD>" -- mirroring the "RECORD.FIELD$" convention
real IOCs support via dbChannelCreate() (see pvxs' ioc/channel.cpp) to
fetch a DBF_STRING field as a long string, working around Channel Access's
40-character MAX_STRING_SIZE limit. p4p/pvAccess has no such limit, so
here "$" is just an identical-valued alias, not a different wire
representation (see `STRING_FIELDS`, `_build_one_field`).

Fields with no independent external representation on a real IOC -- the
DBF_NOACCESS internals (MLOK, MLIS, BKLNK, ASP, PPN, PPNR, SPVT, RSET,
DSET, DPVT, RDES, LSET, BKPT), and TIME (DBF_NOACCESS, only reachable via
DBR_TIME_* wrapper requests, never as "RECORD.TIME") -- are intentionally
not served here, matching real IOC behaviour.

Ported from upstream p4p (epics-base/p4p, unreleased as of p4p 4.2.1) into
p4pillon so that field sub-PVs default to p4pillon's own Handler-capable
`SharedPV` (open()/post()/close() support) rather than plain p4p's.
"""

import functools
import warnings
from typing import Any, NoReturn, TypedDict

from p4p import Value
from p4p.server import StaticProvider
from p4p.server.raw import SharedPV as _SharedPVBase

from p4pillon.nt import NTEnum, NTScalar, defaultNT

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
    "IOCChannelProvider",
    "DynamicRecordFields",
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
# the module docstring and _build_one_field).  DTYP is deliberately excluded:
# it's a menu/choice field (NTEnum), not a string, despite dbCommon.dbd
# storing its choice as DBF_MENU rather than DBF_STRING either.  DESC is
# excluded from COMMON_FIELDS itself (see _build_one_field's DESC special
# case) but is still string-valued, so it's added here explicitly.
STRING_FIELDS: frozenset[str] = frozenset(
    fieldname for fieldname, spec in COMMON_FIELDS.items() if spec.get("valtype") == "s"
) | {"NAME", "RTYP", "DESC"}

# Every field name servable through build_record_fields()/IOCChannelProvider.
# ADEL/MDEL are only included when _field_applies() says so (see below).
FIELD_NAMES: frozenset[str] = (
    frozenset(COMMON_FIELDS)
    | {"DTYP", "RTYP", "NAME", "ADEL", "MDEL", "DESC"}
    | {f"{fieldname}$" for fieldname in STRING_FIELDS}
)

# Static-typing counterpart to the runtime FIELD_NAMES check (_validate_fields):
# lets a type checker (mypy/pyright) flag a typo'd key in a `fields={...}`
# literal before the code ever runs, rather than only at runtime.  TypedDict's
# functional form requires a literal dict here (mypy special-cases it and
# won't accept one built from FIELD_NAMES itself), so this must be kept in
# sync with FIELD_NAMES by hand -- guarded by
# TestRecordFieldOverridesTyping.test_matches_field_names in
# tests/unit/server/test_records.py, which fails if they ever drift apart.
# Every value is `Any`: this only catches unknown *keys*, the same thing
# _validate_fields checks -- not value-type mismatches, since a menu-kind
# field's override is a choice name (str) while a scalar-kind field's is a
# raw value matching its own valtype, i.e. no single type fits every key.
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
    (i.e. once per client connect to that record's fields), not tracked live
    the way `IOCChannelProvider.add()` tracks a base PV's display.description,
    since this registry holds no live PV reference to observe.
    """

    dtyp_choices: list[str] | None
    fields: RecordFieldOverrides
    description: str


# NTScalar type codes for which ADEL/MDEL are meaningful -- a plain numeric
# scalar (see the module docstring's ADEL/MDEL bullet). Excludes 's'
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


# Normative type IDs infer_rtyp() has no plausible guess for -- checked only
# on the _struct_id_of_current() fallback path (see documentation/nt.rst).
# Derived from p4p.nt's own structure-ID -> NT-class registry (defaultNT()),
# extended with NTTable/NTMultiChannel -- which aren't in that registry since
# they need per-instance constructor args (e.g. 'columns') and so have no
# meaningful zero-arg default -- rather than a second, independently
# hand-maintained copy of the same ID-to-NT-flavor mapping.
_NON_SCALAR_NT_IDS: frozenset[str] = frozenset(
    struct_id for struct_id, nt_cls in defaultNT().items() if nt_cls is not NTScalar
) | {
    "epics:nt/NTTable:1.0",
    "epics:nt/NTMultiChannel:1.0",
}


def _raise_rtyp_not_inferrable(desc: str) -> NoReturn:
    raise ValueError(f"Cannot infer RTYP for {desc}; pass fields={{'RTYP': ...}} explicitly.")


def _raw_current_or_none(pv: _SharedPVBase) -> Any | None:
    # Best-effort raw Value of pv's live current(), for when pv.nt is None (a
    # hand-built PV using a plain Value, or wrap=/unwrap() were used instead).
    # None means "unknown" (not open()'d yet, or pv.current() itself failed)
    # -- shared by _struct_id_of_current and _description_of_pv's slow path,
    # both of which need the same "fetch current(), unwrap .raw" step.
    try:
        current = pv.current()
    except Exception:
        return None
    return getattr(current, "raw", current)


def _struct_id_of_current(pv: _SharedPVBase) -> str | None:
    # Best-effort structure ID of pv's live Value, for when pv.nt is None.
    # None means "unknown" -- never treated as "confirmed scalar".
    raw = _raw_current_or_none(pv)
    if raw is None:
        return None
    return getattr(raw, "getID", lambda: None)()


def _check_rtyp_inferrable(pv: _SharedPVBase) -> None:
    # Fast path: pv.nt tells us the PV's actual type with no further access.
    nt = getattr(pv, "nt", None)
    if nt is not None:
        if not isinstance(nt, NTScalar):
            _raise_rtyp_not_inferrable(f"a {type(nt).__name__}-backed PV")
        return

    # Slow path: pv.nt is None (hand-built with a plain Value, or
    # wrap=/unwrap= was used) -- fall back to the live Value's structure ID.
    struct_id = _struct_id_of_current(pv)
    if struct_id in _NON_SCALAR_NT_IDS:
        _raise_rtyp_not_inferrable(f"a {struct_id}-shaped PV")


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
        # `fields`, same as NAME. See the module docstring's DESC bullet.
        return _scalar_nt("s").wrap(description)

    if fieldname in ("ADEL", "MDEL"):
        # Same DBF/valtype as VAL itself (see the module docstring).
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
                        module docstring's DESC bullet).  Not settable via
                        `fields` (same as NAME).  Defaults to ``""``.
    :returns: dict mapping field name to an initial `~p4p.Value`.  Only includes
             "ADEL"/"MDEL" when `valtype` is a plain numeric scalar code (see
             `_field_applies`) -- omitted entirely otherwise, same as the
             DBF_NOACCESS fields never appear (see the module docstring).

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


def _description_of_pv(pv: _SharedPVBase) -> tuple[str, bool]:
    # Returns (description, has_description_field). has_description_field is
    # False whenever the PV's structure has no display.description at all
    # (the common case) -- DESC is then permanently "" and
    # IOCChannelProvider.add() need not install _DescriptionSyncHandler.

    # Fast path: pv.nt tells us whether display.description is even
    # structurally possible with no further access (same rationale as
    # _check_rtyp_inferrable's fast path).
    nt = getattr(pv, "nt", None)
    if nt is not None and "display.description" not in nt.type:
        return "", False

    # Slow path: pv.nt confirmed display.description exists (needs a
    # pv.current() read), or pv.nt is None (hand-built PV) and there's no
    # way to tell without looking at the live Value.
    raw = _raw_current_or_none(pv)
    if raw is None:
        return "", False
    try:
        if "display.description" not in raw:
            return "", False
        return raw.get("display.description", "") or "", True
    except TypeError:
        # raw isn't Value-like (e.g. a hand-rolled unwrap= returning
        # something else) -- give up gracefully, same as above.
        return "", False


@functools.cache
def _patched_shared_pv_cls() -> type:
    # Lazy + cached, same rationale as _default_pv_factory: avoid a hard
    # dependency on p4pillon.server.raw for callers who only want
    # build_record_fields(), without re-importing on every call.
    from p4pillon.server.raw import SharedPV as _PatchedSharedPV

    return _PatchedSharedPV


def _supports_handler_hooks(pv: _SharedPVBase) -> bool:
    # Only p4pillon's raw.SharedPV (thread/asyncio flavors) calls
    # self._handler.open()/post() (a p4p PR #172 patch) -- a plain p4p
    # SharedPV (e.g. p4p.server.thread.SharedPV, unpatched) has no hook to
    # observe post()s on at all.
    return isinstance(pv, _patched_shared_pv_cls())


class _DescriptionSyncHandler:
    """Wraps a base PV's handler (see `IOCChannelProvider.add`) so every
    open()/post() also mirrors display.description onto its ".DESC"/".DESC$"
    sub-PVs, matching pvxs' dbChannel behaviour where RECORD.DESC and
    display.description are the same field (see `_build_one_field`'s DESC
    case). Delegates every other hook to the original handler unchanged.
    Only installed when the base PV has display.description
    (`_description_of_pv`) and supports these hooks (`_supports_handler_hooks`);
    `IOCChannelProvider.remove` restores the original handler afterward.
    """

    def __init__(self, real: Any, desc_pv: _SharedPVBase, desc_dollar_pv: _SharedPVBase):
        self._real = real
        self._desc_pv = desc_pv
        self._desc_dollar_pv = desc_dollar_pv

    def _sync(self, value: Value) -> None:
        # value may only carry a subset of fields (a post() only sets changed
        # ones), so display.description must be checked via .changed() rather
        # than assumed present -- otherwise an unrelated post() (e.g. a bare
        # `pv.post(1.0)`) would read back "" and wrongly blank out DESC.
        try:
            changed = value.changed("display.description")
        except KeyError:
            return
        if not changed:
            return
        wrapped = _scalar_nt("s").wrap(value.get("display.description", "") or "")
        self._desc_pv.post(wrapped)
        self._desc_dollar_pv.post(wrapped)

    def _delegate(self, hook_name: str, *args: Any) -> None:
        # Tolerates a handler that omits a hook, same pattern
        # p4pillon.server.raw.SharedPV itself uses.
        try:
            hook = getattr(self._real, hook_name)
        except AttributeError:
            return
        hook(*args)

    def open(self, value: Value) -> None:
        self._sync(value)
        self._delegate("open", value)

    def post(self, pv: _SharedPVBase, value: Value) -> None:
        self._sync(value)
        self._delegate("post", pv, value)

    def close(self, pv: _SharedPVBase) -> None:
        self._delegate("close", pv)


class IOCChannelProvider(StaticProvider):
    """A `~p4p.server.StaticProvider` which, in addition to serving each added PV
    under its own name, also serves "<name>.<FIELD>" as independent read-only
    channels for DTYP, RTYP, NAME, the fields common to every EPICS record
    (dbCommon.dbd), and ADEL/MDEL where `valtype` supports them -- without adding
    any of those fields to the PV's own NTScalar or NTEnum structure. ::

        from p4p.nt import NTScalar
        from p4p.server import Server
        from p4pillon.server.thread import SharedPV
        from p4pillon.server.records import IOCChannelProvider

        provider = IOCChannelProvider("example")
        provider.add("EXAMPLE:PV",
                     SharedPV(nt=NTScalar("d", display=True),
                              initial={"value": 1.234,
                                       "display": {"description": "An example ai-like record"}}),
                     dtyp_choices=["Soft Channel", "Raw Soft Channel"],
                     fields={"SCAN": "1 second"})

        with Server(providers=[provider]):
            ...

    See the `p4pillon.server.records` module docstring for the rationale behind each
    field's default, and `build_record_fields` for the meaning of `dtyp_choices`
    and `fields`.

    Each "<name>.<FIELD>" sub-PV is built using ``type(pv)`` -- the same
    `~p4pillon.server.thread.SharedPV` or `~p4pillon.server.asyncio.SharedPV`
    class as the base PV passed to `add` -- so it automatically uses the same
    concurrency model.

    DESC/DESC$ are seeded from the base PV's ``display.description`` at
    `add()` time -- a one-time snapshot by default.  Ongoing live tracking
    (mirroring later ``pv.post(...)`` changes onto DESC/DESC$) is opt-in via
    `sync_description`, either as this constructor's default for every `add()`
    call or overridden per-PV in `add()` itself, and is only possible at all
    for a p4pillon-flavored base PV (`~p4pillon.server.thread.SharedPV`/
    `~p4pillon.server.asyncio.SharedPV`); a plain, non-p4pillon flavor (e.g.
    `~p4p.server.thread.SharedPV`, unpatched) has no hook to observe post()s
    on at all, so it stays a snapshot regardless (a `UserWarning` is emitted
    when live tracking was requested but isn't possible).  See
    `_DescriptionSyncHandler`.
    """

    def __init__(self, name: str | None = None, sync_description: bool = False):
        """
        :param sync_description: Default for `add`'s `sync_description` when
                                 not overridden there -- whether DESC/DESC$
                                 should keep tracking the base PV's
                                 display.description live after `add()`, vs.
                                 just a one-time snapshot taken at `add()`
                                 time.  Off by default.
        """
        super().__init__(name)
        # name -> the field names actually added for it (not always
        # FIELD_NAMES in full -- e.g. ADEL/MDEL are omitted for a non-numeric
        # valtype, see build_record_fields), so remove() only ever removes
        # sub-PVs that were actually added.
        self._recorded: dict[str, frozenset[str]] = {}
        # name -> (pv, pv's original handler), only for records where
        # _DescriptionSyncHandler was installed -- so remove() can restore
        # the original handler rather than leaving pv wrapped (and the DESC/
        # DESC$ sub-PVs it references unreachably retained) forever.
        self._description_sync: dict[str, tuple[_SharedPVBase, Any]] = {}
        self._sync_description_default = sync_description

    def add(
        self,
        name: str,
        pv: _SharedPVBase,
        valtype: str | None = None,
        dtyp_choices: list[str] | None = None,
        fields: RecordFieldOverrides | None = None,
        record_fields: bool = True,
        sync_description: bool | None = None,
    ) -> None:
        """Add a PV, and (unless `record_fields` is False) its "<name>.<FIELD>"
        sub-PVs.

        :param str valtype: NTScalar value type code matching whatever `pv` was
                            itself constructed with (e.g. ``NTScalar('d')`` ->
                            ``valtype='d'``).  Only used to infer a default RTYP;
                            does not need to be exact if RTYP is overridden via
                            `fields` or `record_fields=False`.  Left as `None`
                            (the default), it's inferred from `pv.nt` when that's
                            an NTScalar (see `_infer_valtype_of_pv`) -- the common
                            case, since that's how `pv` was actually built; falls
                            back to ``'d'`` (matching `~p4p.nt.NTScalar`'s own
                            default) only when it can't be, e.g. a hand-built `pv`
                            using `wrap=`/`unwrap=` instead of `nt=`.
        :param sync_description: Whether DESC/DESC$ should keep tracking `pv`'s
                                 display.description live after this call, vs.
                                 just a one-time snapshot taken now.  Left as
                                 `None` (the default), the constructor's
                                 `sync_description` applies instead.

        See `build_record_fields` for `dtyp_choices`, `fields`, and how RTYP
        inference is rejected for a non-scalar `pv`.
        """
        super().add(name, pv)
        if not record_fields:
            return

        if valtype is None:
            valtype = _infer_valtype_of_pv(pv) or "d"

        description, has_description = _description_of_pv(pv)
        built = build_record_fields(
            name, valtype, dtyp_choices=dtyp_choices, fields=fields, pv=pv, description=description
        )
        field_pvs: dict[str, _SharedPVBase] = {}
        for fieldname, value in built.items():
            field_pv = _field_shared_pv(value, type(pv))
            super().add(f"{name}.{fieldname}", field_pv)
            field_pvs[fieldname] = field_pv
        self._recorded[name] = frozenset(built)

        if has_description:
            want_sync = self._sync_description_default if sync_description is None else sync_description
            if want_sync:
                if _supports_handler_hooks(pv):
                    original_handler = pv._handler
                    pv._handler = _DescriptionSyncHandler(original_handler, field_pvs["DESC"], field_pvs["DESC$"])
                    self._description_sync[name] = (pv, original_handler)
                else:
                    warnings.warn(
                        f"{name!r}'s base PV has a display.description but is not a "
                        "p4pillon-flavored SharedPV, so its .DESC/.DESC$ will not track "
                        "display.description changes made after add() -- only "
                        "p4pillon.server.thread.SharedPV and p4pillon.server.asyncio.SharedPV "
                        "support this (see IOCChannelProvider's docstring).",
                        stacklevel=2,
                    )

    def remove(self, name: str) -> None:
        """Remove a PV, and any "<name>.<FIELD>" sub-PVs previously added for it."""
        fieldnames = self._recorded.pop(name, None)
        if fieldnames is not None:
            for fieldname in fieldnames:
                super().remove(f"{name}.{fieldname}")
        sync_entry = self._description_sync.pop(name, None)
        if sync_entry is not None:
            pv, original_handler = sync_entry
            pv._handler = original_handler
        super().remove(name)


class DynamicRecordFields:
    """A `~p4p.server.DynamicProvider` handler serving "<name>.<FIELD>" for base PV
    names known to a `registry`, building each field PV lazily on demand rather than
    eagerly for every record up front (unlike `IOCChannelProvider`). ::

        from p4p.server import DynamicProvider
        from p4pillon.server.records import DynamicRecordFields

        registry = {
            "EXAMPLE:PV": {"valtype": "d", "dtyp_choices": ["Soft Channel"], "fields": {}},
        }
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

    :param registry: A mapping of base PV name to a dict with keys 'valtype'
                     (required), 'dtyp_choices', 'fields', and 'description'
                     (all optional).  See `build_record_fields`.  Each entry's
                     'fields' is validated against `FIELD_NAMES` eagerly here, at
                     construction time -- same `UserWarning` on an
                     unrecognized key as `build_record_fields`, but emitted
                     immediately rather than only when/if a client happens to
                     connect to that particular record's fields (this class
                     otherwise builds each field PV lazily, on demand).
                     'description' (DESC/DESC$'s value) is a snapshot only,
                     re-read from the registry once per `makeChannel()` call --
                     unlike `IOCChannelProvider`, this class has no live PV
                     reference to track display.description changes with (see
                     `RegistryEntry`).
    :param pv_factory: Callable used to construct each "<name>.<FIELD>" sub-PV,
                       called as ``pv_factory(initial=value)``.  Defaults to
                       `~p4pillon.server.thread.SharedPV`.  A plain, unpatched
                       `~p4p.server.thread.SharedPV` is also safe here.

                       `~p4pillon.server.asyncio.SharedPV` is rejected at construction time
                       (raises `ValueError`): `makeChannel` is called by the server's
                       own internal I/O thread, never the thread actually running the
                       asyncio event loop, and `asyncio.SharedPV.__init__` requires a
                       running loop *on the calling thread* -- it would raise
                       ``RuntimeError: no running event loop`` on every channel
                       creation.  (`IOCChannelProvider` does not have this restriction,
                       since its ``add()`` is called directly by user code, which for
                       asyncio users naturally runs inside a coroutine.)
    """

    def __init__(
        self,
        registry: dict[str, RegistryEntry],
        pv_factory: type[_SharedPVBase] | None = None,
    ) -> None:
        if pv_factory is not None:
            _check_pv_factory_is_safe(pv_factory)
        for name, entry in registry.items():
            _validate_fields(entry.get("fields") or {}, name)
        self._registry: dict[str, RegistryEntry] = registry
        self._pv_factory: type[_SharedPVBase] | None = pv_factory

    def testChannel(self, name: str) -> bool:
        basename, field = _split_field_name(name)
        if field is None:
            return False
        entry = self._registry.get(basename)
        if entry is None:
            return False
        return _field_applies(field, entry["valtype"])

    def makeChannel(self, name: str, peer: str) -> _SharedPVBase | None:
        basename, field = _split_field_name(name)
        if field is None:
            return None
        entry = self._registry.get(basename)
        if entry is None or not _field_applies(field, entry["valtype"]):
            return None
        value = _build_one_field(
            field,
            basename,
            entry["valtype"],
            entry.get("dtyp_choices"),
            entry.get("fields") or {},
            entry.get("description") or "",
        )
        return _field_shared_pv(value, self._pv_factory)


def _split_field_name(name: str) -> tuple[str, str | None]:
    # Returns (basename, field) if `name` is "<basename>.<FIELD>" for a
    # known field, else (name, None).
    basename, sep, field = name.rpartition(".")
    if not sep or field not in FIELD_NAMES:
        return name, None
    return basename, field


def _check_pv_factory_is_safe(pv_factory: type[_SharedPVBase]) -> None:
    # See DynamicRecordFields' docstring for why a loop-requiring pv_factory
    # can never work here. Detected via the `_requires_running_loop` trait
    # (set on p4pillon.server.asyncio.SharedPV) so any future loop-requiring
    # flavor is caught the same way, at construction time rather than deep
    # inside a server callback.
    if isinstance(pv_factory, type) and getattr(pv_factory, "_requires_running_loop", False):
        raise ValueError(
            f"pv_factory={pv_factory.__name__} is not safe for DynamicRecordFields: makeChannel() is "
            "always called by the server's own internal thread, never the thread "
            "running an asyncio event loop, so it can never construct one. Use "
            "p4pillon.server.thread.SharedPV (the default) instead."
        )


@functools.cache
def _default_pv_factory() -> type[_SharedPVBase]:
    # Lazy + cached: importing p4pillon.server.thread at module scope would
    # force a hard dependency on it for callers who only use
    # build_record_fields() or always pass their own pv_factory.
    from p4pillon.server.thread import SharedPV

    return SharedPV


def _field_shared_pv(value: Value, pv_factory: type[_SharedPVBase] | None = None) -> _SharedPVBase:
    return (pv_factory or _default_pv_factory())(initial=value)
