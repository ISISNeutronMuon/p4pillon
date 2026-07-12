import asyncio
import warnings

import numpy
import pytest
from p4p.client.asyncio import Context as AsyncContext
from p4p.client.thread import Context, TimeoutError
from p4p.nt import NTNDArray, NTScalar, NTTable
from p4p.server import DynamicProvider, Server

from p4pillon.server.asyncio import SharedPV as AsyncSharedPV
from p4pillon.server.records import (
    FIELD_NAMES,
    STRING_FIELDS,
    DynamicRecordFields,
    RecordFieldOverrides,
    IOCChannelProvider,
    _supports_handler_hooks,
    build_record_fields,
    infer_rtyp,
)
from p4pillon.server.thread import SharedPV


class TestInferRtyp:
    def test_infer_rtyp(self):
        assert infer_rtyp('d') == "ai"
        assert infer_rtyp('f') == "ai"
        assert infer_rtyp('s') == "stringin"
        assert infer_rtyp('i') == "longin"
        assert infer_rtyp('ad') == "waveform"
        assert infer_rtyp('?') == "bi"


class TestBuildRecordFields:
    def test_all_fields_built(self):
        built = build_record_fields("PV:NAME", 'd')
        assert set(built) == FIELD_NAMES

    def test_name_mirrors_basename_and_is_not_overridable(self):
        built = build_record_fields("PV:NAME", 'd', fields={"NAME": "ignored"})
        assert built["NAME"]['value'] == "PV:NAME"

    def test_rtyp_inferred_and_overridable(self):
        built = build_record_fields("PV:NAME", 'd')
        assert built["RTYP"]['value'] == "ai"

        built = build_record_fields("PV:NAME", 'd', fields={"RTYP": "waveform"})
        assert built["RTYP"]['value'] == "waveform"

    def test_dtyp_default_and_choices(self):
        built = build_record_fields("PV:NAME", 'd')
        assert built["DTYP"]['value.choices'] == ["Soft Channel"]
        assert built["DTYP"]['value.index'] == 0

        built = build_record_fields("PV:NAME", 'd',
                                     dtyp_choices=["Soft Channel", "Raw Soft Channel"],
                                     fields={"DTYP": "Raw Soft Channel"})
        assert built["DTYP"]['value.index'] == 1

    def test_menu_field_default_and_override(self):
        built = build_record_fields("PV:NAME", 'd')
        assert built["SCAN"]['value.choices'][built["SCAN"]['value.index']] == "Passive"
        assert built["STAT"]['value.choices'][built["STAT"]['value.index']] == "UDF"

        built = build_record_fields("PV:NAME", 'd', fields={"SCAN": "1 second"})
        assert built["SCAN"]['value.choices'][built["SCAN"]['value.index']] == "1 second"

    def test_scalar_field_default_and_override(self):
        built = build_record_fields("PV:NAME", 'd')
        assert built["ASG"]['value'] == ""

        built = build_record_fields("PV:NAME", 'd', fields={"ASG": "hello"})
        assert built["ASG"]['value'] == "hello"

    def test_desc_mirrors_description_param_and_is_not_overridable(self):
        built = build_record_fields("PV:NAME", 'd')
        assert built["DESC"]['value'] == ""

        built = build_record_fields("PV:NAME", 'd', description="from display.description")
        assert built["DESC"]['value'] == "from display.description"

        # 'fields' is ignored for DESC, same as NAME -- description= is the
        # only way to set it.
        built = build_record_fields("PV:NAME", 'd', fields={"DESC": "ignored"},
                                     description="from display.description")
        assert built["DESC"]['value'] == "from display.description"

    def test_adel_mdel_included_for_numeric_valtype_and_matches_it(self):
        built = build_record_fields("PV:NAME", 'd')
        assert built["ADEL"]['value'] == 0.0
        assert built["MDEL"]['value'] == 0.0

        built = build_record_fields("PV:NAME", 'l', fields={"ADEL": 5, "MDEL": 1})
        assert built["ADEL"]['value'] == 5
        assert built["MDEL"]['value'] == 1

    def test_adel_mdel_omitted_for_non_numeric_valtype(self):
        built = build_record_fields("PV:NAME", 's')
        assert "ADEL" not in built
        assert "MDEL" not in built
        assert set(built) == FIELD_NAMES - {"ADEL", "MDEL"}

        built = build_record_fields("PV:NAME", '?')
        assert "ADEL" not in built
        assert "MDEL" not in built

        built = build_record_fields("PV:NAME", 'ad', fields={"RTYP": "waveform"})
        assert "ADEL" not in built
        assert "MDEL" not in built

    def test_string_field_dollar_alias_mirrors_value(self):
        assert STRING_FIELDS == {"DESC", "ASG", "EVNT", "TSEL", "SDIS", "AMSG",
                                  "NAMSG", "FLNK", "NAME", "RTYP"}

        built = build_record_fields("PV:NAME", 'd', fields={"RTYP": "waveform"},
                                     description="hello")
        for fieldname in STRING_FIELDS:
            assert built[f"{fieldname}$"]['value'] == built[fieldname]['value']
        assert built["DESC$"]['value'] == "hello"
        assert built["RTYP$"]['value'] == "waveform"
        assert built["NAME$"]['value'] == "PV:NAME"

    def test_non_string_field_has_no_dollar_alias(self):
        built = build_record_fields("PV:NAME", 'd')
        for fieldname in set(FIELD_NAMES) - STRING_FIELDS - {"ADEL", "MDEL"}:
            if fieldname.endswith("$"):
                continue
            assert f"{fieldname}$" not in built

    def test_unknown_fields_key_warns_but_does_not_raise(self):
        with pytest.warns(UserWarning, match="DESK"):
            built = build_record_fields("PV:NAME", 'd', fields={"ASG": "hello", "DESK": "typo"})
        assert built["ASG"]['value'] == "hello"
        assert "DESK" not in built

    def test_no_warning_for_valid_fields(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            build_record_fields("PV:NAME", 'd', fields={"DESC": "hello", "RTYP": "waveform"})


class TestRecordFieldOverridesTyping:
    def test_matches_field_names(self):
        # RecordFieldOverrides is hand-written (TypedDict's functional form
        # needs a literal dict, not one built from FIELD_NAMES) -- this is
        # the drift guard that keeps it honest as fields are added/removed
        # from COMMON_FIELDS/STRING_FIELDS.
        assert RecordFieldOverrides.__optional_keys__ == FIELD_NAMES
        assert not RecordFieldOverrides.__required_keys__


def _pv(valtype='d', initial=1.234):
    return SharedPV(nt=NTScalar(valtype), initial=initial)


def _pv_with_description(description=None, valtype='d', initial=1.234):
    value = {"value": initial}
    if description is not None:
        value["display"] = {"description": description}
    return SharedPV(nt=NTScalar(valtype, display=True), initial=value)


class TestIOCChannelProvider:
    def setup_method(self, _method):
        self.P = IOCChannelProvider("test")

    def test_add_creates_field_pvs(self):
        self.P.add("PV:NAME", _pv(), valtype='d')
        keys = set(self.P.keys())
        assert "PV:NAME" in keys
        for field in FIELD_NAMES:
            assert f"PV:NAME.{field}" in keys

    def test_record_fields_false_opts_out(self):
        self.P.add("PV:NAME", _pv(), record_fields=False)
        assert list(self.P.keys()) == ["PV:NAME"]

    def test_valtype_inferred_from_pv_nt_when_omitted(self):
        # pv.nt is an NTScalar('s') -- valtype (and so RTYP/ADEL-MDEL
        # applicability) should be inferred from that, not silently
        # defaulted to 'd'/"ai".
        self.P.add("PV:NAME", _pv('s', "hello"))
        keys = set(self.P.keys())
        assert "PV:NAME.ADEL" not in keys  # 's' has no ADEL/MDEL
        assert "PV:NAME.MDEL" not in keys

        with Server(providers=[self.P], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("PV:NAME.RTYP") == "stringin"

    def test_explicit_valtype_overrides_inference(self):
        # pv.nt is NTScalar('s'), but an explicit valtype takes precedence
        # over whatever could be inferred from pv.nt.
        self.P.add("PV:NAME", _pv('s', "hello"), valtype='d')

        with Server(providers=[self.P], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("PV:NAME.RTYP") == "ai"

    def test_valtype_defaults_to_d_when_not_inferrable(self):
        # A hand-built PV (no nt=) has no pv.nt to infer from -- falls back
        # to 'd', same as before this default became conditional.
        value = NTScalar('l').wrap(5)
        self.P.add("PV:NAME", SharedPV(initial=value))

        with Server(providers=[self.P], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("PV:NAME.RTYP") == "ai"
                assert "PV:NAME.ADEL" in self.P.keys()

    def test_remove_cleans_up_fields(self):
        self.P.add("PV:NAME", _pv(), valtype='d')
        assert len(self.P.keys()) > 1
        self.P.remove("PV:NAME")
        assert list(self.P.keys()) == []

    def test_remove_without_fields_is_safe(self):
        self.P.add("PV:NAME", _pv(), record_fields=False)
        self.P.remove("PV:NAME")  # must not raise
        assert list(self.P.keys()) == []

    def test_adel_mdel_omitted_for_non_numeric_pv_and_remove_still_clean(self):
        self.P.add("PV:NAME", _pv('s', "hello"), valtype='s')
        keys = set(self.P.keys())
        assert "PV:NAME.ADEL" not in keys
        assert "PV:NAME.MDEL" not in keys
        for field in FIELD_NAMES - {"ADEL", "MDEL"}:
            assert f"PV:NAME.{field}" in keys

        self.P.remove("PV:NAME")  # must not raise despite ADEL/MDEL never having been added
        assert list(self.P.keys()) == []

    def _check_rtyp_required_for(self, name, make_img, make_tbl):
        # infer_rtyp() has no plausible guess for a structural PV.  Rejected
        # without an explicit RTYP override, accepted with one.
        with pytest.raises(ValueError):
            self.P.add(f"EXAMPLE:{name}_IMG", make_img(), valtype='d')
        with pytest.raises(ValueError):
            self.P.add(f"EXAMPLE:{name}_TBL", make_tbl(), valtype='d')

        self.P.add(f"EXAMPLE:{name}_IMG2", make_img(), valtype='d', fields={"RTYP": "waveform"})
        assert f"EXAMPLE:{name}_IMG2.RTYP" in self.P.keys()

        self.P.add(f"EXAMPLE:{name}_TBL2", make_tbl(), valtype='d', fields={"RTYP": "waveform"})
        assert f"EXAMPLE:{name}_TBL2.RTYP" in self.P.keys()

    @pytest.mark.xfail(
        reason="p4pillon.server.raw.SharedPV.open() double-wraps its 'initial' value "
               "(wraps once itself, then again inside the original p4p open() it calls) "
               "-- harmless/idempotent for NTScalar but crashes for NTNDArray/NTTable. "
               "Pre-existing bug, unrelated to IOCChannelProvider; needs its own fix.",
        raises=ValueError,
    )
    def test_rtyp_required_for_non_scalar_nt(self):
        # Detected via pv.nt (set by SharedPV(nt=...)) rather than the
        # 'valtype' string, which can't distinguish an NTNDArray/NTTable-backed
        # PV from an NTScalar one.
        def img():
            return SharedPV(nt=NTNDArray(), initial=numpy.zeros((4, 4)))

        def tbl():
            return SharedPV(nt=NTTable(columns=[('A', 'd')]), initial=[{'A': 1.0}])

        self._check_rtyp_required_for("NT", img, tbl)

    def test_rtyp_required_for_hand_built_non_scalar_value(self):
        # Same as test_rtyp_required_for_non_scalar_nt, but for a PV built
        # directly from a plain Value (no nt=) -- pv.nt is never set for
        # this, so detection instead falls back to the Value's own
        # structure ID (see _struct_id_of_current).
        img_value = NTNDArray().wrap(numpy.zeros((4, 4)))
        table_value = NTTable(columns=[('A', 'd')]).wrap([{'A': 1.0}])

        self._check_rtyp_required_for(
            "HAND",
            lambda: SharedPV(initial=img_value),
            lambda: SharedPV(initial=table_value))

    @pytest.mark.xfail(
        reason="p4pillon.server.raw.SharedPV.open() double-wraps its 'initial' value "
               "-- see test_rtyp_required_for_non_scalar_nt.",
        raises=ValueError,
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

        scalar_pv = _CountingCurrentPV(nt=NTScalar('d'), initial=1.234)
        self.P.add("EXAMPLE:FASTSCALAR", scalar_pv, valtype='d')
        assert scalar_pv.current_calls == 0

        ndarray_pv = _CountingCurrentPV(nt=NTNDArray(), initial=numpy.zeros((4, 4)))
        with pytest.raises(ValueError):
            self.P.add("EXAMPLE:FASTIMG", ndarray_pv, valtype='d')
        assert ndarray_pv.current_calls == 0

    def test_live_get(self):
        self.P.add("EXAMPLE:PV", _pv_with_description("An example ai-like record"),
                    valtype='d',
                    dtyp_choices=["Soft Channel", "Raw Soft Channel"],
                    fields={"SCAN": "1 second", "ADEL": 0.5, "MDEL": 0.1})

        with Server(providers=[self.P], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV") == 1.234
                assert C.get("EXAMPLE:PV.NAME") == "EXAMPLE:PV"
                assert C.get("EXAMPLE:PV.RTYP") == "ai"
                assert C.get("EXAMPLE:PV.DESC") == "An example ai-like record"
                assert C.get("EXAMPLE:PV.ADEL") == 0.5
                assert C.get("EXAMPLE:PV.MDEL") == 0.1

                assert C.get("EXAMPLE:PV.DESC$") == "An example ai-like record"
                assert C.get("EXAMPLE:PV.NAME$") == "EXAMPLE:PV"
                assert C.get("EXAMPLE:PV.RTYP$") == "ai"

                dtyp = C.get("EXAMPLE:PV.DTYP")
                assert dtyp.choice == "Soft Channel"

                scan = C.get("EXAMPLE:PV.SCAN")
                assert scan.choice == "1 second"

                stat = C.get("EXAMPLE:PV.STAT")
                assert stat.choice == "UDF"

    def test_desc_default_empty_without_display_description(self):
        self.P.add("EXAMPLE:PV", _pv(), valtype='d')

        with Server(providers=[self.P], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV.DESC") == ""
                assert C.get("EXAMPLE:PV.DESC$") == ""

    def test_desc_not_settable_via_fields(self):
        pv = _pv_with_description("real description")
        self.P.add("EXAMPLE:PV", pv, valtype='d', fields={"DESC": "ignored"})

        with Server(providers=[self.P], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV.DESC") == "real description"

    def test_desc_tracks_display_description_live_after_add(self):
        pv = _pv_with_description("initial description")
        self.P.add("EXAMPLE:PV", pv, valtype='d')

        with Server(providers=[self.P], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV.DESC") == "initial description"

                pv.post({"display": {"description": "updated description"}})

                assert C.get("EXAMPLE:PV.DESC") == "updated description"
                assert C.get("EXAMPLE:PV.DESC$") == "updated description"

                # An unrelated post (not touching display.description) must
                # not blank DESC back out -- only fields actually marked
                # changed in a given post() are applied at all.
                pv.post(2.5)
                assert C.get("EXAMPLE:PV") == 2.5
                assert C.get("EXAMPLE:PV.DESC") == "updated description"

    def test_desc_sync_handler_delegates_to_original_handler(self):
        put_calls = []

        class _Handler:
            def put(self, pv, op):
                put_calls.append(op.value())
                op.done()

        pv = SharedPV(handler=_Handler(), nt=NTScalar('d', display=True),
                      initial={"value": 1.0, "display": {"description": "x"}})
        self.P.add("EXAMPLE:PV", pv, valtype='d')

        with Server(providers=[self.P], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                C.put("EXAMPLE:PV", 9.0)
                assert put_calls == [9.0]
                assert C.get("EXAMPLE:PV.DESC") == "x"

    def test_desc_sync_handler_restored_on_remove(self):
        pv = _pv_with_description("desc")
        original_handler = pv._handler
        self.P.add("EXAMPLE:PV", pv, valtype='d')
        assert pv._handler is not original_handler

        self.P.remove("EXAMPLE:PV")
        assert pv._handler is original_handler

    def test_supports_handler_hooks_detects_p4pillon_flavor(self):
        # Unit-level check of the isinstance test IOCChannelProvider.add() uses
        # to decide whether live DESC tracking is even possible (see
        # _DescriptionSyncHandler/_supports_handler_hooks) -- deliberately
        # not exercised against a real p4p.server.thread.SharedPV/
        # p4p.server.cothread.SharedPV instance here: importing
        # p4p.server.thread directly, before p4pillon.server.thread has run
        # its (import-order-sensitive) monkey-patch of p4p.server.raw.SharedPV,
        # silently breaks that patch for the rest of the process -- see
        # p4pillon/server/thread.py's own comment on this fragility.
        assert _supports_handler_hooks(_pv()) is True

        class _NotAPatchedSharedPV:
            pass

        assert _supports_handler_hooks(_NotAPatchedSharedPV()) is False

    def test_no_such_field_times_out(self):
        self.P.add("EXAMPLE:PV", _pv(), valtype='d')

        with Server(providers=[self.P], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                with pytest.raises(TimeoutError):
                    C.get("EXAMPLE:PV.NOSUCHFIELD", timeout=0.2)

    def test_adel_mdel_unreachable_for_non_numeric_pv(self):
        self.P.add("EXAMPLE:STR", _pv('s', "hello"), valtype='s')

        with Server(providers=[self.P], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:STR") == "hello"
                with pytest.raises(TimeoutError):
                    C.get("EXAMPLE:STR.ADEL", timeout=0.2)
                with pytest.raises(TimeoutError):
                    C.get("EXAMPLE:STR.MDEL", timeout=0.2)


class TestDynamicRecordFields:
    def test_unknown_fields_key_warns_eagerly_at_construction(self):
        # Unlike IOCChannelProvider.add(), this registry's 'fields' is never
        # otherwise inspected until (if ever) a client connects to that
        # specific record's fields -- validated eagerly here instead so the
        # typo is caught regardless of whether a client ever asks.
        registry = {"EXAMPLE:PV3": {"valtype": 's', "fields": {"DESK": "typo"}}}
        with pytest.warns(UserWarning, match="DESK"):
            DynamicRecordFields(registry)

    def test_no_warning_for_valid_fields(self):
        registry = {"EXAMPLE:PV3": {"valtype": 's', "fields": {"DESC": "hello"}}}
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            DynamicRecordFields(registry)

    def test_live_get(self):
        base = {"EXAMPLE:PV3": SharedPV(nt=NTScalar('s'), initial="hello")}
        registry = {"EXAMPLE:PV3": {"valtype": 's'}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with Server(providers=[base, field_provider], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV3") == "hello"
                assert C.get("EXAMPLE:PV3.NAME") == "EXAMPLE:PV3"
                assert C.get("EXAMPLE:PV3.RTYP") == "stringin"
                assert C.get("EXAMPLE:PV3.NAME$") == "EXAMPLE:PV3"
                assert C.get("EXAMPLE:PV3.RTYP$") == "stringin"

                with pytest.raises(TimeoutError):
                    C.get("EXAMPLE:PV3.NOSUCHFIELD", timeout=0.2)

                with pytest.raises(TimeoutError):
                    C.get("NOSUCHBASE.DESC", timeout=0.2)

                # 's' is a non-numeric valtype -- ADEL/MDEL don't apply, same
                # as IOCChannelProvider (see TestIOCChannelProvider.
                # test_adel_mdel_unreachable_for_non_numeric_pv).
                with pytest.raises(TimeoutError):
                    C.get("EXAMPLE:PV3.ADEL", timeout=0.2)

    def test_adel_mdel_reachable_for_numeric_valtype(self):
        base = {"EXAMPLE:PV4": SharedPV(nt=NTScalar('l'), initial=42)}
        registry = {"EXAMPLE:PV4": {"valtype": 'l', "fields": {"ADEL": 3, "MDEL": 1}}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with Server(providers=[base, field_provider], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV4.ADEL") == 3
                assert C.get("EXAMPLE:PV4.MDEL") == 1

    def test_desc_from_registry_snapshot_not_fields(self):
        # No live PV reference here (see RegistryEntry's docstring) -- DESC
        # comes from the registry's 'description' entry, a one-time snapshot
        # re-read per makeChannel() call; 'fields'={"DESC": ...} is ignored,
        # same as IOCChannelProvider.
        base = {"EXAMPLE:PV5": SharedPV(nt=NTScalar('d'), initial=1.0)}
        registry = {"EXAMPLE:PV5": {"valtype": 'd', "description": "snapshot description",
                                     "fields": {"DESC": "ignored"}}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with Server(providers=[base, field_provider], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV5.DESC") == "snapshot description"
                assert C.get("EXAMPLE:PV5.DESC$") == "snapshot description"

    def test_desc_default_empty_without_registry_description(self):
        base = {"EXAMPLE:PV6": SharedPV(nt=NTScalar('d'), initial=1.0)}
        registry = {"EXAMPLE:PV6": {"valtype": 'd'}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with Server(providers=[base, field_provider], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV6.DESC") == ""

    def test_desc_snapshot_reread_per_connection(self):
        # Mutating the registry entry between connects is picked up on the
        # *next* connect (still just a snapshot, not a live subscription --
        # see RegistryEntry's docstring).
        base = {"EXAMPLE:PV7": SharedPV(nt=NTScalar('d'), initial=1.0)}
        registry = {"EXAMPLE:PV7": {"valtype": 'd', "description": "first"}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with Server(providers=[base, field_provider], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV7.DESC") == "first"

            registry["EXAMPLE:PV7"]["description"] = "second"

            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV7.DESC") == "second"


def _async_pv(valtype='d', initial=1.234):
    return AsyncSharedPV(nt=NTScalar(valtype), initial=initial)


class TestIOCChannelProviderAsyncio:
    async def test_live_get(self):
        # Field-value semantics (defaults, overrides, RTYP inference, etc)
        # are covered by TestIOCChannelProvider.test_live_get; this only
        # confirms the same IOCChannelProvider works against an
        # asyncio-flavored PV/Context.
        P = IOCChannelProvider("test")
        P.add("EXAMPLE:PV", _async_pv(), valtype='d')

        with Server(providers=[P], isolate=True) as S:
            with AsyncContext('pva', conf=S.conf(), useenv=False) as C:
                assert (await C.get("EXAMPLE:PV")) == 1.234
                assert (await C.get("EXAMPLE:PV.NAME")) == "EXAMPLE:PV"
                assert (await C.get("EXAMPLE:PV.RTYP")) == "ai"

                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(C.get("EXAMPLE:PV.NOSUCHFIELD"), timeout=0.2)

    async def test_mixed_pv_flavors(self):
        # A single IOCChannelProvider can mix thread- and asyncio-flavored base
        # PVs; each record's own "<name>.<FIELD>" sub-PVs are built using
        # that same PV's class (type(pv)), so they automatically use the
        # same concurrency model rather than a single flavor for the whole
        # provider.
        thread_instances = []
        async_instances = []

        class TrackedThreadPV(SharedPV):
            def __init__(self, **kw):
                super().__init__(**kw)
                thread_instances.append(self)

        class TrackedAsyncPV(AsyncSharedPV):
            def __init__(self, **kw):
                super().__init__(**kw)
                async_instances.append(self)

        P = IOCChannelProvider("test")
        P.add("EXAMPLE:THREAD", TrackedThreadPV(nt=NTScalar('d'), initial=1.234), valtype='d')
        P.add("EXAMPLE:ASYNC", TrackedAsyncPV(nt=NTScalar('d'), initial=2.345), valtype='d')

        # one base PV plus one per field, all of the matching flavor
        assert len(thread_instances) == 1 + len(FIELD_NAMES)
        assert len(async_instances) == 1 + len(FIELD_NAMES)
        assert all(isinstance(pv, SharedPV) for pv in thread_instances)
        assert all(isinstance(pv, AsyncSharedPV) for pv in async_instances)

        with Server(providers=[P], isolate=True) as S:
            with AsyncContext('pva', conf=S.conf(), useenv=False) as C:
                assert (await C.get("EXAMPLE:THREAD")) == 1.234
                assert (await C.get("EXAMPLE:THREAD.NAME")) == "EXAMPLE:THREAD"
                assert (await C.get("EXAMPLE:ASYNC")) == 2.345
                assert (await C.get("EXAMPLE:ASYNC.NAME")) == "EXAMPLE:ASYNC"


class TestDynamicRecordFieldsAsyncio:
    async def test_live_get(self):
        # DynamicRecordFields.makeChannel() is always called by the server's own
        # internal I/O thread, never the asyncio event loop thread, so its field
        # sub-PVs must stay thread-flavored (the default) even though the base PV
        # and client here are asyncio-flavored -- see DynamicRecordFields' pv_factory
        # docstring.
        base = {"EXAMPLE:PV3": _async_pv('s', "hello")}
        registry = {"EXAMPLE:PV3": {"valtype": 's'}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with Server(providers=[base, field_provider], isolate=True) as S:
            with AsyncContext('pva', conf=S.conf(), useenv=False) as C:
                assert (await C.get("EXAMPLE:PV3")) == "hello"
                assert (await C.get("EXAMPLE:PV3.NAME")) == "EXAMPLE:PV3"
                assert (await C.get("EXAMPLE:PV3.RTYP")) == "stringin"

                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(C.get("EXAMPLE:PV3.NOSUCHFIELD"), timeout=0.2)

    def test_pv_factory_rejects_asyncio_flavor(self):
        # Caught eagerly at construction time -- see the pv_factory docstring for
        # why an asyncio-flavored pv_factory can never work here.
        registry = {"EXAMPLE:PV3": {"valtype": 's'}}
        with pytest.raises(ValueError):
            DynamicRecordFields(registry, pv_factory=AsyncSharedPV)

        class SubclassedAsyncPV(AsyncSharedPV):
            pass

        with pytest.raises(ValueError):
            DynamicRecordFields(registry, pv_factory=SubclassedAsyncPV)
