# Quick Start
The example below requires only the installation of the p4p and p4p_ext Python packages. If using `uv` the command `uv run .\examples\quick_start\start.py` should start the server script.

## Example
The example below creates two PVs, `demo:pv:1` and `demo:pv:2`. It sets the first up with alarm and control limits. The second PV is identical to the first except it has a different initial value and is set as read only. This script may be found in the `examples/quick_start` directory and is called `start.py`.
```py
# /// script
# dependencies = [
#   "p4p",
#   "p4p_ext@git+https://github.com/ISISNeutronMuon/p4p_ext",
# ]
# ///

import asyncio

from p4p.server import Server, StaticProvider

from p4p_ext.asyncio.pvrecipe import PVScalarRecipe
from p4p_ext.definitions import PVTypes

loop = asyncio.new_event_loop()  # create the asyncio event loop

pvrecipe_double = PVScalarRecipe(PVTypes.DOUBLE, "An example double PV", 5.0)
pvrecipe_double.initial_value = 17.5
pvrecipe_double.set_alarm_limits(low_warning=2, high_alarm=9)
pvrecipe_double.set_control_limits(low=-10, high=100)

pv_double1 = pvrecipe_double.create_pv()

pvrecipe_double.initial_value = -15.5
pvrecipe_double.read_only = True

pv_double2 = pvrecipe_double.create_pv()

provider = StaticProvider()
provider.add("demo:pv:1", pv_double1)
provider.add("demo:pv:2", pv_double2)

try:
    server = Server((provider,))
    with server:
        done = asyncio.Event()

        loop.run_until_complete(done.wait())
finally:
    loop.close()
```
The initial state of the PVs may be examined using the commands:
```console
$ python -m p4p.client.cli get demo:pv:1
demo:pv:1 Thu Aug 14 22:20:28 2025 17.5
$ python -m p4p.client.cli get demo:pv:2
demo:pv:2 Thu Aug 14 22:20:28 2025 -10.0
```
We can attempt to set values and verify what effect that has:
```
$ python -m p4p.client.cli put demo:pv:1=101
demo:pv:1=101 ok
$ python -m p4p.client.cli get demo:pv:1
demo:pv:1 Sun Aug 17 14:04:08 2025 100.0
$ python -m p4p.client.cli put demo:pv:2=13
demo:pv:2=13 Error: This PV is read-only
$ python -m p4p.client.cli get demo:pv:2
demo:pv:2 Sun Aug 17 13:59:55 2025 -10.0
```

To examine 

## How p4p_ext extends p4p
The p4p library provides an Python interface to the pvAccess protocol and the structure of the Normative types. It does not implement the logic of the Normative Types. We illustrate what that means below.

