"""Serve per-field "sub-PVs" for the fields common to every EPICS record
(dbCommon.dbd), plus DTYP, RTYP, and NAME, mimicking the IOC/QSRV
convention where "RECORD.FIELD" resolves as its own channel independent of
the record's own value type (e.g. NTScalar for "RECORD" itself).

Unlike an IOC, a plain p4p server has no database and no dbChannel layer to
parse a "RECORD.FIELD" name automatically. `RecordProvider` (a
`~p4p.server.StaticProvider` subclass) and `DynamicRecordFields` (a
`~p4p.server.DynamicProvider` handler) both provide this, without ever
adding any of these fields to the base record's own NTScalar/NTEnum
structure.

Field defaults are taken from EPICS Base wherever it defines one:
 - menu fields (SCAN, PINI, STAT, SEVR, ...) default to the same choice
   dbCommon.dbd's initial() gives a freshly iocInit'd record (e.g. STAT
   starts as "UDF", UDFS as "INVALID", ACKT as "YES"), or choice 0 where
   no initial() is declared.
 - RTYP has no single correct default (a plain p4p PV isn't really any
   EPICS record type), so it is *inferred* from the base PV's own NTScalar
   value type code via `infer_rtyp` -- e.g. valtype='d' suggests "ai".
   Non-scalar PVs (e.g. `~p4p.nt.NTTable`, `~p4p.nt.NTNDArray`) have no
   plausible guess; `RecordProvider.add` detects and rejects these unless
   'fields' gives 'RTYP' explicitly (see `infer_rtyp`).
 - DTYP's choices are inherently per-record-type (they mirror whichever
   device supports were built for that record type), so unlike the other
   menu fields there is no global default list -- callers supply their own
   'dtyp_choices'.
 - ADEL/MDEL (archive/monitor deadband) are not declared in dbCommon.dbd
   either -- only record types whose VAL is a plain numeric scalar (ai, ao,
   calc, calcout, dfanout, longin, longout, int64in, int64out, sel, sub;
   *not* bi/bo/mbbi/mbbo/stringin/stringout/waveform/...) declare them, and
   always with the same DBF type as VAL itself. So unlike DTYP/RTYP/NAME,
   they are not unconditionally part of `FIELD_NAMES`' output: whether
   `build_record_fields` includes them is inferred straight from `valtype`
   (see `_field_applies`), defaulting to 0, same DBF/valtype as the base PV.
Any of these can be overridden via the 'fields' dict accepted by
`build_record_fields`/`RecordProvider.add`, e.g.
{"DESC": "...", "SCAN": "1 second", "RTYP": "ai"}.

Every string-valued field (DESC, ASG, EVNT, TSEL, SDIS, AMSG, NAMSG, FLNK,
NAME, RTYP) is additionally servable as "<name>.<FIELD>$", returning exactly
the same value as "<name>.<FIELD>" itself -- mirroring the "RECORD.FIELD$"
convention real IOCs support via dbChannelCreate() (see pvxs' ioc/channel.cpp)
to fetch a DBF_STRING field as a long string/char array, working around
Channel Access's 40-character MAX_STRING_SIZE scalar-string limit. p4p/pvAccess
has no such limit, so here "$" is simply an identical-valued alias rather than
a different wire representation (see `STRING_FIELDS`, `_build_one_field`).

Fields with no independent external representation on a real IOC -- the
DBF_NOACCESS internals (MLOK, MLIS, BKLNK, ASP, PPN, PPNR, SPVT, RSET,
DSET, DPVT, RDES, LSET, BKPT), and TIME, which is DBF_NOACCESS and only
reachable via DBR_TIME_* wrapper requests, never as "RECORD.TIME" -- are
intentionally not served here, matching real IOC behaviour.

Ported from upstream p4p (epics-base/p4p, unreleased as of p4p 4.2.1) into
p4pillon so that field sub-PVs built without an explicit `pv_factory`/
`record_fields` PV class default to p4pillon's own Handler-capable
`SharedPV` (open()/post()/close() support) rather than plain p4p's.
"""

import functools

from p4p.server import StaticProvider

from p4pillon.nt import NTEnum, NTScalar, defaultNT

