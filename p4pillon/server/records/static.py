"""`StaticRecordProvider`: the eager path, building every "<name>.<FIELD>"
sub-PV up front when a base PV is `add()`-ed. See `.dynamic` for the lazy,
registry-driven alternative, `.server` for `IOCRecordServer` (which uses
`.dynamic`, not this module, for its plain-dict shorthand), and the
`p4pillon.server.records` package docstring for the overall rationale.
"""

from p4p.server import StaticProvider
from p4p.server.raw import SharedPV as _SharedPVBase

from .fields import (
    RecordFieldOverrides,
    _field_shared_pv,
    _resolve_valtype_and_description,
    _scalar_nt,
    build_record_fields,
)

__all__ = ("StaticRecordProvider",)


class StaticRecordProvider(StaticProvider):
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

    Each "<name>.<FIELD>" sub-PV is built using ``type(pv)``, so it
    automatically matches the base PV's own concurrency model.

    DESC/DESC$ are seeded from the base PV's ``display.description`` at
    `add()` time and not tracked afterward; call `set_description` to push
    an update.
    """

    def __init__(self, name: str | None = None):
        super().__init__(name)
        # name -> {fieldname: field pv}, for the sub-PVs actually added (may
        # be fewer than FIELD_NAMES, e.g. ADEL/MDEL omitted for a
        # non-numeric valtype) -- lets remove()/set_description() find them.
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
                            `pv.nt` when that's an NTScalar, else falls back to
                            ``'d'``.

        See `~p4pillon.server.records.build_record_fields` for `dtyp_choices`,
        `fields`, and how RTYP inference is rejected for a non-scalar `pv`.
        """
        super().add(name, pv)
        if not record_fields:
            return

        valtype, description = _resolve_valtype_and_description(pv, valtype)
        built = build_record_fields(
            name, valtype, dtyp_choices=dtyp_choices, fields=fields, pv=pv, description=description
        )
        field_pvs: dict[str, _SharedPVBase] = {}
        for fieldname, value in built.items():
            field_pv = _field_shared_pv(value, type(pv))
            super().add(f"{name}.{fieldname}", field_pv)
            field_pvs[fieldname] = field_pv
        self._field_pvs[name] = field_pvs

    def set_description(self, name: str, description: str) -> None:
        """Update "<name>.DESC"/"<name>.DESC$" to `description`, pushed live
        to any already-open connection via `post()`.

        :raises KeyError: if `name` was never added, or was added with
                          `record_fields=False`.
        """
        field_pvs = self._field_pvs[name]
        wrapped = _scalar_nt("s").wrap(description)
        field_pvs["DESC"].post(wrapped)
        field_pvs["DESC$"].post(wrapped)

    def remove(self, name: str) -> None:
        """Remove a PV, and any "<name>.<FIELD>" sub-PVs previously added for it."""
        field_pvs = self._field_pvs.pop(name, None)
        if field_pvs is not None:
            for fieldname in field_pvs:
                super().remove(f"{name}.{fieldname}")
        super().remove(name)
