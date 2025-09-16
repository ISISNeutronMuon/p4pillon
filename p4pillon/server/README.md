# Monkey-Patching p4p
p4pillon extends the p4p Handler class to allow open(), post(), and close() operations.To support this, changes to the equivalent functions in `p4p.server.raw.SharedPV` are required. This is handled by subclassing that class and then adding the needed functionality. This is straightforward.

It is possible to do this to the asyncio and thread `SharedPV` subclasses. Instead we use monkey-patching to replace the `p4p.server.raw.SharedPV` base class of those classes with `p4pillon.server.raw.SharedPV`. This means they inherit the required new Handler functionality.

`p4pillon.server.cli` uses similar monkey-patching techniques to change `p4p.server.cli` from using `SharedPV` to `SharedNT`.

Crudely, this is equivalent to forking the p4p code and modifying it. This method allows changes in p4p to be automatically tracked.