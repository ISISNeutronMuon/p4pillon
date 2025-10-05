import pytest

from p4pillon.nt import NTEnum, NTNDArray, NTScalar, NTTable
from p4pillon.nt.identify import NTType, id_nttype


@pytest.mark.parametrize(
    "input_val, expected_result",
    [
        (NTScalar("?"), NTType.NTSCALAR),
        (NTScalar("d"), NTType.NTSCALAR),
        (NTScalar("ad"), NTType.NTSCALARARRAY),
        (NTEnum(), NTType.NTENUM),
        (NTNDArray(), NTType.NTNDARRAY),
        (NTTable(), NTType.NTTABLE),
    ],
)
def test_identify(input_val, expected_result):
    """
    id_nttype() can work with NTBase, Value, and Type so we need to test each
    """

    assert id_nttype(input_val) == expected_result
    assert id_nttype(input_val.type) == expected_result
