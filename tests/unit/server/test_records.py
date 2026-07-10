import asyncio

import numpy
import pytest
from p4p.client.asyncio import Context as AsyncContext
from p4p.client.thread import Context, TimeoutError
from p4p.nt import NTNDArray, NTScalar, NTTable
from p4p.server import DynamicProvider, Server

from p4pillon.server.asyncio import SharedPV as AsyncSharedPV
from p4pillon.server.records import (
    FIELD_NAMES,
    DynamicRecordFields,
    RecordProvider,
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
        assert built["DESC"]['value'] == ""

        built = build_record_fields("PV:NAME", 'd', fields={"DESC": "hello"})
        assert built["DESC"]['value'] == "hello"


def _pv(valtype='d', initial=1.234):
    return SharedPV(nt=NTScalar(valtype), initial=initial)


class TestRecordProvider:
    def test_add_creates_field_pvs(self):
        P = RecordProvider("test")
        P.add("PV:NAME", _pv(), valtype='d')
        keys = set(P.keys())
        assert "PV:NAME" in keys
        for field in FIELD_NAMES:
            assert f"PV:NAME.{field}" in keys

    def test_record_fields_false_opts_out(self):
        P = RecordProvider("test")
        P.add("PV:NAME", _pv(), record_fields=False)
        assert list(P.keys()) == ["PV:NAME"]

    def test_remove_cleans_up_fields(self):
        P = RecordProvider("test")
        P.add("PV:NAME", _pv(), valtype='d')
        assert len(P.keys()) > 1
        P.remove("PV:NAME")
        assert list(P.keys()) == []

    def test_remove_without_fields_is_safe(self):
        P = RecordProvider("test")
        P.add("PV:NAME", _pv(), record_fields=False)
        P.remove("PV:NAME")  # must not raise
        assert list(P.keys()) == []

    def _check_rtyp_required_for(self, name, img_pv, tbl_pv, img_pv2, tbl_pv2):
        # infer_rtyp() has no plausible guess for a structural PV.  Rejected
        # without an explicit RTYP override, accepted with one.
        P = RecordProvider("test")

        with pytest.raises(ValueError):
            P.add(f"EXAMPLE:{name}_IMG", img_pv, valtype='d')
        with pytest.raises(ValueError):
            P.add(f"EXAMPLE:{name}_TBL", tbl_pv, valtype='d')

        P.add(f"EXAMPLE:{name}_IMG2", img_pv2, valtype='d', fields={"RTYP": "waveform"})
        assert f"EXAMPLE:{name}_IMG2.RTYP" in P.keys()

        P.add(f"EXAMPLE:{name}_TBL2", tbl_pv2, valtype='d', fields={"RTYP": "waveform"})
        assert f"EXAMPLE:{name}_TBL2.RTYP" in P.keys()

    @pytest.mark.xfail(
        reason="p4pillon.server.raw.SharedPV.open() double-wraps its 'initial' value "
               "(wraps once itself, then again inside the original p4p open() it calls) "
               "-- harmless/idempotent for NTScalar but crashes for NTNDArray/NTTable. "
               "Pre-existing bug, unrelated to RecordProvider; needs its own fix.",
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

        self._check_rtyp_required_for("NT", img(), tbl(), img(), tbl())

    def test_rtyp_required_for_hand_built_non_scalar_value(self):
        # Same as test_rtyp_required_for_non_scalar_nt, but for a PV built
        # directly from a plain Value (no nt=) -- pv.nt is never set for
        # this, so detection instead falls back to the Value's own
        # structure ID (see _struct_id_of_current).
        img_value = NTNDArray().wrap(numpy.zeros((4, 4)))
        table_value = NTTable(columns=[('A', 'd')]).wrap([{'A': 1.0}])

        self._check_rtyp_required_for(
            "HAND",
            SharedPV(initial=img_value), SharedPV(initial=table_value),
            SharedPV(initial=img_value), SharedPV(initial=table_value))

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

        P = RecordProvider("test")

        scalar_pv = _CountingCurrentPV(nt=NTScalar('d'), initial=1.234)
        P.add("EXAMPLE:FASTSCALAR", scalar_pv, valtype='d')
        assert scalar_pv.current_calls == 0

        ndarray_pv = _CountingCurrentPV(nt=NTNDArray(), initial=numpy.zeros((4, 4)))
        with pytest.raises(ValueError):
            P.add("EXAMPLE:FASTIMG", ndarray_pv, valtype='d')
        assert ndarray_pv.current_calls == 0

    def test_live_get(self):
        P = RecordProvider("test")
        P.add("EXAMPLE:PV", _pv(),
              valtype='d',
              dtyp_choices=["Soft Channel", "Raw Soft Channel"],
              fields={"DESC": "An example ai-like record", "SCAN": "1 second"})

        with Server(providers=[P], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV") == 1.234
                assert C.get("EXAMPLE:PV.NAME") == "EXAMPLE:PV"
                assert C.get("EXAMPLE:PV.RTYP") == "ai"
                assert C.get("EXAMPLE:PV.DESC") == "An example ai-like record"

                dtyp = C.get("EXAMPLE:PV.DTYP")
                assert dtyp.choice == "Soft Channel"

                scan = C.get("EXAMPLE:PV.SCAN")
                assert scan.choice == "1 second"

                stat = C.get("EXAMPLE:PV.STAT")
                assert stat.choice == "UDF"

                with pytest.raises(TimeoutError):
                    C.get("EXAMPLE:PV.NOSUCHFIELD", timeout=0.2)


class TestDynamicRecordFields:
    def test_live_get(self):
        base = {"EXAMPLE:PV3": SharedPV(nt=NTScalar('s'), initial="hello")}
        registry = {"EXAMPLE:PV3": {"valtype": 's'}}
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

        with Server(providers=[base, field_provider], isolate=True) as S:
            with Context('pva', conf=S.conf(), useenv=False) as C:
                assert C.get("EXAMPLE:PV3") == "hello"
                assert C.get("EXAMPLE:PV3.NAME") == "EXAMPLE:PV3"
                assert C.get("EXAMPLE:PV3.RTYP") == "stringin"

                with pytest.raises(TimeoutError):
                    C.get("EXAMPLE:PV3.NOSUCHFIELD", timeout=0.2)

                with pytest.raises(TimeoutError):
                    C.get("NOSUCHBASE.DESC", timeout=0.2)


def _async_pv(valtype='d', initial=1.234):
    return AsyncSharedPV(nt=NTScalar(valtype), initial=initial)


class TestRecordProviderAsyncio:
    async def test_live_get(self):
        # Field-value semantics (defaults, overrides, RTYP inference, etc)
        # are covered by TestRecordProvider.test_live_get; this only
        # confirms the same RecordProvider works against an
        # asyncio-flavored PV/Context.
        P = RecordProvider("test")
        P.add("EXAMPLE:PV", _async_pv(), valtype='d')

        with Server(providers=[P], isolate=True) as S:
            with AsyncContext('pva', conf=S.conf(), useenv=False) as C:
                assert (await C.get("EXAMPLE:PV")) == 1.234
                assert (await C.get("EXAMPLE:PV.NAME")) == "EXAMPLE:PV"
                assert (await C.get("EXAMPLE:PV.RTYP")) == "ai"

                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(C.get("EXAMPLE:PV.NOSUCHFIELD"), timeout=0.2)

    async def test_mixed_pv_flavors(self):
        # A single RecordProvider can mix thread- and asyncio-flavored base
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

        P = RecordProvider("test")
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