__all__ = (
    'MENU_SCAN',
    'MENU_PINI',
    'MENU_PRIORITY',
    'MENU_ALARM_STAT',
    'MENU_ALARM_SEVR',
    'MENU_YES_NO',
    'COMMON_FIELDS',
    'STRING_FIELDS',
    'FIELD_NAMES',
    'infer_rtyp',
    'build_record_fields',
    'RecordProvider',
    'DynamicRecordFields',
)

# --- menu choice lists, copied verbatim from EPICS Base's dbd/menu*.dbd,
#     in declaration order (the order fixes each choice's index) ---

MENU_SCAN = [
    "Passive", "Event", "I/O Intr",
    "10 second", "5 second", "2 second", "1 second",
    ".5 second", ".2 second", ".1 second",
]
MENU_PINI = ["NO", "YES", "RUN", "RUNNING", "PAUSE", "PAUSED"]
MENU_PRIORITY = ["LOW", "MEDIUM", "HIGH"]
MENU_ALARM_STAT = [
    "NO_ALARM", "READ", "WRITE", "HIHI", "HIGH", "LOLO", "LOW", "STATE",
    "COS", "COMM", "TIMEOUT", "HWLIMIT", "CALC", "SCAN", "LINK", "SOFT",
    "BAD_SUB", "UDF", "DISABLE", "SIMM", "READ_ACCESS", "WRITE_ACCESS",
]
MENU_ALARM_SEVR = ["NO_ALARM", "MINOR", "MAJOR", "INVALID"]
MENU_YES_NO = ["NO", "YES"]

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

COMMON_FIELDS = {
    "DESC":  {"valtype": "s", "default": ""},
    "ASG":   {"valtype": "s", "default": ""},
    "SCAN":  {"choices": MENU_SCAN, "default": "Passive"},
    "PINI":  {"choices": MENU_PINI, "default": "NO"},
    "PHAS":  {"valtype": "h", "default": 0},
    "EVNT":  {"valtype": "s", "default": ""},
    "TSE":   {"valtype": "h", "default": 0},
    "TSEL":  {"valtype": "s", "default": ""},
    "DISV":  {"valtype": "h", "default": 1},
    "DISA":  {"valtype": "h", "default": 0},
    "SDIS":  {"valtype": "s", "default": ""},
    "DISP":  {"valtype": "B", "default": 0},
    "PROC":  {"valtype": "B", "default": 0},
    "STAT":  {"choices": MENU_ALARM_STAT, "default": "UDF"},
    "SEVR":  {"choices": MENU_ALARM_SEVR, "default": "NO_ALARM"},
    "AMSG":  {"valtype": "s", "default": ""},
    "NSTA":  {"choices": MENU_ALARM_STAT, "default": "NO_ALARM"},
    "NSEV":  {"choices": MENU_ALARM_SEVR, "default": "NO_ALARM"},
    "NAMSG": {"valtype": "s", "default": ""},
    "ACKS":  {"choices": MENU_ALARM_SEVR, "default": "NO_ALARM"},
    "ACKT":  {"choices": MENU_YES_NO, "default": "YES"},
    "DISS":  {"choices": MENU_ALARM_SEVR, "default": "NO_ALARM"},
    "LCNT":  {"valtype": "B", "default": 0},
    "PACT":  {"valtype": "B", "default": 0},
    "PUTF":  {"valtype": "B", "default": 0},
    "RPRO":  {"valtype": "B", "default": 0},
    "PRIO":  {"choices": MENU_PRIORITY, "default": "LOW"},
    "TPRO":  {"valtype": "B", "default": 0},
    "UDF":   {"valtype": "B", "default": 1},
    "UDFS":  {"choices": MENU_ALARM_SEVR, "default": "INVALID"},
    "UTAG":  {"valtype": "L", "default": 0},
    "FLNK":  {"valtype": "s", "default": ""},
}

# String-valued field names -- each gets a "<FIELD>$" long-string alias (see
# the module docstring and _build_one_field).  DTYP is deliberately excluded:
# it's a menu/choice field (NTEnum), not a string, despite dbCommon.dbd
# storing its choice as DBF_MENU rather than DBF_STRING either.
STRING_FIELDS = frozenset(
    fieldname for fieldname, spec in COMMON_FIELDS.items() if spec.get("valtype") == "s"
) | {"NAME", "RTYP"}