### SharedPV
We here repeat the simple "mailbox" PV from the [p4p Server Example](https://epics-base.github.io/p4p/server.html#example) with some small changes to the SharedPV variable `pv`. We add in additional fields (`control` and `valueAlarm`) and set them with initial values. This script is available in the `examples/quick_start` directory as `mailbox_sharedpv.py`. Note that this example uses [threads](https://docs.python.org/3/library/threading.html), whereas the example in the previous section, above, uses [asyncio](https://docs.python.org/3/library/asyncio.html).

```py
from p4p.nt import NTScalar
from p4p.server import Server
from p4p.server.thread import SharedPV

pv = SharedPV(
    nt=NTScalar("d", control=True, valueAlarm=True),  # scalar double
    initial={
        "value": 2.2,  # setting initial value also open()'s
        "control.limitHigh": 10,
        "valueAlarm.active": True,
        "valueAlarm.highWarningLimit": 5,
        "valueAlarm.highWarningSeverity": 1,
        "valueAlarm.highAlarmLimit": 8,
        "valueAlarm.highAlarmSeverity": 2,
    },
)  


@pv.put
def handle(pv, op):
    pv.post(op.value())  # just store and update subscribers
    op.done()


Server.forever(
    providers=[
        {
            "demo:pv:name": pv,  # PV name only appears here
        }
    ]
)  # runs until KeyboardInterrupt
```

Run the script above and, leaving it running, examine the PV `demo:pv:name` that it creates. You can do this using the tools built into p4p. 
```
python -m p4p.client.cli --raw get demo:pv:name
```
Note that we use the `--raw` option to see the full structure of the PV rather than a summary.

You should see output like this:
```console
$ python -m p4p.client.cli --raw get demo:pv:name

demo:pv:name struct "epics:nt/NTScalar:1.0" {
    double value = 2.2
    struct "alarm_t" {
        int32_t severity = 0
        int32_t status = 0
        string message = ""
    } alarm
    struct "time_t" {
        int64_t secondsPastEpoch = 0
        int32_t nanoseconds = 0
        int32_t userTag = 0
    } timeStamp
    struct {
        double limitLow = 0
        double limitHigh = 10
        double minStep = 0
    } control
    struct {
        bool active = true
        double lowAlarmLimit = 0
        double lowWarningLimit = 0
        double highWarningLimit = 5
        double highAlarmLimit = 8
        int32_t lowAlarmSeverity = 0
        int32_t lowWarningSeverity = 0
        int32_t highWarningSeverity = 1
        int32_t highAlarmSeverity = 2
        double hysteresis = 0
    } valueAlarm
}
```
This shows that the PV has been constructed as expected and is reporting the correct value and other settings. However, if we drop off the `--raw` option in the get command and examine the output an issue becomes more obvious. Note that the timestamp is incorrect.
```console
$ python -m p4p.client.cli get demo:pv:name
demo:pv:name Thu Jan  1 00:00:00 1970 2.2
```
Let's now try putting a value to the PV and then checking the result:
```console
$ python -m p4p.client.cli put demo:pv:name=6.6
demo:pv:name=6.6 ok
$ python -m p4p.client.cli get demo:pv:name
demo:pv:name Thu Jan  1 00:00:00 1970 6.6
```
We can observe that the value has correctly changed, but that the timestamp remains incorrect. Let's take another more detailed look at the full structure:
```console
$ python -m p4p.client.cli --raw get demo:pv:name

demo:pv:name struct "epics:nt/NTScalar:1.0" {
    double value = 6.6
    struct "alarm_t" {
        int32_t severity = 0
        int32_t status = 0
        string message = ""
    } alarm
    struct "time_t" {
        int64_t secondsPastEpoch = 0
        int32_t nanoseconds = 0
        int32_t userTag = 0
    } timeStamp
    struct {
        double limitLow = 0
        double limitHigh = 10
        double minStep = 0
    } control
    struct {
        bool active = true
        double lowAlarmLimit = 0
        double lowWarningLimit = 0
        double highWarningLimit = 5
        double highAlarmLimit = 8
        int32_t lowAlarmSeverity = 0
        int32_t lowWarningSeverity = 0
        int32_t highWarningSeverity = 1
        int32_t highAlarmSeverity = 2
        double hysteresis = 0
    } valueAlarm
}
```
Examine the PV's `alarm` field:
```
    double value = 6.6
    struct "alarm_t" {
        int32_t severity = 0
        int32_t status = 0
        string message = ""
    } alarm
```
The value of 6.6 is over the `valueAlarm.highWarningLimit`of 5 but the alarm severity, status, and message do not reflect this. 

Similarly if we set the value of the PV to 12.7...
```console
$ python -m p4p.client.cli put demo:pv:name=12.7
demo:pv:name=12.7 ok
$ python -m p4p.client.cli --raw get demo:pv:name

demo:pv:name struct "epics:nt/NTScalar:1.0" {
    double value = 12.7
    struct "alarm_t" {
        int32_t severity = 0
        int32_t status = 0
        string message = ""
    } alarm
    struct "time_t" {
        int64_t secondsPastEpoch = 0
        int32_t nanoseconds = 0
        int32_t userTag = 0
    } timeStamp
    [...]
}
```
... we truncate some fields (not showing `control` and `valueAlarm` as they are unchanged).

The value has been set to 12.7, despite the `control.limitHigh` being 10 which should not permit values above 10.0. Similarly the alarm severity, status, and message, and the timestamp remain unchanged. 

The PV's Normative Type fields are present, but the logic implied by their presence is not implemented.

### SharedNT
Let's try implementing the same simple "mailbox" server with p4p_ext. This file is available in the `examples/quick_start` directory and is called `mailbox_sharednt.py`.
```py
from p4p.nt import NTScalar
from p4p.server import Server

from p4p_ext.thread.sharednt import SharedNT

pv = SharedNT(
    nt=NTScalar("d", control=True, valueAlarm=True),  # scalar double
    initial={
        "value": 2.2,  # setting initial value also open()'s
        "control.limitHigh": 10,
        "valueAlarm.active": True,
        "valueAlarm.highWarningLimit": 5,
        "valueAlarm.highWarningSeverity": 1,
        "valueAlarm.highAlarmLimit": 8,
        "valueAlarm.highAlarmSeverity": 2,
    },
)  # setting initial value also open()'s

Server.forever(
    providers=[
        {
            "demo:pv:name": pv,  # PV name only appears here
        }
    ]
)  # runs until KeyboardInterrupt
```
Note that we have replaced the `SharedPV` with a `SharedNT` from p4p_ext, and that we have removed the `handle` function with the `@pv.put` decorator.

Let's examine the results of the same commands as above:
```console
$ python -m p4p.client.cli --raw get demo:pv:name

demo:pv:name struct "epics:nt/NTScalar:1.0" {
    double value = 2.2
    struct "alarm_t" {
        int32_t severity = 0
        int32_t status = 0
        string message = ""
    } alarm
    struct "time_t" {
        int64_t secondsPastEpoch = 1755203073
        int32_t nanoseconds = 363457202
        int32_t userTag = 0
    } timeStamp
    struct {
        double limitLow = 0
        double limitHigh = 10
        double minStep = 0
    } control
    struct {
        bool active = true
        double lowAlarmLimit = 0
        double lowWarningLimit = 0
        double highWarningLimit = 5
        double highAlarmLimit = 8
        int32_t lowAlarmSeverity = 0
        int32_t lowWarningSeverity = 0
        int32_t highWarningSeverity = 1
        int32_t highAlarmSeverity = 2
        double hysteresis = 0
    } valueAlarm
}

$ python -m p4p.client.cli get demo:pv:name
demo:pv:name Thu Aug 14 21:24:33 2025 2.2
```
The timestamp is already being set correctly.

Let's try the other commands...
```console
$ python -m p4p.client.cli put demo:pv:name=6.6
demo:pv:name=6.6 ok
$ python -m p4p.client.cli get demo:pv:name
demo:pv:name Thu Aug 14 21:30:29 2025 6.6
$ python -m p4p.client.cli --raw get demo:pv:name
demo:pv:name struct "epics:nt/NTScalar:1.0" {
    double value = 6.6
    struct "alarm_t" {
        int32_t severity = 1
        int32_t status = 0
        string message = "highWarning"
    } alarm
    struct "time_t" {
        int64_t secondsPastEpoch = 1755203429
        int32_t nanoseconds = 724358797
        int32_t userTag = 0
    } timeStamp
    [...]
}
```
... again truncating fields which have not changed.

When you `put` the value the timestamp on the PV should reflect that time. Notice that the alarm severity and message have been set. 

```console
$ python -m p4p.client.cli put demo:pv:name=12.7
demo:pv:name=12.7 ok
$ python -m p4p.client.cli get demo:pv:name
demo:pv:name Thu Aug 14 21:31:40 2025 10.0
$ python -m p4p.client.cli --raw get demo:pv:name
demo:pv:name struct "epics:nt/NTScalar:1.0" {
    double value = 10
    struct "alarm_t" {
        int32_t severity = 2
        int32_t status = 0
        string message = "highAlarm"
    } alarm
    struct "time_t" {
        int64_t secondsPastEpoch = 1755203500
        int32_t nanoseconds = 87517261
        int32_t userTag = 0
    } timeStamp
    [...]
}
```
The value has been limited to 10, the alarm severity has been updated to a value of 2 (i.e. MAJOR), and the timestamp has been updated appropriately.