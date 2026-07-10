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
from p4p.server.asyncio import Handler  # noqa: E402, F401,
from p4p.server.asyncio import SharedPV as _AsyncioSharedPV  # noqa: E402


class SharedPV(_AsyncioSharedPV):
    # __init__ requires a running event loop on the calling thread (see
    # p4p.server.asyncio.SharedPV.__init__'s get_running_loop() call) --
    # flagged via this class attribute so callers needing to detect that
    # (e.g. p4pillon.server.records) can check the trait instead of naming
    # this class directly.  A real subclass rather than mutating
    # p4p.server.asyncio.SharedPV in place, same reasoning as
    # p4pillon.asyncio.sharednt.SharedNT: patching an attribute onto the
    # shared p4p class would leak into anyone else holding a reference to it.
    _requires_running_loop = True

# SharedPV.__init__ requires a running event loop on the calling thread (see
# p4p.server.asyncio.SharedPV.__init__'s get_running_loop() call) -- flagged
# here so callers needing to detect that (e.g. p4pillon.server.records) can
# check the trait instead of importing and naming this class directly.
SharedPV._requires_running_loop = True

#####
# Monkey patching the Handler is a simpler operation as it's a straight
# substitution with our new version.
# pylint: disable=ungrouped-imports
from p4pillon.server.raw import Handler as _Handler  # noqa: E402

Handler = _Handler  # noqa: F811