# Every field name servable through build_record_fields()/RecordProvider.
# ADEL/MDEL are only actually included for a given PV when _field_applies()
# says so (see below) -- unlike every other name here, they are not part of
# every record type.
FIELD_NAMES = (frozenset(COMMON_FIELDS) | {"DTYP", "RTYP", "NAME", "ADEL", "MDEL"}
               | {f"{fieldname}$" for fieldname in STRING_FIELDS})

# NTScalar type codes ADEL/MDEL are meaningful for: a plain numeric scalar,
# same set of codes real record types declare them with (DBF_DOUBLE,
# DBF_LONG, DBF_INT64, ...) -- see documentation/values.rst for the code
# table.  Excludes 's' (string), '?' (bool), and array codes ('a' + one of
# these) -- no real record type of those kinds has ADEL/MDEL.
_ADEL_MDEL_VALTYPES = frozenset("bBhHiIlLfd")


def _field_applies(fieldname, valtype):
    """Whether `fieldname` is meaningful for a base PV of the given `valtype`.

    True for every field name except ADEL/MDEL, which are only meaningful for
    a plain numeric scalar `valtype` (see `_ADEL_MDEL_VALTYPES`) -- e.g. an
    NTEnum- or NTTable-shaped or string-valued PV has neither on a real IOC.
    """
    if fieldname in ("ADEL", "MDEL"):
        return valtype in _ADEL_MDEL_VALTYPES
    return True


