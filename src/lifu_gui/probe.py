"""Probe the AFG1022 command by command and write a report.

Run:  uv run python -m lifu_gui.probe            (first USB instrument found)
      uv run python -m lifu_gui.probe <VISA resource string>

It sends the commands the GUI uses, one at a time, and reads the error queue after each.
It NEVER switches an output on. Paste the printed report back if something misbehaves.
"""
from __future__ import annotations

import sys
import time
import warnings
from datetime import datetime

COMMANDS = [
    "*CLS",
    "OUTPut1:STATe OFF",
    "OUTPut2:STATe OFF",
    "OUTPut1:IMPedance 50",
    "SOURce1:FUNCtion:SHAPe SINusoid",
    "SOURce1:FREQuency:FIXed 500000",
    "SOURce1:VOLTage:LEVel:IMMediate:AMPLitude 0.1",
    "SOURce1:VOLTage:LEVel:IMMediate:OFFSet 0",
    "SOURce1:BURSt:MODE TRIGgered",
    "SOURce1:BURSt:NCYCles 250",
    "SOURce1:BURSt:SOURce EXTernal",
    "SOURce1:BURSt:STATe ON",
    "OUTPut2:IMPedance INFinity",
    "SOURce2:FUNCtion:SHAPe SQUare",
    "SOURce2:FREQuency:FIXed 1000",
    "SOURce2:VOLTage:LEVel:IMMediate:AMPLitude 3.3",
    "SOURce2:VOLTage:LEVel:IMMediate:OFFSet 1.65",
]

QUERIES = [
    "OUTPut1:IMPedance?",
    "SOURce1:FREQuency:FIXed?",
    "SOURce1:VOLTage:LEVel:IMMediate:AMPLitude?",
    "SOURce1:BURSt:MODE?",
    "SOURce1:BURSt:NCYCles?",
    "SOURce1:BURSt:SOURce?",
    "SOURce1:BURSt:STATe?",
    "OUTPut2:IMPedance?",
    "SOURce2:FUNCtion:SHAPe?",
    "SOURce2:FREQuency:FIXed?",
    "SOURce2:VOLTage:LEVel:IMMediate:AMPLitude?",
    "SOURce2:VOLTage:LEVel:IMMediate:OFFSet?",
    "OUTPut1:STATe?",
    "OUTPut2:STATe?",
]


def main() -> int:
    warnings.simplefilter("ignore")
    import pyvisa

    from .afg1022 import AFG1022

    lines: list[str] = []

    def out(msg: str = "") -> None:
        print(msg, flush=True)
        lines.append(msg)

    resource = sys.argv[1] if len(sys.argv) > 1 else None
    if resource is None:
        found = AFG1022.list_resources()
        usb = [r for r in found if r.upper().startswith("USB")]
        if not found:
            out("No VISA resources found (is libusb installed and the generator on?).")
            return 1
        resource = (usb or found)[0]

    out(f"AFG1022 probe, {datetime.now():%Y-%m-%d %H:%M:%S}")
    out(f"Resource: {resource}")
    inst = pyvisa.ResourceManager().open_resource(resource)
    inst.timeout = 3000
    inst.write_termination = "\n"
    inst.read_termination = "\n"

    def recover() -> None:
        try:
            inst.clear()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)

    def ask(cmd: str) -> tuple[bool, str]:
        try:
            return True, inst.query(cmd).strip()
        except Exception as exc:  # noqa: BLE001
            recover()
            return False, f"{type(exc).__name__}: {exc}"

    ok, reply = ask("*IDN?")
    out(f"*IDN?  ->  {reply}")

    out("\n--- commands (each followed by SYSTem:ERRor?) ---")
    for cmd in COMMANDS:
        inst.write(cmd)
        time.sleep(0.3)
        ok, err = ask("SYSTem:ERRor?")
        if not ok:
            status = f"NO REPLY to SYSTem:ERRor?  ({err})"
        elif err.startswith("0,") or err.startswith("+0,"):
            status = "ok"
        else:
            status = f"REJECTED  {err}"
            ask("SYSTem:ERRor?")  # drain
        out(f"{cmd:<55} {status}")

    out("\n--- queries ---")
    for q in QUERIES:
        ok, reply = ask(q)
        out(f"{q:<55} {'-> ' + reply if ok else 'NO REPLY (' + reply + ')'}")
        ask("SYSTem:ERRor?")  # drain any error a bad query left behind

    inst.write("OUTPut2:STATe OFF")
    inst.write("OUTPut1:STATe OFF")
    inst.close()
    with open("probe_report.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    out("\nReport saved to probe_report.txt (outputs were never switched on).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
