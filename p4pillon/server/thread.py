"""
Monkey patch in required changes to Handlers and SharedPVs
"""

####
# First override the base class of p4pillon.server.thread.SharedPV with
# p4pillon.server.raw.SharedPV. This requires us to perform the imports
# in a very specific order, which means overriding Linter checks
import p4p.server.raw

from p4pillon.server.raw import SharedPV as _SharedPV

p4p.server.raw.SharedPV = _SharedPV

# pylint: disable=unused-import, wrong-import-order, wrong-import-position
from p4p.server.thread import Handler, SharedPV  # noqa: E402, F401,

#####
# Monkey patching the Handler is a simpler operation as it's a straight
# substitution with our new version.
# pylint: disable=ungrouped-imports
from p4pillon.server.raw import Handler as _Handler  # noqa: E402

Handler = _Handler  # noqa: F811
