"""`StaticRecordProvider`: the eager path, building every "<name>.<FIELD>"
sub-PV up front when a base PV is `add()`-ed. See `.dynamic` for the lazy,
registry-driven alternative, `.server` for `IOCMimicServer` (which uses
`.dynamic`, not this module, for its plain-dict shorthand), and the
`p4pillon.server.records` package docstring for the overall rationale.
"""

from p4p.server import StaticProvider
from p4p.server.raw import SharedPV as _SharedPVBase

from p4pillon.utils import mark_all

from ._util import _apply_ioc_initial_update, _KeysContainerMixin
from .fields import (
    RecordFieldOverrides,
    _desc_field_value,
    _field_shared_pv,
    _flavor_matched_pv_factory,
    _resolve_valtype_and_description,
    _should_serve_record_fields,
    _stamp,
    build_record_fields,
)

__all__ = ("StaticRecordProvider",)


class StaticRecordProvider(_KeysContainerMixin, StaticProvider):
    """A `~p4p.server.StaticProvider` which, in addition to serving each added PV
    under its own name, also serves "<name>.<FIELD>" as independent read-only
    channels for DTYP, RTYP, NAME, the fields common to every EPICS record
    (dbCommon.dbd), and ADEL/MDEL where `valtype` supports them -- without adding
    any of those fields to the PV's own NTScalar or NTEnum structure. ::

        from p4p.nt import NTScalar
        from p4p.server import Server
        from p4pillon.server.thread import SharedPV
        from p4pillon.server.records import StaticRecordProvider

        provider = StaticRecordProvider("example")
        provider.add("EXAMPLE:PV",
                     SharedPV(nt=NTScalar("d", display=True),
                              initial={"value": 1.234,
                                       "display": {"description": "An example ai-like record"}}),
                     dtyp_choices=["Soft Channel", "Raw Soft Channel"],
                     fields={"SCAN": "1 second"})

        with Server(providers=[provider]):
            ...

    See the `p4pillon.server.records` package docstring for the rationale behind each
    field's default, and `~p4pillon.server.records.build_record_fields` for the meaning
    of `dtyp_choices` and `fields`.

    Each "<name>.<FIELD>" sub-PV is built with the plain p4pillon SharedPV
    class matching the base PV's concurrency flavor (thread or asyncio) --
    deliberately not ``type(pv)`` itself, so a base PV with its own handlers
    (e.g. a `~p4pillon.thread.sharednt.SharedNT`) doesn't pass those on to
    its sub-PVs, which stay read-only.

    DESC/DESC$ are seeded from the base PV's ``display.description`` at
    `add()` time and not tracked afterward; call `set_desc_record` to push
    an update.

    Every sub-PV's timeStamp is likewise a one-time `add()`-time snapshot of
    the base PV's own (falling back to `add()` time itself for a base PV
    carrying no stamp), shared by every client for the life of the sub-PV.
    `IOCMimicProvider` re-reads it per connection instead -- see the
    `p4pillon.server.records` package docstring.
    """

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        # name -> {fieldname: field pv}, for the sub-PVs actually added (may
        # be fewer than FIELD_NAMES, e.g. ADEL/MDEL omitted for a
        # non-numeric valtype) -- lets remove()/set_desc_record() find them.
        self._field_pvs: dict[str, dict[str, _SharedPVBase]] = {}

    def add(
        self,
        name: str,
        pv: _SharedPVBase,
        valtype: str | None = None,
        dtyp_choices: list[str] | None = None,
        fields: RecordFieldOverrides | None = None,
        record_fields: bool = True,
    ) -> None:
        """Add a PV, and (unless `record_fields` is False) its "<name>.<FIELD>"
        sub-PVs.

        :param str valtype: NTScalar value type code matching `pv` (e.g.
                            ``NTScalar('d')`` -> ``valtype='d'``); only used to
                            infer a default RTYP, so it needn't be exact if RTYP
                            is overridden.  Left as `None`, it's inferred from
                            `pv.nt` when that's an NTScalar (or NTEnum -> mbbi),
                            else falls back to ``'d'``.

        A `pv` whose RTYP can't be inferred (a non-scalar, non-enum
        `~p4p.nt.NTNDArray`/`~p4p.nt.NTTable`/... -> a Q:group in a real IOC) and
        which is given no explicit ``fields={'RTYP': ...}`` is served on its own,
        with no "<name>.<FIELD>" sub-PVs -- the same as ``record_fields=False``,
        mirroring an IOC serving a group (no dbCommon fields), rather than raising.

        See `~p4pillon.server.records.build_record_fields` for `dtyp_choices` and
        `fields`.
        """
        if record_fields and not _should_serve_record_fields(pv, fields):
            # Not record-like, and no explicit fields={'RTYP'} to opt in: serve
            # the base PV alone, as with record_fields=False (see the docstring).
            record_fields = False

        field_pvs: dict[str, _SharedPVBase] = {}
        if record_fields:
            # Validate and build everything *before* the first super().add() --
            # a failure (e.g. a bad menu choice) must not leave the base PV
            # half-added with no sub-PVs. That is also why the widening below
            # sits here rather than at the top of add(): a raise must leave `pv`
            # untouched.
            valtype, description = _resolve_valtype_and_description(pv, valtype)
            built = build_record_fields(
                name, valtype, dtyp_choices=dtyp_choices, fields=fields, pv=pv, description=description
            )
            pv_factory = _flavor_matched_pv_factory(pv)
            field_pvs = {fieldname: _field_shared_pv(value, pv_factory) for fieldname, value in built.items()}

        _apply_ioc_initial_update(pv)
        super().add(name, pv)
        if not record_fields:
            return

        for fieldname, field_pv in field_pvs.items():
            super().add(f"{name}.{fieldname}", field_pv)
        self._field_pvs[name] = field_pvs

    def set_desc_record(self, name: str, description: str) -> None:
        """Update "<name>.DESC"/"<name>.DESC$" to `description`, pushed live
        to any already-open connection via `post()`.

        :raises KeyError: if `name` was never added, or was added with
                          `record_fields=False`.
        """
        field_pvs = self._field_pvs[name]
        # Stamped "now", not from the base PV: this is a DESC change in its own
        # right, and the record hasn't processed. Without it the posted value
        # would carry wrap()'s unset 0s 0ns and land on the client as
        # 1970-01-01 (see `~p4pillon.server.records.fields._stamp`).
        wrapped = mark_all(_stamp(_desc_field_value(description), None))
        field_pvs["DESC"].post(wrapped)
        field_pvs["DESC$"].post(wrapped)

    def remove(self, name: str) -> None:
        """Remove a PV, and any "<name>.<FIELD>" sub-PVs previously added for it."""
        field_pvs = self._field_pvs.pop(name, None)
        if field_pvs is not None:
            for fieldname in field_pvs:
                super().remove(f"{name}.{fieldname}")
        super().remove(name)
