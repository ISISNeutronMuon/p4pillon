"""Tests for `p4pillon.server.records`: `infer_rtyp`/`build_record_fields`
(the field-value logic shared by both providers), `StaticRecordProvider`
(the eager path), `DynamicRecordFields`/`IOCMimicProvider` (the lazy,
registry-driven path), and `IOCMimicServer` (the plain-dict shorthand).
Thread-flavored coverage is the default; the `*Asyncio` classes at the
bottom only re-check flavor-specific concerns already covered for the
thread flavor elsewhere in this file.
"""

import asyncio
import gc
import io
import time
import warnings
from contextlib import redirect_stderr
from functools import cache

import numpy
import pytest
from p4p import Value
from p4p.client.asyncio import Context as AsyncContext
from p4p.client.thread import Context, RemoteError, TimeoutError
from p4p.nt import NTEnum, NTNDArray, NTScalar, NTTable
from p4p.server import DynamicProvider, Server, StaticProvider
from p4p.server.asyncio import SharedPV as RawAsyncSharedPV

from p4pillon.server.asyncio import SharedPV as AsyncSharedPV
from p4pillon.server.raw import InitialUpdate
from p4pillon.server.records import (
    FIELD_NAMES,
    STRING_FIELDS,
    DynamicRecordFields,
    IOCMimicProvider,
    IOCMimicServer,
    RecordFieldOverrides,
    RegistryEntry,
    StaticRecordProvider,
    build_record_fields,
    infer_rtyp,
)
from p4pillon.server.records.fields import _ENUM_VALTYPE
from p4pillon.server.records.server import _expand_providers
from p4pillon.server.thread import SharedPV
from p4pillon.thread.sharednt import SharedNT


def _stamp_of(value) -> float:
    """A raw Value's timeStamp as a float, for comparison against time.time().

    Only for bare `p4p.Value`s (what `build_record_fields` returns); anything
    that came back from a `current()`/`get()` wrapper already has `.timestamp`.
    """
    return value["timeStamp.secondsPastEpoch"] + value["timeStamp.nanoseconds"] / 1e9


def _leaves(value) -> set[str]:
    """Every leaf field path in a raw Value, dotted ("alarm.message", ...).

    Compared against `changedSet(expand=True)` to assert a value is *fully*
    marked; see `TestFieldValuesAreFullyMarked`.
    """
    leaves = set()
    for name, sub in value.items():
        if isinstance(sub, Value):
            leaves |= {f"{name}.{leaf}" for leaf in _leaves(sub)}
        else:
            leaves.add(name)
    return leaves


class TestInferRtyp:
    """`infer_rtyp`'s valtype-code -> RTYP-choice guesses."""

    def test_infer_rtyp(self):
        assert infer_rtyp("d") == "ai"
        assert infer_rtyp("f") == "ai"
        assert infer_rtyp("s") == "stringin"
        assert infer_rtyp("i") == "longin"
        assert infer_rtyp("ad") == "waveform"
        assert infer_rtyp("?") == "bi"

    def test_infer_rtyp_int_widths(self):
        # 8/16/32-bit ints fit longin's DBF_LONG VAL, but 64-bit 'l'/'L' would
        # truncate there, so they infer the dedicated int64in record (DBF_INT64).
        for code in ("b", "B", "h", "H", "i", "I"):
            assert infer_rtyp(code) == "longin"
        assert infer_rtyp("l") == "int64in"
        assert infer_rtyp("L") == "int64in"

    def test_infer_rtyp_enum(self):
        # An NTEnum-backed PV (index into named choices) has no scalar valtype
        # code; the _ENUM_VALTYPE sentinel maps to mbbi, the multi-state binary
        # input record whose DBF_ENUM VAL is the same index+choices shape.
        assert infer_rtyp(_ENUM_VALTYPE) == "mbbi"


