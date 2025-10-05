"""
Integration tests for expected behaviour of NTEnum PV types:
- [x] creation / modification (values, descriptions)
- [ ] alarm handling - match alarm
- [ ] alarm handling - invalid alarm
- [ ] calc records
- [ ] forward linking records
"""

import sys
from pathlib import Path

import pytest
import yaml
from helpers import put_different_value_enum, put_metadata

from tests.integration.thread.assertions import (
    assert_enum_value_changed,
    assert_enum_value_not_changed,
)

root_dir = Path(__file__).parents[2]

sys.path.append(str(root_dir))


with open(f"{root_dir}/integration/ntenum_config.yml") as f:
    ntenum_config = yaml.load(f, Loader=yaml.SafeLoader)
    f.close()


@pytest.mark.parametrize("pvname, pv_config", list(ntenum_config.items()))
def test_configs(pvname, enum_yaml_server, pv_config, ctx):
    # NOTE by using pytest and parameterize here we run the test individually
    # per PV in the config file, helping us to identify which PVs are causing
    # problems (this would be much more difficult if we were iterating over
    # a list from within the same test)
    pvname = enum_yaml_server.prefix + pvname

    assert pvname in enum_yaml_server.pvlist

    pv_state = ctx.get(pvname).raw.todict()

    assert pv_state.get("descriptor", "") == pv_config.get("description", "")

    assert pv_state.get("display") is None
    assert pv_state.get("control") is None
    assert pv_state.get("valueAlarm") is None


@pytest.mark.parametrize("pvname, pv_config", list(ntenum_config.items()))
def test_value_change(pvname, enum_yaml_server, pv_config, ctx):
    pvname = enum_yaml_server.prefix + pvname

    if not pv_config.get("read_only"):
        put_val, put_timestamp = put_different_value_enum(ctx, pvname)
        assert_enum_value_changed(pvname, put_val, put_timestamp, ctx)
    else:
        pytest.xfail(
            "Unsure on expected behaviour - expect the RemoteError or continue \
                     working with a warning logged to user"
        )
        assert_enum_value_not_changed(pvname, put_val, ctx)


@pytest.mark.parametrize("pvname, pv_config", list(ntenum_config.items()))
def test_field_change(pvname, enum_yaml_server, pv_config, ctx):
    pvname = enum_yaml_server.prefix + pvname

    current_description = ctx.get(pvname).raw.todict().get("descriptor")
    new_description = current_description + " modified"

    if not pv_config.get("read_only"):
        put_timestamp = put_metadata(ctx, pvname, "descriptor", new_description)

        pvstate = ctx.get(pvname)

        assert pvstate.raw.todict().get("descriptor") == new_description
        assert pvstate.timestamp >= put_timestamp

    else:
        pytest.xfail("Unsure on expected behaviour for read-only field changes")
