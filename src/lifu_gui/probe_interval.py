"""Hunt for a SCPI command that sets the burst trigger interval (PRI) on the AFG1022.

Run:  uv run python -m lifu_gui.probe_interval

Sets burst mode with the internal timer as trigger source, then tries many possible command
names with a recognisable value (0.25 s). Reports which ones the generator accepts and what
the matching query returns. It NEVER switches an output on.
"""
from __future__ import annotations

import sys
import time
import warnings
from datetime import datetime

SETUP = [
    "*CLS",
    "OUTPut1:STATe OFF",
    "OUTPut2:STATe OFF",
    "SOURce1:FUNCtion:SHAPe SINusoid",
    "SOURce1:FREQuency:FIXed 500000",
    "SOURce1:BURSt:MODE TRIGgered",
    "SOURce1:BURSt:NCYCles 250",
    "SOURce1:BURSt:SOURce TIMer",
    "SOURce1:BURSt:STATe ON",
]

HEADS = [
    # under the burst node
    "SOURce1:BURSt:INTerval",
    "SOURce1:BURSt:TINTerval",
    "SOURce1:BURSt:INTernal:INTerval",
    "SOURce1:BURSt:INTernal:PERiod",
    "SOURce1:BURSt:INTernal:RATE",
    "SOURce1:BURSt:INTernal:TIMer",
    "SOURce1:BURSt:PERiod",
    "SOURce1:BURSt:TIMer",
    "SOURce1:BURSt:RATE",
    "SOURce1:BURSt:DELay",
    "SOURce1:BURSt:TDELay",
    "SOURce1:BURSt:TRIGger:INTerval",
    "SOURce1:BURSt:TRIGger:PERiod",
    "SOURce1:BURSt:TRIGger:TIMer",
    "SOURce1:BURSt:TIMer:PERiod",
    "SOURce1:BURSt:TIMer:INTerval",
    # under the trigger node
    "TRIGger:INTerval",
    "TRIGger:PERiod",
    "TRIGger:TIMer",
    "TRIGger:RATE",
    "TRIGger:INTernal:INTerval",
    "TRIGger:INTernal:PERiod",
    "TRIGger:INTernal:TIMer",
    "TRIGger:SEQuence:INTerval",
    "TRIGger:SEQuence:PERiod",
    "TRIGger:SEQuence:TIMer",
    "TRIGger:SEQuence:TINTerval",
    "TRIGger:SEQuence:RATE",
    "TRIGger:SEQuence:DELay",
    "TRIGger:SEQuence:INTernal:INTerval",
    "TRIGger:SEQuence:INTernal:PERiod",
    "SOURce1:TRIGger:INTerval",
    "SOURce1:TRIGger:TIMer",
    "SOURce1:TRIGger:PERiod",
    # others
    "BURSt:INTernal:PERiod",
    "BURSt:INTerval",
    "BURSt:PERiod",
    "SOURce1:INTerval",
    "SOURce1:PERiod",
]
VALUES = ["0.25", "250ms"]


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
            out("No VISA resources found.")
            return 1
        resource = (usb or found)[0]

    inst = pyvisa.ResourceManager().open_resource(resource)
    inst.timeout = 2000
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
            return False, f"{type(exc).__name__}"

    def accepted(cmd: str) -> bool:
        inst.write(cmd)
        time.sleep(0.25)
        ok, err = ask("SYSTem:ERRor?")
        if ok and (err.startswith("0,") or err.startswith("+0,")):
            return True
        if ok:
            ask("SYSTem:ERRor?")  # drain
        return False

    out(f"AFG1022 interval hunt, {datetime.now():%Y-%m-%d %H:%M:%S}")
    ok, idn = ask("*IDN?")
    out(f"*IDN? -> {idn}\n")

    out("--- setup ---")
    for cmd in SETUP:
        out(f"{cmd:<45} {'ok' if accepted(cmd) else 'REJECTED'}")
    ok, reply = ask("SOURce1:BURSt:SOURce?")
    out(f"SOURce1:BURSt:SOURce?  ->  {reply}")

    out("\n--- candidates (value 0.25 s) ---")
    hits = []
    for head in HEADS:
        for value in VALUES:
            cmd = f"{head} {value}"
            if accepted(cmd):
                ok, reply = ask(head + "?")
                out(f"ACCEPTED  {cmd:<50} query -> {reply if ok else 'no reply'}")
                hits.append(cmd)
                break
        else:
            out(f"rejected  {head}")

    out(f"\nAccepted commands: {hits if hits else 'none'}")
    inst.write("OUTPut1:STATe OFF")
    inst.write("OUTPut2:STATe OFF")
    inst.close()
    with open("probe_interval_report.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    out("\nSaved probe_interval_report.txt (outputs were never switched on).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