class TestBuildRecordFields:
    """`build_record_fields`'s per-field value/override/default logic,
    independent of either provider that serves the fields it builds."""

    def test_all_fields_built(self):
        built = build_record_fields("PV:NAME", "d")
        assert set(built) == FIELD_NAMES

    def test_name_mirrors_basename_and_is_not_overridable(self):
        built = build_record_fields("PV:NAME", "d", fields={"NAME": "ignored"})
        assert built["NAME"]["value"] == "PV:NAME"

    def test_rtyp_inferred_and_overridable(self):
        built = build_record_fields("PV:NAME", "d")
        assert built["RTYP"]["value"] == "ai"

        built = build_record_fields("PV:NAME", "d", fields={"RTYP": "waveform"})
        assert built["RTYP"]["value"] == "waveform"

    def test_dtyp_default_and_choices(self):
        built = build_record_fields("PV:NAME", "d")
        assert built["DTYP"]["value.choices"] == ["Soft Channel"]
        assert built["DTYP"]["value.index"] == 0

        built = build_record_fields(
            "PV:NAME", "d", dtyp_choices=["Soft Channel", "Raw Soft Channel"], fields={"DTYP": "Raw Soft Channel"}
        )
        assert built["DTYP"]["value.index"] == 1

    def test_menu_field_default_and_override(self):
        built = build_record_fields("PV:NAME", "d")
        assert built["SCAN"]["value.choices"][built["SCAN"]["value.index"]] == "Passive"
        assert built["STAT"]["value.choices"][built["STAT"]["value.index"]] == "UDF"

        built = build_record_fields("PV:NAME", "d", fields={"SCAN": "1 second"})
        assert built["SCAN"]["value.choices"][built["SCAN"]["value.index"]] == "1 second"

    def test_scalar_field_default_and_override(self):
        built = build_record_fields("PV:NAME", "d")
        assert built["ASG"]["value"] == ""

        built = build_record_fields("PV:NAME", "d", fields={"ASG": "hello"})
        assert built["ASG"]["value"] == "hello"

    def test_desc_mirrors_description_param_and_is_not_overridable(self):
        built = build_record_fields("PV:NAME", "d")
        assert built["DESC"]["value"] == ""

        built = build_record_fields("PV:NAME", "d", description="from display.description")
        assert built["DESC"]["value"] == "from display.description"

        # 'fields' is ignored for DESC, same as NAME -- description= is the
        # only way to set it.
        built = build_record_fields("PV:NAME", "d", fields={"DESC": "ignored"}, description="from display.description")
        assert built["DESC"]["value"] == "from display.description"

    def test_adel_mdel_included_for_numeric_valtype_and_matches_it(self):
        built = build_record_fields("PV:NAME", "d")
        assert built["ADEL"]["value"] == 0.0
        assert built["MDEL"]["value"] == 0.0

        built = build_record_fields("PV:NAME", "l", fields={"ADEL": 5, "MDEL": 1})
        assert built["ADEL"]["value"] == 5
        assert built["MDEL"]["value"] == 1

    def test_adel_mdel_omitted_for_non_numeric_valtype(self):
        built = build_record_fields("PV:NAME", "s")
        assert "ADEL" not in built
        assert "MDEL" not in built
        assert set(built) == FIELD_NAMES - {"ADEL", "MDEL"}

        built = build_record_fields("PV:NAME", "?")
        assert "ADEL" not in built
        assert "MDEL" not in built

        built = build_record_fields("PV:NAME", "ad", fields={"RTYP": "waveform"})
        assert "ADEL" not in built
        assert "MDEL" not in built

    def test_string_field_dollar_alias_mirrors_value(self):
        assert {"DESC", "ASG", "EVNT", "TSEL", "SDIS", "AMSG", "NAMSG", "FLNK", "NAME", "RTYP"} == STRING_FIELDS

        built = build_record_fields("PV:NAME", "d", fields={"RTYP": "waveform"}, description="hello")
        for fieldname in STRING_FIELDS:
            assert built[f"{fieldname}$"]["value"] == built[fieldname]["value"]
        assert built["DESC$"]["value"] == "hello"
        assert built["RTYP$"]["value"] == "waveform"
        assert built["NAME$"]["value"] == "PV:NAME"

    def test_non_string_field_has_no_dollar_alias(self):
        built = build_record_fields("PV:NAME", "d")
        for fieldname in set(FIELD_NAMES) - STRING_FIELDS - {"ADEL", "MDEL"}:
            if fieldname.endswith("$"):
                continue
            assert f"{fieldname}$" not in built

    def test_unknown_fields_key_warns_but_does_not_raise(self):
        with pytest.warns(UserWarning, match="DESK"):
            # Deliberate "DESK" typo asserts the UserWarning; ty flags it against RecordFieldOverrides.
            built = build_record_fields("PV:NAME", "d", fields={"ASG": "hello", "DESK": "typo"})  # ty: ignore[invalid-argument-type, invalid-key]
        assert built["ASG"]["value"] == "hello"
        assert "DESK" not in built

    def test_no_warning_for_valid_fields(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            build_record_fields("PV:NAME", "d", fields={"DESC": "hello", "RTYP": "waveform"})

    def test_invalid_menu_choice_raises_with_valid_choices_listed(self):
        # A typo'd choice name used to surface as NTEnum.assign's int()
        # fallback -- "invalid literal for int() with base 0" -- rather than
        # anything naming the field or the valid choices.
        with pytest.raises(ValueError, match=r"SCAN.*'1 second'"):
            build_record_fields("PV:NAME", "d", fields={"SCAN": "2 seconds"})

        # DTYP is validated against dtyp_choices (or its default list).
        with pytest.raises(ValueError, match=r"DTYP.*'Soft Channel'"):
            build_record_fields("PV:NAME", "d", fields={"DTYP": "Raw Soft Channel"})
        built = build_record_fields(
            "PV:NAME", "d", dtyp_choices=["Soft Channel", "Raw Soft Channel"], fields={"DTYP": "Raw Soft Channel"}
        )
        assert built["DTYP"]["value.index"] == 1

    def test_raises_for_non_record_pv_without_explicit_rtyp(self):
        # The low-level builder still refuses a non-record PV (NTNDArray/NTTable/
        # ...) with no explicit RTYP: its job is to return the fields dict, so it
        # can't invent an RTYP. (The *providers* instead pre-check and omit the
        # fields entirely -- see test_non_record_nt_served_without_fields.)
        img = SharedPV(nt=NTNDArray(), initial=numpy.zeros((4, 4)))
        with pytest.raises(ValueError, match="Cannot infer RTYP"):
            build_record_fields("PV:NAME", "d", pv=img)

        # An explicit RTYP override builds fine (it's what opts a group into
        # record treatment through the providers too).
        built = build_record_fields("PV:NAME", "d", pv=img, fields={"RTYP": "waveform"})
        assert built["RTYP"]["value"] == "waveform"

    def test_every_field_is_stamped_with_the_build_time_without_a_pv(self):
        # NTScalar/NTEnum.wrap() leaves timeStamp at 0s 0ns, which a client
        # renders as 1970-01-01. With no `pv` there's no record process time
        # to mirror, so every field is stamped "now" instead.
        before = time.time()
        built = build_record_fields("PV:NAME", "d", description="hello")
        after = time.time()

        assert set(built) == FIELD_NAMES  # no field escapes the loop below
        for fieldname, value in built.items():
            stamped = _stamp_of(value)
            assert before <= stamped <= after, f"{fieldname} stamped {stamped}, expected {before}..{after}"

    def test_every_field_takes_the_base_pv_timestamp(self):
        # Like a real IOC, where "RECORD.FIELD" reports the record's process
        # time: a SharedNT runs TimestampRule, so it has one to mirror.
        base = SharedNT(nt=NTScalar("d"), initial=1.0)
        expected = base.current().timestamp

        time.sleep(0.01)  # so a "now" stamp would be distinguishable
        built = build_record_fields("PV:NAME", "d", pv=base, description="hello")

        assert set(built) == FIELD_NAMES
        for fieldname, value in built.items():
            assert _stamp_of(value) == expected, f"{fieldname} stamped {_stamp_of(value)}, expected {expected}"

    def test_falls_back_to_now_for_an_unstamped_base_pv(self):
        # A plain SharedPV runs no TimestampRule, so its own timeStamp is the
        # unset 0s 0ns -- mirroring that would put the 1970 back.
        before = time.time()
        built = build_record_fields("PV:NAME", "d", pv=_pv())
        after = time.time()

        assert before <= _stamp_of(built["RTYP"]) <= after


class TestFieldValuesAreFullyMarked:
    """Every field value must have its *whole* structure marked as changed.

    pvAccess only puts marked fields on the wire, and a field sub-PV is
    open()'d once and never post()'d -- so an unmarked alarm/timeStamp is
    simply never sent. p4p and pvxs clients zero-fill what they didn't
    receive, which hides it; the Java org.epics.pva client leaves an
    untransmitted string as null, and the EPICS Archiver Appliance then
    NPEs flattening alarm.message into its metadata map. A real IOC sends
    the complete structure on a first get/monitor update.
    """

    # The leaves that used to go missing. alarm.message is the one that
    # actually crashed the archiver; the others share the same cause.
    UNSENT = frozenset({"alarm.message", "alarm.severity", "alarm.status", "timeStamp.userTag"})

    def test_every_built_field_is_fully_marked(self):
        built = build_record_fields("PV:NAME", "d", description="hello")

        assert set(built) == FIELD_NAMES  # no field escapes the loop below
        for fieldname, value in built.items():
            marked = value.changedSet(expand=True)
            assert _leaves(value) <= marked, f"{fieldname} has unmarked leaves"
            assert marked >= self.UNSENT, fieldname

    def test_enum_backed_field_is_fully_marked(self):
        # DTYP is an NTEnum, so its "value" is a substructure (value.index,
        # value.choices) rather than a leaf -- marking must reach into it.
        built = build_record_fields("PV:NAME", "d")

        marked = built["DTYP"].changedSet(expand=True)
        assert {"value.index", "value.choices"} <= marked
        assert marked >= self.UNSENT

    def test_static_provider_sends_the_whole_structure(self):
        # The assertion that reproduces the archiver failure: a builder-only
        # check would pass even if the value lost its marks before open().
        provider = StaticRecordProvider("test")
        provider.add("PV:NAME", _pv(), valtype="d")

        with Server(providers=[provider], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            for field in ("RTYP", "DESC", "NAME", "SCAN", "DTYP"):
                received = c.get(f"PV:NAME.{field}").raw.changedSet()
                assert received >= self.UNSENT, f"{field} arrived missing {sorted(self.UNSENT - received)}"

    def test_dynamic_provider_sends_the_whole_structure(self):
        # Same, for the lazy path -- makeChannel() builds per connection.
        provider = IOCMimicProvider("test")
        provider.add("PV:NAME", _pv(), valtype="d")

        with (
            Server(providers=[*provider.providers], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            for field in ("RTYP", "DESC", "NAME", "SCAN", "DTYP"):
                received = c.get(f"PV:NAME.{field}").raw.changedSet()
                assert received >= self.UNSENT, f"{field} arrived missing {sorted(self.UNSENT - received)}"

    def test_set_desc_record_posts_a_fully_marked_value(self):
        # set_desc_record builds its value directly rather than through
        # _build_one_field, so it needs the marking of its own.
        provider = StaticRecordProvider("test")
        provider.add("PV:NAME", _pv_with_description("hello"))

        with Server(providers=[provider], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            provider.set_desc_record("PV:NAME", "goodbye")
            for field in ("DESC", "DESC$"):
                got = c.get(f"PV:NAME.{field}")
                assert got == "goodbye"
                assert got.raw.changedSet() >= self.UNSENT, field


class TestBasePVSendsTheWholeStructure:
    """The same wire-format requirement as `TestFieldValuesAreFullyMarked`, for
    the *base* PV rather than its "<name>.<FIELD>" sub-PVs. Everything here
    exists to mimic an IOC, and an IOC sends the complete structure on a first
    get/monitor update -- so every entry point resolves a PV left on
    `InitialUpdate.DEFAULT` to `~InitialUpdate.COMPLETE`.
    """

    # The string leaves an org.epics.pva client would otherwise see as null.
    UNSENT = frozenset({"alarm.message", "display.description", "display.units"})

    @staticmethod
    def _base_pv(**kwargs):
        return SharedPV(nt=NTScalar("d", display=True, valueAlarm=True), initial={"value": 1.234}, **kwargs)

    def _assert_complete(self, context, name):
        received = context.get(name).raw.changedSet(expand=True)
        assert received >= self.UNSENT, f"{name} arrived missing {sorted(self.UNSENT - received)}"
        assert "valueAlarm.highAlarmLimit" in received

    def test_static_provider(self):
        provider = StaticRecordProvider("test")
        provider.add("PV:NAME", self._base_pv())

        with Server(providers=[provider], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            self._assert_complete(c, "PV:NAME")

    def test_static_provider_without_record_fields(self):
        # The wire format is fixed for every PV served, not just record-like
        # ones -- record_fields=False opts out of sub-PVs, not out of this.
        provider = StaticRecordProvider("test")
        provider.add("PV:NAME", self._base_pv(), record_fields=False)

        with Server(providers=[provider], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            self._assert_complete(c, "PV:NAME")

    def test_dynamic_provider(self):
        provider = IOCMimicProvider("test")
        provider.add("PV:NAME", self._base_pv())

        with (
            Server(providers=[*provider.providers], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            self._assert_complete(c, "PV:NAME")

    def test_ioc_mimic_server_dict(self):
        with (
            IOCMimicServer(providers=[{"PV:NAME": self._base_pv()}], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            self._assert_complete(c, "PV:NAME")

    def test_explicit_opt_out_is_respected(self):
        # A caller who asked for p4p's own behaviour keeps it: their choice
        # outranks the provider's.
        provider = IOCMimicProvider("test")
        provider.add("PV:NAME", self._base_pv(initial_update=InitialUpdate.AS_POSTED))

        with (
            Server(providers=[*provider.providers], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("PV:NAME").raw.changedSet() == {"value"}

    def test_plain_p4p_server_is_unchanged(self):
        # The negative control for the whole feature: outside
        # p4pillon.server.records, DEFAULT still means p4p's behaviour.
        provider = StaticProvider("test")
        provider.add("PV:NAME", self._base_pv())

        with Server(providers=[provider], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get("PV:NAME").raw.changedSet() == {"value"}


class TestRecordFieldOverridesTyping:
    """Drift guard keeping the hand-written `RecordFieldOverrides` TypedDict
    in sync with `FIELD_NAMES` as fields are added/removed."""

    def test_matches_field_names(self):
        # RecordFieldOverrides is hand-written (TypedDict's functional form
        # needs a literal dict, not one built from FIELD_NAMES) -- this is
        # the drift guard that keeps it honest as fields are added/removed
        # from COMMON_FIELDS/STRING_FIELDS.
        assert RecordFieldOverrides.__optional_keys__ == FIELD_NAMES
        assert not RecordFieldOverrides.__required_keys__


def _pv(valtype="d", initial=1.234):
    return SharedPV(nt=NTScalar(valtype), initial=initial)


def _enum_pv(choices=("OFF", "ON"), index=0):
    return SharedPV(nt=NTEnum(), initial={"index": index, "choices": list(choices)})


def _pv_with_description(description=None, valtype="d", initial=1.234):
    value = {"value": initial}
    if description is not None:
        value["display"] = {"description": description}
    return SharedPV(nt=NTScalar(valtype, display=True), initial=value)


class TestStaticRecordProvider:
    """`StaticRecordProvider`: the eager path, building every "<name>.<FIELD>"
    sub-PV up front in `add()`."""

    def setup_method(self, _method):
        self.P = StaticRecordProvider("test")

    def test_add_creates_field_pvs(self):
        self.P.add("PV:NAME", _pv(), valtype="d")
        keys = set(self.P)
        assert "PV:NAME" in keys
        for field in FIELD_NAMES:
            assert f"PV:NAME.{field}" in keys

    def test_record_fields_false_opts_out(self):
        self.P.add("PV:NAME", _pv(), record_fields=False)
        assert list(self.P) == ["PV:NAME"]

    def test_valtype_inferred_from_pv_nt_when_omitted(self):
        # pv.nt is an NTScalar('s') -- valtype (and so RTYP/ADEL-MDEL
        # applicability) should be inferred from that, not silently
        # defaulted to 'd'/"ai".
        self.P.add("PV:NAME", _pv("s", "hello"))
        keys = set(self.P)
        assert "PV:NAME.ADEL" not in keys  # 's' has no ADEL/MDEL
        assert "PV:NAME.MDEL" not in keys

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get("PV:NAME.RTYP") == "stringin"

    def test_explicit_valtype_overrides_inference(self):
        # pv.nt is NTScalar('s'), but an explicit valtype takes precedence
        # over whatever could be inferred from pv.nt.
        self.P.add("PV:NAME", _pv("s", "hello"), valtype="d")

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get("PV:NAME.RTYP") == "ai"

    def test_enum_pv_infers_mbbi_rtyp(self):
        # An NTEnum-backed PV is accepted without an explicit RTYP and infers
        # "mbbi" (see infer_rtyp). ADEL/MDEL don't apply -- mbbi's VAL is a
        # DBF_ENUM index, not a plain numeric scalar.
        self.P.add("ENUM:PV", _enum_pv())
        keys = set(self.P)
        assert "ENUM:PV.ADEL" not in keys
        assert "ENUM:PV.MDEL" not in keys

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get("ENUM:PV.RTYP") == "mbbi"

    def test_valtype_defaults_to_d_when_not_inferrable(self):
        # A hand-built PV (no nt=) has no pv.nt to infer from -- falls back
        # to 'd', same as before this default became conditional.
        value = NTScalar("l").wrap(5)
        self.P.add("PV:NAME", SharedPV(initial=value))

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get("PV:NAME.RTYP") == "ai"
            assert "PV:NAME.ADEL" in self.P

    def test_served_field_carries_a_live_timestamp(self):
        # End-to-end: a field used to reach the client stamped 1970-01-01
        # (0s 0ns). This base PV is a plain SharedPV with no timeStamp of its
        # own, so the fields fall back to their build ("now") time.
        before = time.time()
        self.P.add("PV:NAME", _pv_with_description("hello"))

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            for field in ("DESC", "RTYP", "NAME", "SCAN"):
                stamped = c.get(f"PV:NAME.{field}").timestamp
                assert before <= stamped <= time.time(), f"{field} stamped {stamped}"

    def test_served_field_reports_the_base_pv_timestamp(self):
        # The IOC-like case: the base record has a process time, so its
        # fields report that rather than their own build time.
        base = SharedNT(nt=NTScalar("d"), initial=1.0)
        expected = base.current().timestamp

        time.sleep(0.01)
        self.P.add("PV:NAME", base)

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            for field in ("RTYP", "NAME", "SCAN"):
                assert c.get(f"PV:NAME.{field}").timestamp == expected, field

    def test_set_desc_record_stamps_the_update(self):
        # post()ing a bare wrap() would send the client 0s 0ns -- i.e. a DESC
        # update that lands stamped 1970-01-01.
        self.P.add("PV:NAME", _pv_with_description("hello"))

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            before = time.time()
            self.P.set_desc_record("PV:NAME", "goodbye")
            after = time.time()

            for field in ("DESC", "DESC$"):
                got = c.get(f"PV:NAME.{field}")
                assert got == "goodbye"
                assert before <= got.timestamp <= after, f"{field} stamped {got.timestamp}"

    def test_remove_cleans_up_fields(self):
        self.P.add("PV:NAME", _pv(), valtype="d")
        assert len(self.P) > 1
        self.P.remove("PV:NAME")
        assert list(self.P) == []

    def test_remove_without_fields_is_safe(self):
        self.P.add("PV:NAME", _pv(), record_fields=False)
        self.P.remove("PV:NAME")  # must not raise
        assert list(self.P) == []

    def test_adel_mdel_omitted_for_non_numeric_pv_and_remove_still_clean(self):
        self.P.add("PV:NAME", _pv("s", "hello"), valtype="s")
        keys = set(self.P)
        assert "PV:NAME.ADEL" not in keys
        assert "PV:NAME.MDEL" not in keys
        for field in FIELD_NAMES - {"ADEL", "MDEL"}:
            assert f"PV:NAME.{field}" in keys

        self.P.remove("PV:NAME")  # must not raise despite ADEL/MDEL never having been added
        assert list(self.P) == []

    def test_failed_add_leaves_provider_unchanged(self):
        # add() must validate before serving anything: a raising add() (e.g. a
        # bad menu choice) must not leave the base PV added with no sub-PVs.
        with pytest.raises(ValueError, match="SCAN"):
            self.P.add("PV:NAME", _pv(), fields={"SCAN": "2 seconds"})
        assert list(self.P) == []

    def test_sharednt_base_gets_plain_readonly_sub_pvs(self):
        # Regression: sub-PVs used to be built with type(pv) itself; for a
        # SharedNT base that gave every "<name>.<FIELD>" sub-PV the base PV's
        # own rule handlers (CompositeHandler with put support), silently
        # making the nominally read-only fields client-writable and
        # timestamp-rewritten. Only the concurrency *flavor* is matched now.
        base = SharedNT(nt=NTScalar("d"), initial=1.0)
        self.P.add("EXAMPLE:NT", base, valtype="d")

        for field_pv in self.P._field_pvs["EXAMPLE:NT"].values():
            assert type(field_pv) is SharedPV

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            with pytest.raises(RemoteError):
                c.put("EXAMPLE:NT.ASG", "written by client")
            assert c.get("EXAMPLE:NT.ASG") == ""

    def _check_non_record_served_without_fields(self, name, make_img, make_tbl):
        # infer_rtyp() has no plausible guess for a structural PV (NTNDArray/
        # NTTable/... -> a Q:group in a real IOC): the base PV is served with no
        # "<name>.<FIELD>" sub-PVs, unless an explicit RTYP override opts it in.
        self.P.add(f"EXAMPLE:{name}_IMG", make_img(), valtype="d")
        assert f"EXAMPLE:{name}_IMG" in self.P
        assert f"EXAMPLE:{name}_IMG.RTYP" not in self.P

        self.P.add(f"EXAMPLE:{name}_TBL", make_tbl(), valtype="d")
        assert f"EXAMPLE:{name}_TBL" in self.P
        assert f"EXAMPLE:{name}_TBL.RTYP" not in self.P

        self.P.add(f"EXAMPLE:{name}_IMG2", make_img(), valtype="d", fields={"RTYP": "waveform"})
        assert f"EXAMPLE:{name}_IMG2.RTYP" in self.P

        self.P.add(f"EXAMPLE:{name}_TBL2", make_tbl(), valtype="d", fields={"RTYP": "waveform"})
        assert f"EXAMPLE:{name}_TBL2.RTYP" in self.P

    def test_non_record_nt_served_without_fields(self):
        # Detected via pv.nt (set by SharedPV(nt=...)) rather than the
        # 'valtype' string, which can't distinguish an NTNDArray/NTTable-backed
        # PV from an NTScalar one.
        def img():
            return SharedPV(nt=NTNDArray(), initial=numpy.zeros((4, 4)))

        def tbl():
            return SharedPV(nt=NTTable(columns=[("A", "d")]), initial=[{"A": 1.0}])

        self._check_non_record_served_without_fields("NT", img, tbl)

    def test_non_record_hand_built_value_served_without_fields(self):
        # Same as test_non_record_nt_served_without_fields, but for a PV built
        # directly from a plain Value (no nt=) -- pv.nt is never set for
        # this, so detection instead falls back to the Value's own
        # structure ID (see _struct_id_of_current).
        img_value = NTNDArray().wrap(numpy.zeros((4, 4)))
        table_value = NTTable(columns=[("A", "d")]).wrap([{"A": 1.0}])

        self._check_non_record_served_without_fields(
            "HAND", lambda: SharedPV(initial=img_value), lambda: SharedPV(initial=table_value)
        )

    def test_rtyp_check_skips_pv_current_when_nt_declared(self):
        # The nt=NTScalar(...)/nt=NTNDArray()/etc. path is the hot path (the
        # common, documented way to build a SharedPV -- see nt.rst): it must
        # be resolved from pv.nt alone, without the more expensive fallback
        # of calling pv.current() to inspect the live Value's structure ID.
        class _CountingCurrentPV(SharedPV):
            def __init__(self, **kw):
                self.current_calls = 0
                super().__init__(**kw)

            def current(self):
                self.current_calls += 1
                return super().current()

        scalar_pv = _CountingCurrentPV(nt=NTScalar("d"), initial=1.234)
        self.P.add("EXAMPLE:FASTSCALAR", scalar_pv, valtype="d")
        # Exactly one, and not for the RTYP check: build_record_fields reads
        # the base PV's timeStamp to stamp the fields with (see _stamp), which
        # pv.nt can't answer. Once per add(), shared by every field.
        assert scalar_pv.current_calls == 1

        # A non-record NTNDArray is served base-only (no fields at all, so
        # nothing to stamp) -- resolved from pv.nt alone, with no current().
        ndarray_pv = _CountingCurrentPV(nt=NTNDArray(), initial=numpy.zeros((4, 4)))
        self.P.add("EXAMPLE:FASTIMG", ndarray_pv, valtype="d")
        assert ndarray_pv.current_calls == 0
        assert "EXAMPLE:FASTIMG" in self.P
        assert "EXAMPLE:FASTIMG.RTYP" not in self.P

    def test_rtyp_check_tolerates_non_value_unwrap(self):
        # Regression test: a hand-rolled unwrap= can return anything, with no
        # guarantee it's Value-like or that a `.raw` it happens to carry is a
        # genuine Value. Before _raw_current_or_none verified this with
        # isinstance(..., Value), _check_rtyp_inferrable's raw.type() call
        # would crash with AttributeError here instead of falling back to
        # NTType.UNKNOWN (never rejected), same as an unavailable current().
        value = NTScalar("d").wrap(1.234)
        pv = SharedPV(initial=value, unwrap=lambda _v: "not a value")

        self.P.add("PV:NAME", pv, valtype="d")  # must not raise
        assert "PV:NAME.RTYP" in self.P

    def test_live_get(self):
        self.P.add(
            "EXAMPLE:PV",
            _pv_with_description("An example ai-like record"),
            valtype="d",
            dtyp_choices=["Soft Channel", "Raw Soft Channel"],
            fields={"SCAN": "1 second", "ADEL": 0.5, "MDEL": 0.1},
        )

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get("EXAMPLE:PV") == 1.234
            assert c.get("EXAMPLE:PV.NAME") == "EXAMPLE:PV"
            assert c.get("EXAMPLE:PV.RTYP") == "ai"
            assert c.get("EXAMPLE:PV.DESC") == "An example ai-like record"
            assert c.get("EXAMPLE:PV.ADEL") == 0.5
            assert c.get("EXAMPLE:PV.MDEL") == 0.1

            assert c.get("EXAMPLE:PV.DESC$") == "An example ai-like record"
            assert c.get("EXAMPLE:PV.NAME$") == "EXAMPLE:PV"
            assert c.get("EXAMPLE:PV.RTYP$") == "ai"

            dtyp = c.get("EXAMPLE:PV.DTYP")
            assert dtyp.choice == "Soft Channel"

            scan = c.get("EXAMPLE:PV.SCAN")
            assert scan.choice == "1 second"

            stat = c.get("EXAMPLE:PV.STAT")
            assert stat.choice == "UDF"

    def test_desc_default_empty_without_display_description(self):
        self.P.add("EXAMPLE:PV", _pv(), valtype="d")

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get("EXAMPLE:PV.DESC") == ""
            assert c.get("EXAMPLE:PV.DESC$") == ""

    def test_desc_not_settable_via_fields(self):
        pv = _pv_with_description("real description")
        self.P.add("EXAMPLE:PV", pv, valtype="d", fields={"DESC": "ignored"})

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get("EXAMPLE:PV.DESC") == "real description"

    def test_desc_snapshot_only_by_default(self):
        # add() only takes a one-time snapshot of display.description --
        # a later pv.post() is never reflected without an explicit
        # set_desc_record() call.
        pv = _pv_with_description("initial description")
        self.P.add("EXAMPLE:PV", pv, valtype="d")

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get("EXAMPLE:PV.DESC") == "initial description"

            pv.post({"display": {"description": "updated description"}})

            assert c.get("EXAMPLE:PV.DESC") == "initial description"

    def test_set_desc_record_pushes_live_to_open_connection(self):
        pv = _pv_with_description("initial description")
        self.P.add("EXAMPLE:PV", pv, valtype="d")

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get("EXAMPLE:PV.DESC") == "initial description"

            self.P.set_desc_record("EXAMPLE:PV", "updated description")

            assert c.get("EXAMPLE:PV.DESC") == "updated description"
            assert c.get("EXAMPLE:PV.DESC$") == "updated description"

    def test_set_desc_record_raises_for_unknown_name(self):
        with pytest.raises(KeyError):
            self.P.set_desc_record("NOSUCH:PV", "x")

    def test_set_desc_record_raises_when_record_fields_false(self):
        self.P.add("EXAMPLE:PV", _pv_with_description("x"), record_fields=False)
        with pytest.raises(KeyError):
            self.P.set_desc_record("EXAMPLE:PV", "y")

    def test_no_such_field_times_out(self):
        self.P.add("EXAMPLE:PV", _pv(), valtype="d")

        with (
            Server(providers=[self.P], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
            pytest.raises(TimeoutError),
        ):
            c.get("EXAMPLE:PV.NOSUCHFIELD", timeout=0.2)

    def test_adel_mdel_unreachable_for_non_numeric_pv(self):
        self.P.add("EXAMPLE:STR", _pv("s", "hello"), valtype="s")

        with Server(providers=[self.P], isolate=True) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get("EXAMPLE:STR") == "hello"
            with pytest.raises(TimeoutError):
                c.get("EXAMPLE:STR.ADEL", timeout=0.2)
            with pytest.raises(TimeoutError):
                c.get("EXAMPLE:STR.MDEL", timeout=0.2)

    def test_keys_is_the_inherited_one_and_does_not_recurse(self):
        # _KeysContainerMixin builds the container dunders on self.keys(), which
        # this class inherits from p4p's StaticProvider. Giving the mixin a real
        # keys() rather than the TYPE_CHECKING-only declaration it has would put
        # one ahead of StaticProvider in this class's MRO, shadowing the
        # inherited one -- and, being a forwarder, recursing until RecursionError.
        self.P.add("EXAMPLE:PV", _pv())

        keys = self.P.keys()  # the inherited StaticProvider.keys(), called explicitly
        assert "EXAMPLE:PV" in keys
        assert sorted(keys) == sorted(self.P)


class TestIOCMimicServer:
    """`IOCMimicServer`: gives a plain `{name: pv}` dict `providers=` entry
    "<name>.<FIELD>" sub-PVs too, via the lazy path, without disturbing
    entries that aren't a plain dict."""

    def test_dict_provider_gets_field_pvs(self):
        # Plain p4p.server.Server treats a bare dict as shorthand for a plain
        # StaticProvider (base PV only, no "<name>.<FIELD>" sub-PVs) --
        # IOCMimicServer should instead also serve "<name>.<FIELD>" for it,
        # via a DynamicRecordFields-backed DynamicProvider built alongside
        # the (otherwise untouched) dict, with no other code changes.
        pvs = {"EXAMPLE:PV": _pv()}

        with (
            IOCMimicServer(providers=[pvs], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("EXAMPLE:PV") == 1.234
            assert c.get("EXAMPLE:PV.RTYP") == "ai"
            assert c.get("EXAMPLE:PV.SCAN").choice == "Passive"

    def test_dict_provider_desc_tracks_base_pv(self):
        # The dict shorthand stores a weak reference per entry, so DESC
        # follows the base PV's display.description for new connections --
        # there is no set_desc_record on this path (see the class docstring).
        pv = _pv_with_description("first")

        with IOCMimicServer(providers=[{"EXAMPLE:PV": pv}], isolate=True) as s:
            with Context("pva", conf=s.conf(), useenv=False) as c:
                assert c.get("EXAMPLE:PV.DESC") == "first"

            pv.post({"value": 2.0, "display": {"description": "second"}})

            with Context("pva", conf=s.conf(), useenv=False) as c:
                assert c.get("EXAMPLE:PV.DESC") == "second"

    def test_provider_with_providers_attribute_is_not_unpacked(self):
        # Only a real IOCMimicProvider is unpacked into its provider pair;
        # any other provider merely carrying a tuple-valued `.providers`
        # attribute must be passed through to p4p.server.Server untouched
        # (the former duck-typed check would hand p4p the tuple's elements
        # -- here two bare object()s -- as providers).
        class ProviderWithProvidersAttr(StaticRecordProvider):
            providers = (object(), object())

        p = ProviderWithProvidersAttr("attr")
        p.add("EXAMPLE:PV", _pv())

        with (
            IOCMimicServer(providers=[p], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("EXAMPLE:PV.RTYP") == "ai"

    def test_non_dict_providers_pass_through_unchanged(self):
        # A provider name string and an already-constructed provider instance
        # (including an explicit StaticRecordProvider) aren't dicts -- must be
        # forwarded to p4p.server.Server as-is, with no extra DynamicProvider
        # built for them (see _expand_mapping).
        explicit = StaticRecordProvider("explicit")
        explicit.add("EXPLICIT:PV", _pv())

        with (
            IOCMimicServer(providers=[explicit], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("EXPLICIT:PV.RTYP") == "ai"

    def test_mixed_dict_and_provider_entries(self):
        pvs = {"EXAMPLE:PV": _pv()}
        explicit = StaticRecordProvider("explicit")
        explicit.add("EXPLICIT:PV", _pv())

        with (
            IOCMimicServer(providers=[pvs, explicit], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("EXAMPLE:PV.RTYP") == "ai"
            assert c.get("EXPLICIT:PV.RTYP") == "ai"

    def test_dict_provider_skips_fields_for_non_inferrable_nt(self):
        # A non-record-like base PV (NTNDArray/NTTable/...) is served through the
        # dict shorthand with no "<name>.<FIELD>" sub-PVs -- as an IOC serves a
        # Q:group -- rather than defaulting to 'd' or raising. A record-like PV
        # in the same dict still gets its fields.
        pvs = {
            "EXAMPLE:IMG": SharedPV(nt=NTNDArray(), initial=numpy.zeros((4, 4))),
            "EXAMPLE:SCALAR": _pv(),
        }
        with (
            IOCMimicServer(providers=[pvs], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            # both base PVs are served
            assert c.get("EXAMPLE:IMG") is not None
            assert c.get("EXAMPLE:SCALAR") == 1.234
            # the NDArray gets no record fields; the scalar still does
            with pytest.raises(TimeoutError):
                c.get("EXAMPLE:IMG.RTYP", timeout=0.2)
            assert c.get("EXAMPLE:SCALAR.RTYP") == "ai"

    def test_dict_provider_all_non_inferrable_adds_no_field_provider(self):
        # If no dict entry is record-like, no DynamicProvider is built at all
        # (an empty registry -> None from _expand_mapping).
        pvs = {"EXAMPLE:IMG": SharedPV(nt=NTNDArray(), initial=numpy.zeros((4, 4)))}
        with IOCMimicServer(providers=[pvs], isolate=True) as s:
            assert s._keep_alive == []

    def test_dict_provider_enum_infers_mbbi_rtyp(self):
        # An NTEnum is inferrable through the dict shorthand too (valtype
        # resolves to the _ENUM_VALTYPE sentinel, not the 'd' fallback): RTYP
        # is mbbi and no ADEL/MDEL sub-PV is served.
        with (
            IOCMimicServer(providers=[{"ENUM:PV": _enum_pv()}], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("ENUM:PV.RTYP") == "mbbi"
            with pytest.raises(TimeoutError):
                c.get("ENUM:PV.ADEL", timeout=0.2)

    def test_ioc_record_provider_passed_directly(self):
        # An IOCMimicProvider isn't itself a single provider (it holds a
        # StaticProvider + DynamicProvider pair, see its own docstring) --
        # IOCMimicServer should unpack it automatically, so passing it bare
        # works the same as spreading it via *base.providers.
        base = IOCMimicProvider("base")
        base.add("EXAMPLE:PV", _pv(), dtyp_choices=["Soft Channel", "Raw Soft Channel"])
        pvs = {"EXAMPLE:PV2": _pv()}

        with (
            IOCMimicServer(providers=[base, pvs], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("EXAMPLE:PV") == 1.234
            assert c.get("EXAMPLE:PV.RTYP") == "ai"
            assert c.get("EXAMPLE:PV.DTYP").raw["value.choices"] == ["Soft Channel", "Raw Soft Channel"]
            assert c.get("EXAMPLE:PV2.RTYP") == "ai"

    def test_unpacked_ioc_record_provider_is_kept_alive(self):
        # p4p.server.Server only keeps a provider alive itself for the
        # StaticProvider it builds from a bare dict; an IOCMimicProvider we
        # unpack is ours to retain. If the caller drops their reference the
        # base PVs keep working (the C++ Server holds the StaticProvider) but
        # every "<name>.<FIELD>" sub-PV silently stops resolving, because
        # nothing holds the DynamicProvider or the registry behind it.
        base = IOCMimicProvider("base")
        base.add("EXAMPLE:PV", _pv())

        with IOCMimicServer(providers=[base], isolate=True) as s:
            del base
            gc.collect()

            with Context("pva", conf=s.conf(), useenv=False) as c:
                assert c.get("EXAMPLE:PV") == 1.234
                assert c.get("EXAMPLE:PV.RTYP") == "ai"

    def test_unpacked_ioc_record_provider_is_retained_whole(self):
        # The object-level counterpart to the test above, without the gc round
        # trip: what's retained is the whole IOCMimicProvider, not just its
        # DynamicProvider -- that also pins its StaticProvider, its registry,
        # and the base PVs the registry's weak 'pv_ref's point at.
        base = IOCMimicProvider("base")
        base.add("EXAMPLE:PV", _pv())

        _, keep_alive = _expand_providers([base])

        assert any(kept is base for kept in keep_alive)


def _effective_order(entry):
    # The order p4p.server.Server.__init__ will resolve for a providers=
    # entry: an explicit (provider, order) tuple, else an `order` attribute
    # on the provider, else 0.
    if isinstance(entry, tuple):
        return entry[1]
    return getattr(entry, "order", 0)


_MAKECHANNEL_NOISE = "must return SharedPV"


@cache
def _p4p_declines_none_silently() -> bool:
    """Whether this p4p lets a `makeChannel` handler decline by returning None.

    Feature-detected rather than version-gated: the fix exists upstream as
    epics-base/p4p#138 (a `Py_None` branch in `DynamicSource::onCreate`) but is
    unmerged and unmilestoned, so no version number implies it either way.

    Probes with a plain p4p server -- a DynamicProvider that claims nothing,
    named to sort ahead of the StaticProvider actually serving the PV so it is
    offered, and has to decline, the base name. `redirect_stderr` rather than
    `capfd` because this runs once per session, not per test: p4p reports the
    decline via `PyErr_Print`, which writes to the `sys.stderr` object.
    """

    class _ClaimsNothing:
        # Suppressions below: N802 because the names are mandated by the p4p
        # DynamicProvider protocol, ARG002 because the whole point of this
        # handler is that it ignores the name and declines regardless.
        def testChannel(self, name: str) -> bool:  # noqa: N802, ARG002
            return False

        def makeChannel(self, name: str, peer: str) -> None:  # noqa: N802, ARG002
            return None

    static = StaticProvider("probe-b-static")
    static.add("PROBE:PV", _pv())
    dynamic = DynamicProvider("probe-a-dynamic", _ClaimsNothing())

    stderr = io.StringIO()
    with (
        redirect_stderr(stderr),
        Server(providers=[static, dynamic], isolate=True) as s,
        Context("pva", conf=s.conf(), useenv=False) as c,
    ):
        c.get("PROBE:PV")
    return _MAKECHANNEL_NOISE not in stderr.getvalue()


class TestFieldProviderOrdering:
    """The lazy path's `~p4p.server.DynamicProvider` serves only
    "<name>.<FIELD>", so every base PV name it is offered it must decline.
    pvxs offers channel creation to *every* source in (order, name) sequence
    regardless of which one claimed the search -- declining is a documented,
    first-class response (pvxs `src/pvxs/source.h`) -- but p4p has no way to
    express it other than returning None from `makeChannel`, and prints
    ``TypeError: makeChannel("...") must return SharedPV, not NoneType`` to
    `sys.stderr` when it does.

    p4pillon therefore sorts its field provider onto an absolute rung
    (`_FIELD_PROVIDER_ORDER`) behind every other entry, so it is never offered
    a base PV name in the first place. Without that the diagnostic is written
    once per base-PV connection, and which way it falls is decided by the
    field provider's (random) name.
    """

    def test_field_provider_sorts_after_its_own_static(self):
        provider = IOCMimicProvider("example")
        static, dynamic = provider.providers

        assert _effective_order(dynamic) > _effective_order(static)

    @pytest.mark.parametrize(
        "make_entry", [IOCMimicProvider, lambda _: {"EXAMPLE:PV": _pv()}], ids=["provider", "dict"]
    )
    @pytest.mark.parametrize("order", [None, 0, 5])
    def test_expansion_sorts_field_provider_after_the_base_pvs(self, make_entry, order):
        # Whatever order the caller asks for, the field provider has to end up
        # behind the entry it belongs to -- including when an explicit
        # (provider, order) tuple is given, which p4p resolves in preference
        # to any `order` attribute on the provider itself.
        entry = make_entry("example")
        if isinstance(entry, IOCMimicProvider):
            entry.add("EXAMPLE:PV", _pv())
        if order is not None:
            entry = (entry, order)

        wrapped, _ = _expand_providers([entry])

        base, fields = wrapped
        assert _effective_order(fields) > _effective_order(base)

    # Each case builds a server a different way and asks for the base PV as
    # well as a sub-PV: connecting to the *base* name is what offers it to the
    # field provider, and so what would trigger the diagnostic. "zzz" as the
    # provider name rather than something realistic keeps this deterministic
    # -- the field provider's name is random, and unordered it would sort
    # before the static provider only for most names, not all.
    @pytest.mark.parametrize(
        ("make_server", "base_name"),
        [
            pytest.param(lambda p: IOCMimicServer(providers=[p], isolate=True), "EXAMPLE:PV", id="provider"),
            # An explicit (provider, order) tuple used to defeat the ordering
            # entirely, back when the field provider took the entry's order + 1.
            pytest.param(lambda p: IOCMimicServer(providers=[(p, 0)], isolate=True), "EXAMPLE:PV", id="tuple-order"),
            # The dict shorthand's own field provider, built by the expansion
            # rather than by the IOCMimicProvider -- hence ignoring `p`.
            pytest.param(lambda _: IOCMimicServer(providers=[{"DICT:PV": _pv()}], isolate=True), "DICT:PV", id="dict"),
            # Unpacked into a plain p4p Server, the way the IOCMimicProvider
            # docstring tells callers who aren't using IOCMimicServer to.
            pytest.param(lambda p: Server(providers=[*p.providers], isolate=True), "EXAMPLE:PV", id="plain-server"),
        ],
    )
    def test_serves_without_makechannel_noise(self, capfd, make_server, base_name):
        provider = IOCMimicProvider("zzz")
        provider.add("EXAMPLE:PV", _pv())

        with make_server(provider) as s, Context("pva", conf=s.conf(), useenv=False) as c:
            assert c.get(base_name) == 1.234
            assert c.get(f"{base_name}.RTYP") == "ai"

        assert _MAKECHANNEL_NOISE not in capfd.readouterr().err

    def test_no_noise_when_a_foreign_provider_is_ordered_later(self, capfd):
        # The absolute rung, rather than an offset from the entry's own order,
        # is what makes this work: a caller ordering their own provider behind
        # p4pillon's still lands in front of the field provider.
        provider = IOCMimicProvider("zzz")
        provider.add("EXAMPLE:PV", _pv())
        foreign = StaticProvider("foreign")
        foreign.add("OTHER:PV", _pv())

        with (
            IOCMimicServer(providers=[provider, (foreign, 5)], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("OTHER:PV") == 1.234

        assert _MAKECHANNEL_NOISE not in capfd.readouterr().err

    def test_two_field_providers_in_one_server_do_not_decline_each_others_names(self, capfd):
        # The one case ordering cannot fix: two field providers in one server
        # share a rung, so each is offered the other's sub-PV names and must
        # decline, whichever rung either sits on. Only serving every registry
        # from a single field provider would avoid it p4pillon-side.
        #
        # So this is xfailed on a p4p where declining is noisy -- but *run*,
        # not skipped, on one where it isn't, which is the point: the day
        # epics-base/p4p#138 lands this starts asserting the fix rather than
        # rotting. Feature-detected, so no red suite the day it does.
        if not _p4p_declines_none_silently():
            pytest.xfail("this p4p has no way for makeChannel to decline (epics-base/p4p#138 unmerged)")

        provider = IOCMimicProvider("zzz")
        provider.add("EXAMPLE:PV", _pv())

        with (
            IOCMimicServer(providers=[provider, {"DICT:PV": _pv()}], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("EXAMPLE:PV.RTYP") == "ai"
            assert c.get("DICT:PV.RTYP") == "ai"

        assert _MAKECHANNEL_NOISE not in capfd.readouterr().err


class TestDynamicRecordFields:
    """`DynamicRecordFields`: the lazy, registry-driven `~p4p.server.DynamicProvider`
    handler, building each "<name>.<FIELD>" sub-PV on demand as clients connect."""

    def test_unknown_fields_key_warns_eagerly_at_construction(self):
        # Unlike StaticRecordProvider.add(), this registry's 'fields' is never
        # otherwise inspected until (if ever) a client connects to that
        # specific record's fields -- validated eagerly here instead so the
        # typo is caught regardless of whether a client ever asks.
        # Deliberate "DESK" typo (asserts UserWarning) makes this an invalid RegistryEntry for ty.
        registry = {"EXAMPLE:PV3": {"valtype": "s", "fields": {"DESK": "typo"}}}
        with pytest.warns(UserWarning, match="DESK"):
            DynamicRecordFields(registry)  # ty: ignore[invalid-argument-type]

    def test_no_warning_for_valid_fields(self):
        registry: dict[str, RegistryEntry] = {"EXAMPLE:PV3": {"valtype": "s", "fields": {"DESC": "hello"}}}
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            DynamicRecordFields(registry)

    def test_invalid_menu_choice_raises_eagerly_at_construction(self):
        # Same eager validation as the unknown-key warning above: caught at
        # construction time, not when (if ever) a client connects.
        registry = {"EXAMPLE:PV3": {"valtype": "d", "fields": {"SCAN": "2 seconds"}}}
        with pytest.raises(ValueError, match=r"SCAN.*'1 second'"):
            DynamicRecordFields(registry)

    def test_live_get(self):
        base = {"EXAMPLE:PV3": SharedPV(nt=NTScalar("s"), initial="hello")}
        registry: dict[str, RegistryEntry] = {"EXAMPLE:PV3": {"valtype": "s"}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with (
            Server(providers=[base, field_provider], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("EXAMPLE:PV3") == "hello"
            assert c.get("EXAMPLE:PV3.NAME") == "EXAMPLE:PV3"
            assert c.get("EXAMPLE:PV3.RTYP") == "stringin"
            assert c.get("EXAMPLE:PV3.NAME$") == "EXAMPLE:PV3"
            assert c.get("EXAMPLE:PV3.RTYP$") == "stringin"

            with pytest.raises(TimeoutError):
                c.get("EXAMPLE:PV3.NOSUCHFIELD", timeout=0.2)

            with pytest.raises(TimeoutError):
                c.get("NOSUCHBASE.DESC", timeout=0.2)

            # 's' is a non-numeric valtype -- ADEL/MDEL don't apply, same
            # as StaticRecordProvider (see TestStaticRecordProvider.
            # test_adel_mdel_unreachable_for_non_numeric_pv).
            with pytest.raises(TimeoutError):
                c.get("EXAMPLE:PV3.ADEL", timeout=0.2)

    def test_adel_mdel_reachable_for_numeric_valtype(self):
        base = {"EXAMPLE:PV4": SharedPV(nt=NTScalar("l"), initial=42)}
        registry: dict[str, RegistryEntry] = {"EXAMPLE:PV4": {"valtype": "l", "fields": {"ADEL": 3, "MDEL": 1}}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with (
            Server(providers=[base, field_provider], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("EXAMPLE:PV4.ADEL") == 3
            assert c.get("EXAMPLE:PV4.MDEL") == 1

    def test_desc_from_registry_snapshot_not_fields(self):
        # No live PV reference here (see RegistryEntry's docstring) -- DESC
        # comes from the registry's 'description' entry, a one-time snapshot
        # re-read per makeChannel() call; 'fields'={"DESC": ...} is ignored,
        # same as StaticRecordProvider.
        base = {"EXAMPLE:PV5": SharedPV(nt=NTScalar("d"), initial=1.0)}
        registry: dict[str, RegistryEntry] = {
            "EXAMPLE:PV5": {"valtype": "d", "description": "snapshot description", "fields": {"DESC": "ignored"}}
        }
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with (
            Server(providers=[base, field_provider], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("EXAMPLE:PV5.DESC") == "snapshot description"
            assert c.get("EXAMPLE:PV5.DESC$") == "snapshot description"

    def test_desc_default_empty_without_registry_description(self):
        base = {"EXAMPLE:PV6": SharedPV(nt=NTScalar("d"), initial=1.0)}
        registry: dict[str, RegistryEntry] = {"EXAMPLE:PV6": {"valtype": "d"}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with (
            Server(providers=[base, field_provider], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("EXAMPLE:PV6.DESC") == ""

    def test_desc_snapshot_reread_per_connection(self):
        # Mutating the registry entry between connects is picked up on the
        # *next* connect (still just a snapshot, not a live subscription --
        # see RegistryEntry's docstring).
        base = {"EXAMPLE:PV7": SharedPV(nt=NTScalar("d"), initial=1.0)}
        registry: dict[str, RegistryEntry] = {"EXAMPLE:PV7": {"valtype": "d", "description": "first"}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with Server(providers=[base, field_provider], isolate=True) as s:
            with Context("pva", conf=s.conf(), useenv=False) as c:
                assert c.get("EXAMPLE:PV7.DESC") == "first"

            registry["EXAMPLE:PV7"]["description"] = "second"

            with Context("pva", conf=s.conf(), useenv=False) as c:
                assert c.get("EXAMPLE:PV7.DESC") == "second"


class TestIOCMimicProvider:
    """`IOCMimicProvider`: the incrementally-mutable `add()`/`remove()`
    counterpart to `StaticRecordProvider`, backed by `DynamicRecordFields`
    (the lazy path) instead of building sub-PVs eagerly."""

    def setup_method(self, _method):
        self.P = IOCMimicProvider("test")

    def test_add_creates_registry_entry_and_live_get(self):
        self.P.add("PV:NAME", _pv(), valtype="d")
        assert "PV:NAME" in self.P._registry

        with (
            Server(providers=[*self.P.providers], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("PV:NAME") == 1.234
            assert c.get("PV:NAME.NAME") == "PV:NAME"
            assert c.get("PV:NAME.RTYP") == "ai"
            assert c.get("PV:NAME.SCAN").choice == "Passive"

            with pytest.raises(TimeoutError):
                c.get("PV:NAME.NOSUCHFIELD", timeout=0.2)

    def test_served_field_is_stamped_at_connection_time(self):
        # This base PV is a plain SharedPV with no timeStamp of its own, so
        # the fields fall back to their build time -- which on the lazy path
        # is makeChannel(), i.e. when the client connected. Strictly after
        # add() here, and never the 1970-01-01 an unstamped wrap() would give.
        self.P.add("PV:NAME", _pv(), valtype="d")
        added = time.time()

        with (
            Server(providers=[*self.P.providers], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            for field in ("DESC", "RTYP", "NAME", "SCAN"):
                stamped = c.get(f"PV:NAME.{field}").timestamp
                assert added <= stamped <= time.time(), f"{field} stamped {stamped}"

    def test_served_field_tracks_the_base_pv_timestamp(self):
        # makeChannel() re-reads the base PV's timeStamp per connection, so
        # unlike the eager path a *new* connection sees the record's current
        # process time -- not a snapshot from add().
        base = SharedNT(nt=NTScalar("d"), initial=1.0)
        self.P.add("PV:NAME", base)

        with Server(providers=[*self.P.providers], isolate=True) as s:
            with Context("pva", conf=s.conf(), useenv=False) as c:
                first = c.get("PV:NAME.RTYP").timestamp
                assert first == base.current().timestamp

            time.sleep(0.01)
            base.post(2.0)  # TimestampRule re-stamps the record
            processed = base.current().timestamp
            assert processed > first

            # A fresh Context, so p4p can't hand back the cached channel.
            with Context("pva", conf=s.conf(), useenv=False) as c:
                assert c.get("PV:NAME.RTYP").timestamp == processed

    def test_set_desc_record_keeps_tracking_the_base_pv_timestamp(self):
        # An explicit DESC stops DESC tracking display.description, but must
        # not also stop the fields' timeStamps tracking the base PV (they're
        # separate concerns -- see RegistryEntry's 'desc_explicit').
        base = SharedNT(nt=NTScalar("d", display=True), initial={"value": 1.0, "display": {"description": "hello"}})
        self.P.add("PV:NAME", base)
        self.P.set_desc_record("PV:NAME", "goodbye")

        with (
            Server(providers=[*self.P.providers], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            got = c.get("PV:NAME.DESC")
            assert got == "goodbye"
            assert got.timestamp == base.current().timestamp

    def test_record_fields_false_opts_out(self):
        self.P.add("PV:NAME", _pv(), record_fields=False)
        assert "PV:NAME" not in self.P._registry

        with (
            Server(providers=[*self.P.providers], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("PV:NAME") == 1.234
            with pytest.raises(TimeoutError):
                c.get("PV:NAME.RTYP", timeout=0.2)

    def test_valtype_inferred_from_pv_nt_when_omitted(self):
        self.P.add("PV:NAME", _pv("s", "hello"))
        assert self.P._registry["PV:NAME"]["valtype"] == "s"

        with (
            Server(providers=[*self.P.providers], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("PV:NAME.RTYP") == "stringin"
            # 's' has no ADEL/MDEL
            with pytest.raises(TimeoutError):
                c.get("PV:NAME.ADEL", timeout=0.2)

    def test_explicit_valtype_overrides_inference(self):
        self.P.add("PV:NAME", _pv("s", "hello"), valtype="d")

        with (
            Server(providers=[*self.P.providers], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("PV:NAME.RTYP") == "ai"

    def test_enum_pv_infers_mbbi_rtyp(self):
        # An NTEnum is inferrable (unlike NTTable/NTNDArray): accepted with no
        # explicit RTYP and reported as mbbi (see infer_rtyp).
        self.P.add("ENUM:PV", _enum_pv())
        assert self.P._registry["ENUM:PV"]["valtype"] == _ENUM_VALTYPE

        with (
            Server(providers=[*self.P.providers], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert c.get("ENUM:PV.RTYP") == "mbbi"
            # mbbi's VAL is a DBF_ENUM index, not a plain numeric scalar
            with pytest.raises(TimeoutError):
                c.get("ENUM:PV.ADEL", timeout=0.2)

    def test_non_record_nt_served_without_fields(self):
        # A non-record PV (NTTable/NTNDArray/... -> a Q:group in a real IOC) is
        # served on its own with no registry entry (hence no "<name>.<FIELD>"
        # sub-PVs), the same as StaticRecordProvider.add, rather than raising.
        table_pv = SharedPV(nt=NTTable(columns=[("A", "d")]), initial=[{"A": 1.0}])
        self.P.add("TBL:PV", table_pv)
        assert list(self.P) == ["TBL:PV"]  # base PV served
        assert "TBL:PV" not in self.P._registry  # no record fields

    def test_rtyp_not_inferrable_accepts_explicit_override(self):
        table_pv = SharedPV(nt=NTTable(columns=[("A", "d")]), initial=[{"A": 1.0}])
        self.P.add("TBL:PV", table_pv, fields={"RTYP": "waveform"})
        assert self.P._registry["TBL:PV"]["fields"] == {"RTYP": "waveform"}

    def test_unknown_fields_key_warns_at_add_time(self):
        with pytest.warns(UserWarning, match="DESK"):
            # Deliberate "DESK" typo asserts the UserWarning; ty flags it against RecordFieldOverrides.
            self.P.add("PV:NAME", _pv(), fields={"DESK": "typo"})  # ty: ignore[invalid-argument-type, invalid-key]

    def test_failed_add_leaves_provider_unchanged(self):
        # add() must validate before serving anything: a raising add() (e.g. a
        # bad menu choice) must not leave the base PV served with no registry
        # entry.
        with pytest.raises(ValueError, match="SCAN"):
            self.P.add("PV:NAME", _pv(), fields={"SCAN": "2 seconds"})
        assert list(self.P) == []
        assert "PV:NAME" not in self.P._registry

    def test_invalid_menu_choice_raises_at_add_time(self):
        with pytest.raises(ValueError, match=r"SCAN.*'1 second'"):
            self.P.add("PV:NAME", _pv(), fields={"SCAN": "2 seconds"})
        assert list(self.P) == []

    def test_desc_tracks_base_pv_for_new_connections(self):
        # add() stores a weak reference to the base PV, and makeChannel()
        # re-reads display.description per connection -- so a later pv.post()
        # changing it IS reflected, but only for *new* connections (an
        # already-open sub-PV channel keeps the value it connected with).
        pv = _pv_with_description("hello")
        self.P.add("PV:NAME", pv, valtype="d")

        with Server(providers=[*self.P.providers], isolate=True) as s:
            with Context("pva", conf=s.conf(), useenv=False) as c:
                assert c.get("PV:NAME.DESC") == "hello"

            pv.post({"value": 1.234, "display": {"description": "changed"}})

            with Context("pva", conf=s.conf(), useenv=False) as c:
                assert c.get("PV:NAME.DESC") == "changed"

    def test_remove_cleans_up_base_and_registry(self):
        self.P.add("PV:NAME", _pv(), valtype="d")
        self.P.remove("PV:NAME")
        assert "PV:NAME" not in self.P._registry

        with (
            Server(providers=[*self.P.providers], isolate=True) as s,
            Context("pva", conf=s.conf(), useenv=False) as c,
        ):
            with pytest.raises(TimeoutError):
                c.get("PV:NAME", timeout=0.2)
            with pytest.raises(TimeoutError):
                c.get("PV:NAME.RTYP", timeout=0.2)

    def test_remove_without_fields_is_safe(self):
        self.P.add("PV:NAME", _pv(), record_fields=False)
        self.P.remove("PV:NAME")  # must not raise

    def test_providers_property(self):
        assert self.P.providers == (self.P._static, self.P._dynamic)

    def test_keys_lists_base_pv_names(self):
        # p4p's StaticProvider has keys(); StaticRecordProvider subclasses it
        # and so inherits one, but this class only mixes in the container
        # dunders -- it needs its own to match. Base PV names only, sub-PVs
        # aren't enumerable on the lazy path (see the class docstring).
        self.P.add("PV:ONE", _pv())
        self.P.add("PV:TWO", _pv(), record_fields=False)

        assert sorted(self.P.keys()) == ["PV:ONE", "PV:TWO"]
        assert sorted(self.P.keys()) == sorted(self.P)

    def test_set_desc_record_updates_registry_for_new_connections_only(self):
        # No live sub-PV channel here (unlike StaticRecordProvider) -- an
        # already-open connection keeps the value it connected with; only a
        # *new* connection picks up the update. The explicit override also
        # wins over the base PV's own display.description ("initial
        # description" throughout) and any later change to it: it stops the
        # automatic tracking for this record.
        pv = _pv_with_description("initial description")
        self.P.add("PV:NAME", pv, valtype="d")

        with Server(providers=[*self.P.providers], isolate=True) as s:
            with Context("pva", conf=s.conf(), useenv=False) as c:
                assert c.get("PV:NAME.DESC") == "initial description"

                self.P.set_desc_record("PV:NAME", "updated description")

                assert c.get("PV:NAME.DESC") == "initial description"

            pv.post({"value": 1.234, "display": {"description": "post-override change"}})

            with Context("pva", conf=s.conf(), useenv=False) as c:
                assert c.get("PV:NAME.DESC") == "updated description"

    def test_set_desc_record_raises_for_unknown_name(self):
        with pytest.raises(KeyError):
            self.P.set_desc_record("NOSUCH:PV", "x")

    def test_set_desc_record_raises_when_record_fields_false(self):
        self.P.add("PV:NAME", _pv_with_description("x"), record_fields=False)
        with pytest.raises(KeyError):
            self.P.set_desc_record("PV:NAME", "y")


def _async_pv(valtype="d", initial=1.234):
    return AsyncSharedPV(nt=NTScalar(valtype), initial=initial)


class TestStaticRecordProviderAsyncio:
    """`StaticRecordProvider` against asyncio-flavored PVs/`Context` -- field
    value semantics themselves are covered once, for the thread flavor, by
    `TestStaticRecordProvider`."""

    async def test_live_get(self):
        # Field-value semantics (defaults, overrides, RTYP inference, etc)
        # are covered by TestStaticRecordProvider.test_live_get; this only
        # confirms the same StaticRecordProvider works against an
        # asyncio-flavored PV/Context.
        p = StaticRecordProvider("test")
        p.add("EXAMPLE:PV", _async_pv(), valtype="d")

        with Server(providers=[p], isolate=True) as s, AsyncContext("pva", conf=s.conf(), useenv=False) as c:
            assert (await c.get("EXAMPLE:PV")) == 1.234
            assert (await c.get("EXAMPLE:PV.NAME")) == "EXAMPLE:PV"
            assert (await c.get("EXAMPLE:PV.RTYP")) == "ai"

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(c.get("EXAMPLE:PV.NOSUCHFIELD"), timeout=0.2)

    async def test_mixed_pv_flavors(self):
        # A single StaticRecordProvider can mix thread- and asyncio-flavored base
        # PVs; each record's own "<name>.<FIELD>" sub-PVs are built with the
        # plain p4pillon SharedPV class of the matching concurrency flavor --
        # deliberately NOT type(pv) itself, so a concrete subclass (e.g. one
        # with its own handlers, like SharedNT) is never propagated to the
        # sub-PVs (see test_sharednt_base_gets_plain_readonly_sub_pvs).
        class TrackedThreadPV(SharedPV):
            pass

        class TrackedAsyncPV(AsyncSharedPV):
            pass

        p = StaticRecordProvider("test")
        p.add("EXAMPLE:THREAD", TrackedThreadPV(nt=NTScalar("d"), initial=1.234), valtype="d")
        p.add("EXAMPLE:ASYNC", TrackedAsyncPV(nt=NTScalar("d"), initial=2.345), valtype="d")

        thread_fields = p._field_pvs["EXAMPLE:THREAD"]
        async_fields = p._field_pvs["EXAMPLE:ASYNC"]
        assert set(thread_fields) == FIELD_NAMES
        assert set(async_fields) == FIELD_NAMES
        assert all(type(f) is SharedPV for f in thread_fields.values())
        assert all(type(f) is AsyncSharedPV for f in async_fields.values())

        with Server(providers=[p], isolate=True) as s, AsyncContext("pva", conf=s.conf(), useenv=False) as c:
            assert (await c.get("EXAMPLE:THREAD")) == 1.234
            assert (await c.get("EXAMPLE:THREAD.NAME")) == "EXAMPLE:THREAD"
            assert (await c.get("EXAMPLE:ASYNC")) == 2.345
            assert (await c.get("EXAMPLE:ASYNC.NAME")) == "EXAMPLE:ASYNC"


class TestDynamicRecordFieldsAsyncio:
    """`DynamicRecordFields` against an asyncio-flavored base PV/`Context`,
    including the `pv_factory` flavor restriction that only applies here."""

    async def test_live_get(self):
        # DynamicRecordFields.makeChannel() is always called by the server's own
        # internal I/O thread, never the asyncio event loop thread, so its field
        # sub-PVs must stay thread-flavored (the default) even though the base PV
        # and client here are asyncio-flavored -- see DynamicRecordFields' pv_factory
        # docstring.
        base = {"EXAMPLE:PV3": _async_pv("s", "hello")}
        registry: dict[str, RegistryEntry] = {"EXAMPLE:PV3": {"valtype": "s"}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with (
            Server(providers=[base, field_provider], isolate=True) as s,
            AsyncContext("pva", conf=s.conf(), useenv=False) as c,
        ):
            assert (await c.get("EXAMPLE:PV3")) == "hello"
            assert (await c.get("EXAMPLE:PV3.NAME")) == "EXAMPLE:PV3"
            assert (await c.get("EXAMPLE:PV3.RTYP")) == "stringin"

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(c.get("EXAMPLE:PV3.NOSUCHFIELD"), timeout=0.2)

    @pytest.mark.parametrize("async_pv_class", [AsyncSharedPV, RawAsyncSharedPV])
    def test_pv_factory_rejects_asyncio_flavor(self, async_pv_class):
        # Caught eagerly at construction time -- see the pv_factory docstring for
        # why an asyncio-flavored pv_factory can never work here. Checked against
        # both p4pillon.server.asyncio.SharedPV (AsyncSharedPV) and the raw p4p
        # class it subclasses, so rejection doesn't depend on going through
        # p4pillon's own subclass.
        registry: dict[str, RegistryEntry] = {"EXAMPLE:PV3": {"valtype": "s"}}
        with pytest.raises(TypeError, match="is not safe for DynamicRecordFields"):
            DynamicRecordFields(registry, pv_factory=async_pv_class)

        class SubclassedAsyncPV(async_pv_class):
            pass

        with pytest.raises(TypeError, match="is not safe for DynamicRecordFields"):
            DynamicRecordFields(registry, pv_factory=SubclassedAsyncPV)
