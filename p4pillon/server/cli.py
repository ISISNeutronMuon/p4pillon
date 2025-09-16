"""
Monkey patch in a version that uses SharedNT instead of p4p.SharedPV
"""

import logging

from p4pillon.thread.sharednt import SharedNT


def _build_mailbox(*kargs, **kws):
    """Simple set up of a post handler using a SharedNT"""

    return SharedNT(*kargs, **kws)


# pylint: disable=wrong-import-position, wrong-import-order, unused-import
import p4p.server.cli  # noqa: E402

p4p.server.cli.buildMailbox = _build_mailbox  # noqa: F811

if __name__ == "__main__":
    args = p4p.server.cli.getargs()
    p4p.server.cli.set_debug(args.debug)
    logging.basicConfig(level=args.verbose)
    p4p.server.cli.main(args)
