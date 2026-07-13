"""Serve per-field "sub-PVs" for the fields common to every EPICS record
(dbCommon.dbd), plus DTYP, RTYP, and NAME, mimicking the IOC/QSRV
convention where "RECORD.FIELD" resolves as its own channel independent of
the record's own value type (e.g. NTScalar for "RECORD" itself).

Unlike an IOC, a plain p4p server has no database or dbChannel layer to
parse a "RECORD.FIELD" name automatically. `StaticRecordProvider` (a
`~p4p.server.StaticProvider` subclass, the eager path) and
`DynamicRecordFields`/`IOCRecordProvider` (a `~p4p.server.DynamicProvider`
handler and its `add()`/`remove()` counterpart, the lazy path) all provide
this, without adding any of these fields to the base record's own
NTScalar/NTEnum structure.

Field defaults are taken from EPICS Base wherever it defines one:
 - menu fields (SCAN, PINI, STAT, SEVR, ...) default to the same choice
   dbCommon.dbd's initial() gives a freshly iocInit'd record (e.g. STAT
   starts as "UDF", UDFS as "INVALID", ACKT as "YES"), or choice 0 where
   no initial() is declared.
 - RTYP has no single correct default (a plain p4p PV isn't really any
   EPICS record type), so it is *inferred* from the base PV's NTScalar
   value type code via `infer_rtyp` (e.g. valtype='d' suggests "ai").
   Non-scalar PVs (`~p4p.nt.NTTable`, `~p4p.nt.NTNDArray`, ...) have no
   plausible guess; `StaticRecordProvider.add`/`IOCRecordProvider.add` reject
   these unless 'fields' gives 'RTYP' explicitly.
 - DTYP's choices are inherently per-record-type (they mirror whichever
   device supports were built for it), so unlike the other menu fields
   there is no real global default list -- 'dtyp_choices' falls back to
   ``["Soft Channel"]`` when omitted.
 - ADEL/MDEL (archive/monitor deadband) aren't in dbCommon.dbd either --
   only record types whose VAL is a plain numeric scalar (ai, ao, calc,
   calcout, dfanout, longin, longout, int64in, int64out, sel, sub; *not*
   bi/bo/mbbi/mbbo/stringin/stringout/waveform/...) declare them, always
   with the same DBF type as VAL. So `build_record_fields` includes them
   only when `valtype` is one of those numeric codes (see
   `~p4pillon.server.records.fields._field_applies`), defaulting to 0.
 - DESC always mirrors the base PV's own `display.description` sub-field
   (present only when built with e.g. ``NTScalar(..., display=True)``) --
   like NAME, it isn't settable via 'fields'. Every path takes just a
   one-time snapshot of it (at `add()` time, or per `makeChannel()` call for
   `DynamicRecordFields`); later `display.description` changes aren't
   tracked automatically. Both `StaticRecordProvider` and `IOCRecordProvider`
   have a `set_desc_record` method to update it explicitly afterward --
   `StaticRecordProvider`'s pushes the update live to any already-open
   connection, while `IOCRecordProvider`'s only affects *new* connections,
   since the lazy path keeps no live PV reference. Absent a
   display.description field entirely, DESC is always "".
Any of these can be overridden via the 'fields' dict accepted by
`build_record_fields`, `StaticRecordProvider.add`, and `IOCRecordProvider.add`,
e.g. {"SCAN": "1 second", "RTYP": "ai"}.

Every string-valued field (DESC, ASG, EVNT, TSEL, SDIS, AMSG, NAMSG, FLNK,
NAME, RTYP) is additionally servable as "<name>.<FIELD>$", returning the
same value as "<name>.<FIELD>" -- mirroring the "RECORD.FIELD$" convention
real IOCs support via dbChannelCreate() (see pvxs' ioc/channel.cpp) to
fetch a DBF_STRING field as a long string, working around Channel Access's
40-character MAX_STRING_SIZE limit. p4p/pvAccess has no such limit, so
here "$" is just an identical-valued alias, not a different wire
representation (see `STRING_FIELDS`, `~p4pillon.server.records.fields._build_one_field`).

Fields with no independent external representation on a real IOC -- the
DBF_NOACCESS internals (MLOK, MLIS, BKLNK, ASP, PPN, PPNR, SPVT, RSET,
DSET, DPVT, RDES, LSET, BKPT), and TIME (DBF_NOACCESS, only reachable via
DBR_TIME_* wrapper requests, never as "RECORD.TIME") -- are intentionally
not served here, matching real IOC behaviour.

This package is split by concern:
 - `.fields` -- the field schema (menus, `COMMON_FIELDS`, ...) and the
   logic to build each field's initial `~p4p.Value` (`build_record_fields`).
 - `.static` -- `StaticRecordProvider`, the eager path.
 - `.dynamic` -- `DynamicRecordFields` and `IOCRecordProvider`, the
   lazy/registry-driven path.
 - `.server` -- `IOCRecordServer`, which uses `.dynamic` (not `.static`) for
   its plain-dict shorthand.
"""

from .dynamic import DynamicRecordFields, IOCRecordProvider
from .fields import (
    COMMON_FIELDS,
    FIELD_NAMES,
    MENU_ALARM_SEVR,
    MENU_ALARM_STAT,
    MENU_PINI,
    MENU_PRIORITY,
    MENU_SCAN,
    MENU_YES_NO,
    STRING_FIELDS,
    RecordFieldOverrides,
    RegistryEntry,
    build_record_fields,
    infer_rtyp,
)
from .server import IOCRecordServer
from .static import StaticRecordProvider

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
    "StaticRecordProvider",
    "IOCRecordServer",
    "DynamicRecordFields",
    "IOCRecordProvider",
)
