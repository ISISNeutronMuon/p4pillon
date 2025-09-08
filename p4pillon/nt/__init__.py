"""
Monkey patch in required changes to NTEnum
"""

from p4p.nt import *  # type: ignore # noqa: F403
from p4p.nt import NTBase, NTEnum  # noqa: F401

from p4pillon.nt.enum import NTEnum as _NTEnum

NTEnum = _NTEnum  # noqa: F811