def infer_rtyp(valtype):
    """Guess a plausible RTYP from an NTScalar value type code.  Only used
    when a 'fields' override does not set 'RTYP' explicitly, and only when
    the base PV is actually NTScalar-shaped -- enforced by
    `_check_rtyp_inferrable`, since e.g. `~p4p.nt.NTTable`/`~p4p.nt.NTNDArray`
    have no plausible guess (real IOCs have no "table" record type either;
    pvxs' own NTTable support composes one from several aai/aao array
    records rather than a single record type).
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


# Every menu-kind field shares the same NTEnum schema (only 'choices', a data
# value not a type parameter, differs between them), and every scalar-kind
# field reuses one of a handful of NTScalar valtypes -- so a single instance
# per schema is built lazily and reused, rather than reparsing the same
# pvxs structure definition on every field/PV/connection.
_menu_nt = NTEnum()


@functools.cache
def _scalar_nt(valtype):
    return NTScalar(valtype)


def _menu_pv(choices, default_name, override):
    return _menu_nt.wrap(default_name if override is None else override, choices=choices)


def _scalar_pv(valtype, default, override):
    return _scalar_nt(valtype).wrap(default if override is None else override)


# Normative type IDs infer_rtyp() has no plausible guess for -- checked only
# on the _struct_id_of_current() fallback path (see documentation/nt.rst).
# Derived from p4p.nt's own structure-ID -> NT-class registry (defaultNT()),
# extended with NTTable/NTMultiChannel -- which aren't in that registry since
# they need per-instance constructor args (e.g. 'columns') and so have no
# meaningful zero-arg default -- rather than a second, independently
# hand-maintained copy of the same ID-to-NT-flavor mapping.
_NON_SCALAR_NT_IDS = frozenset(
    struct_id for struct_id, nt_cls in defaultNT().items() if nt_cls is not NTScalar
) | {
    "epics:nt/NTTable:1.0",
    "epics:nt/NTMultiChannel:1.0",
}


def _raise_rtyp_not_inferrable(desc):
    raise ValueError(
        f"Cannot infer RTYP for {desc}; pass fields={{'RTYP': ...}} explicitly.")


def _struct_id_of_current(pv):
    # Best-effort structure ID of pv's live Value, for when pv.nt is None.
    # None means "unknown" (not open()'d yet, or an unrecognizable
    # wrap=/unwrap= result) -- never treated as "confirmed scalar".
    try:
        current = pv.current()
    except Exception:
        return None
    raw = getattr(current, "raw", current)
    return getattr(raw, "getID", lambda: None)()


def _check_rtyp_inferrable(pv):
    # Fast path: `pv.nt` (set by SharedPV(nt=...), any flavor, even before
    # open()) tells us the PV's actual type with no further access -- covers
    # the common case, no fallback needed.
    nt = getattr(pv, "nt", None)
    if nt is not None:
        if not isinstance(nt, NTScalar):
            _raise_rtyp_not_inferrable(f"a {type(nt).__name__}-backed PV")
        return

    # Slow path: pv.nt is None (a hand-built PV using a plain Value, or
    # wrap=/unwrap= callables were used instead -- see :ref:`unwrap` in
    # nt.rst); fall back to the live Value's own structure ID.
    struct_id = _struct_id_of_current(pv)
    if struct_id in _NON_SCALAR_NT_IDS:
        _raise_rtyp_not_inferrable(f"a {struct_id}-shaped PV")


def _build_one_field(fieldname, name, valtype, dtyp_choices, fields):
    if fieldname.endswith("$"):
        # '<FIELD>$' is a long-string alias for '<FIELD>' (see the module
        # docstring) -- always exactly the value '<FIELD>' itself would
        # build, override included, so simply delegate.  Only ever reached
        # for names in STRING_FIELDS (FIELD_NAMES only has a "$" entry for
        # those), so the stripped name is always a real string-kind field.
        return _build_one_field(fieldname[:-1], name, valtype, dtyp_choices, fields)

    if fieldname == "DTYP":
        choices = list(dtyp_choices) if dtyp_choices else ["Soft Channel"]
        return _menu_pv(choices, choices[0], fields.get("DTYP"))

    if fieldname == "RTYP":
        # RTYP-inferrability (when there's a live `pv` to check) is validated
        # once by the caller (`build_record_fields`), not here -- this can be
        # reached twice per `add()` call (once for "RTYP", once for its "RTYP$"
        # alias), and pv.current() isn't free.
        return _scalar_pv("s", infer_rtyp(valtype), fields.get("RTYP"))

    if fieldname == "NAME":
        # NAME always mirrors the record's own PV name -- not overridable,
        # same as dbCommon.dbd's special(SPC_NOMOD) on this field.
        return _scalar_nt("s").wrap(name)

    if fieldname in ("ADEL", "MDEL"):
        # Same DBF/valtype as the base PV's own VAL -- real record types
        # declare these two with whatever numeric type VAL itself is (see
        # the module docstring).  Caller is responsible for only requesting
        # this when _field_applies() agrees (checked by build_record_fields
        # and DynamicRecordFields, not here, since callers of
        # _build_one_field always already know).
        return _scalar_pv(valtype, 0, fields.get(fieldname))

    spec = COMMON_FIELDS[fieldname]
    override = fields.get(fieldname)
    if "choices" in spec:
        return _menu_pv(spec["choices"], spec["default"], override)
    return _scalar_pv(spec["valtype"], spec["default"], override)


def build_record_fields(name, valtype, dtyp_choices=None, fields=None, pv=None):
    """Build the "<name>.<FIELD>" values for every applicable field in
    `FIELD_NAMES` (DTYP, RTYP, NAME, the fields common to every EPICS record,
    ADEL/MDEL where `valtype` supports them, and a "<FIELD>$" long-string
    alias -- identical value to "<FIELD>" -- for each name in `STRING_FIELDS`).

    :param str name: The base PV name (used verbatim as the NAME field's value).
    :param str valtype: NTScalar value type code of the base PV, used to infer a
                        default RTYP (see `infer_rtyp`).
    :param list dtyp_choices: Menu choices for DTYP.  Defaults to ``["Soft Channel"]``.
    :param dict fields: Per-field overrides.  A raw value for scalar-kind fields,
                        or a choice name (str) for menu-kind fields including DTYP
                        and RTYP.
    :param pv: The base PV, if available -- used to check whether RTYP can
              plausibly be inferred (see `_check_rtyp_inferrable`); raises
              `ValueError` if not, unless `fields` gives ``"RTYP"`` explicitly.
    :returns: dict mapping field name to an initial `~p4p.Value`.  Only includes
             "ADEL"/"MDEL" when `valtype` is a plain numeric scalar code (see
             `_field_applies`) -- omitted entirely otherwise, same as the
             DBF_NOACCESS fields never appear (see the module docstring).

    Values are plain `~p4p.Value` (as built by `~p4p.nt.NTScalar.wrap`/
    `~p4p.nt.NTEnum.wrap`), suitable to pass directly as a `~p4p.server.thread.SharedPV`'s
    ``initial=``.
    """
    fields = fields or {}
    if pv is not None and fields.get("RTYP") is None:
        # pv is None when called from DynamicRecordFields.makeChannel(), which
        # has no live PV instance to check -- nothing to infer from.  Checked
        # once here rather than per-field, since "RTYP" and its "RTYP$" alias
        # would otherwise each independently re-read pv.current().
        _check_rtyp_inferrable(pv)
    return {fieldname: _build_one_field(fieldname, name, valtype, dtyp_choices, fields)
            for fieldname in FIELD_NAMES if _field_applies(fieldname, valtype)}


class RecordProvider(StaticProvider):
    """A `~p4p.server.StaticProvider` which, in addition to serving each added PV
    under its own name, also serves "<name>.<FIELD>" as independent read-only
    channels for DTYP, RTYP, NAME, the fields common to every EPICS record
    (dbCommon.dbd), and ADEL/MDEL where `valtype` supports them -- without adding
    any of those fields to the PV's own NTScalar or NTEnum structure. ::

        from p4p.nt import NTScalar
        from p4p.server import Server
        from p4pillon.server.thread import SharedPV
        from p4pillon.server.records import RecordProvider

        provider = RecordProvider("example")
        provider.add("EXAMPLE:PV", SharedPV(nt=NTScalar("d"), initial=1.234),
                     dtyp_choices=["Soft Channel", "Raw Soft Channel"],
                     fields={"DESC": "An example ai-like record", "SCAN": "1 second"})

        with Server(providers=[provider]):
            ...

    See the `p4pillon.server.records` module docstring for the rationale behind each
    field's default, and `build_record_fields` for the meaning of `dtyp_choices`
    and `fields`.

    Each "<name>.<FIELD>" sub-PV is built using ``type(pv)`` -- the same
    `~p4pillon.server.thread.SharedPV`, `~p4pillon.server.asyncio.SharedPV`, or
    `~p4p.server.cothread.SharedPV` class as the base PV passed to `add` --
    so it automatically uses the same concurrency model.
    """

    def __init__(self, name=None):
        super().__init__(name)
        # name -> the field names actually added for it (not always
        # FIELD_NAMES in full -- e.g. ADEL/MDEL are omitted for a non-numeric
        # valtype, see build_record_fields), so remove() only ever removes
        # sub-PVs that were actually added.
        self._recorded = {}

    def add(self, name, pv, valtype='d', dtyp_choices=None, fields=None, record_fields=True):
        """Add a PV, and (unless `record_fields` is False) its "<name>.<FIELD>"
        sub-PVs.

        :param str valtype: NTScalar value type code matching whatever `pv` was
                            itself constructed with (e.g. ``NTScalar('d')`` ->
                            ``valtype='d'``).  Only used to infer a default RTYP;
                            does not need to be exact if RTYP is overridden via
                            `fields` or `record_fields=False`.

        See `build_record_fields` for `dtyp_choices`, `fields`, and how RTYP
        inference is rejected for a non-scalar `pv`.
        """
        super().add(name, pv)
        if not record_fields:
            return

        built = build_record_fields(name, valtype, dtyp_choices=dtyp_choices, fields=fields, pv=pv)
        for fieldname, value in built.items():
            super().add(f"{name}.{fieldname}",
                                             _field_shared_pv(value, type(pv)))
        self._recorded[name] = frozenset(built)

    def remove(self, name):
        """Remove a PV, and any "<name>.<FIELD>" sub-PVs previously added for it."""
        fieldnames = self._recorded.pop(name, None)
        if fieldnames is not None:
            for fieldname in fieldnames:
                super().remove(f"{name}.{fieldname}")
        super().remove(name)


class DynamicRecordFields:
    """A `~p4p.server.DynamicProvider` handler serving "<name>.<FIELD>" for base PV
    names known to a `registry`, building each field PV lazily on demand rather than
    eagerly for every record up front (unlike `RecordProvider`). ::

        from p4p.server import DynamicProvider
        from p4pillon.server.records import DynamicRecordFields

        registry = {
            "EXAMPLE:PV": {"valtype": "d", "dtyp_choices": ["Soft Channel"], "fields": {}},
        }
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

    :param registry: A mapping of base PV name to a dict with keys 'valtype'
                     (required), 'dtyp_choices' and 'fields' (both optional).
                     See `build_record_fields`.
    :param pv_factory: Callable used to construct each "<name>.<FIELD>" sub-PV,
                       called as ``pv_factory(initial=value)``.  Defaults to
                       `~p4pillon.server.thread.SharedPV`.  `~p4p.server.cothread.SharedPV`
                       is also safe here.

                       `~p4pillon.server.asyncio.SharedPV` is rejected at construction time
                       (raises `ValueError`): `makeChannel` is called by the server's
                       own internal I/O thread, never the thread actually running the
                       asyncio event loop, and `asyncio.SharedPV.__init__` requires a
                       running loop *on the calling thread* -- it would raise
                       ``RuntimeError: no running event loop`` on every channel
                       creation.  (`RecordProvider` does not have this restriction,
                       since its ``add()`` is called directly by user code, which for
                       asyncio users naturally runs inside a coroutine.)
    """

    def __init__(self, registry, pv_factory=None):
        if pv_factory is not None:
            _check_pv_factory_is_safe(pv_factory)
        self._registry = registry
        self._pv_factory = pv_factory

    def testChannel(self, name):
        basename, field = _split_field_name(name)
        if field is None:
            return False
        entry = self._registry.get(basename)
        if entry is None:
            return False
        return _field_applies(field, entry["valtype"])

    def makeChannel(self, name, peer):
        basename, field = _split_field_name(name)
        entry = self._registry.get(basename)
        if entry is None or not _field_applies(field, entry["valtype"]):
            return None
        value = _build_one_field(field, basename, entry["valtype"],
                                  entry.get("dtyp_choices"), entry.get("fields") or {})
        return _field_shared_pv(value, self._pv_factory)


def _split_field_name(name):
    # Returns (basename, field) if `name` is "<basename>.<FIELD>" for a
    # known field, else (name, None).
    basename, sep, field = name.rpartition(".")
    if not sep or field not in FIELD_NAMES:
        return name, None
    return basename, field


def _check_pv_factory_is_safe(pv_factory):
    # DynamicRecordFields.makeChannel()/testChannel() are always called by the
    # server's own internal I/O thread, never the thread (if any) running an
    # asyncio event loop, so a pv_factory requiring one can never construct
    # successfully there.  Detected via the `_requires_running_loop` trait
    # (set on p4pillon.server.asyncio.SharedPV) rather than naming that class
    # directly, so any future loop-requiring flavor is caught the same way.
    # Caught here, at construction time, rather than leaving it to fail deep
    # inside a server callback on first use.
    if isinstance(pv_factory, type) and getattr(pv_factory, "_requires_running_loop", False):
        raise ValueError(
            f"pv_factory={pv_factory.__name__} is not safe for DynamicRecordFields: makeChannel() is "
            "always called by the server's own internal thread, never the thread "
            "running an asyncio event loop, so it can never construct one. Use "
            "p4pillon.server.thread.SharedPV (the default) or p4p.server.cothread.SharedPV "
            "instead.")


@functools.cache
def _default_pv_factory():
    # Resolved lazily and cached: p4pillon.server.thread is the common
    # default, but importing it at module scope would force a hard
    # dependency on the threading server helper for anyone only using
    # build_record_fields() directly, or always passing their own
    # pv_factory.  Caching avoids repeating the import on every call --
    # DynamicRecordFields.makeChannel() runs this once per channel connect.
    from p4pillon.server.thread import SharedPV
    return SharedPV


def _field_shared_pv(value, pv_factory=None):
    return (pv_factory or _default_pv_factory())(initial=value)
