"""Driver for the Tektronix AFG1022 (SCPI over VISA) plus a simulated twin for testing.

What the AFG1000 programmer manual allows (and what the probe on a real unit confirmed):
  * Burst mode exists on CH1 only.
  * Burst trigger source: SOURce1:BURSt:SOURce {TIMer|MANual|EXTernal}.
  * There is NO SCPI command for the internal trigger interval (front panel only).

So the PRF is produced by the generator itself with a small loop-back:
  * CH1 = sine carrier, triggered burst of N cycles, trigger source EXTernal.
  * CH2 = continuous 0-3.3 V square wave at the PRF.
  * A BNC cable runs from the CH2 output to the rear "Ext Trig/Burst/FSK In" connector.
Each rising edge of the CH2 square wave triggers one CH1 burst.
"""
from __future__ import annotations

import time
from typing import Callable

from .protocol import Protocol

CLOCK_HIGH_V = 3.3  # CH2 trigger square wave: 0 .. 3.3 V (input must stay below 5 V)


class AFGError(RuntimeError):
    pass


class AFG1022:
    name = "Tektronix AFG1022"

    def __init__(self, resource: str):
        self.resource = resource
        self._inst = None
        self.on_command: Callable[[str], None] | None = None  # called for every command sent
        self._failures: list[str] = []

    # ---- connection ---------------------------------------------------
    @staticmethod
    def list_resources() -> list[str]:
        """USB-TMC instruments first (fast, no network scan); full VISA scan as fallback."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                from pyvisa_py.usb import USBInstrSession

                found = list(USBInstrSession.list_resources())
                if found:
                    return found
            except Exception:
                pass
            try:
                import pyvisa

                return list(pyvisa.ResourceManager().list_resources())
            except Exception:
                return []

    def connect(self) -> None:
        import pyvisa

        rm = pyvisa.ResourceManager()
        self._inst = rm.open_resource(self.resource)
        self._inst.timeout = 5000
        self._inst.write_termination = "\n"
        self._inst.read_termination = "\n"

    def close(self) -> None:
        if self._inst is not None:
            try:
                self._inst.close()
            finally:
                self._inst = None

    # ---- low level ----------------------------------------------------
    def _write(self, cmd: str) -> None:
        self._inst.write(cmd)

    def _query(self, cmd: str) -> str:
        try:
            return self._inst.query(cmd).strip()
        except Exception as exc:  # noqa: BLE001
            raise AFGError(f"No valid reply to '{cmd}' ({exc})") from exc

    def _send(self, cmd: str) -> None:
        if self.on_command:
            self.on_command(cmd)
        self._write(cmd)

    def _recover(self) -> None:
        """Try to get a confused USBTMC link talking again after a timeout."""
        if self._inst is not None:
            try:
                self._inst.clear()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.3)

    def _error_reply(self) -> str:
        """Read SYSTem:ERRor? once; give the instrument a moment, retry once after recovery."""
        time.sleep(0.05)
        try:
            return self._query("SYSTem:ERRor?")
        except AFGError:
            self._recover()
            return self._query("SYSTem:ERRor?")

    def _pop_errors(self) -> str | None:
        errs = []
        for _ in range(5):
            resp = self._error_reply()
            try:
                code = int(resp.split(",")[0])
            except ValueError:
                code = -1
            if code == 0:
                break
            errs.append(resp)
        return " | ".join(errs) if errs else None

    def _send_checked(self, cmd: str, optional: bool = False) -> None:
        self._send(cmd)
        try:
            err = self._pop_errors()
        except AFGError as exc:
            raise AFGError(f"After sending '{cmd}': {exc}") from exc
        if err is None:
            return
        if optional:
            if self.on_command:
                self.on_command(f"   (ignored, optional command rejected: {err})")
            return
        self._failures.append(f"{cmd}   ->   {err}")

    # ---- high level ---------------------------------------------------
    def idn(self) -> str:
        return self._query("*IDN?")

    def configure(self, p: Protocol) -> None:
        """Program CH1 (carrier burst) and CH2 (PRF clock). Leaves both outputs OFF.

        The error queue is read after every command, so a rejected command is
        reported by name instead of as an anonymous "Syntax error".
        """
        self._failures = []
        self._send("*CLS")
        self.output_off()
        steps = [
            # CH1: carrier, N-cycle burst, started by an external trigger edge
            f"OUTPut1:IMPedance {'50' if p.load == '50' else 'INFinity'}",
            "SOURce1:FUNCtion:SHAPe SINusoid",
            f"SOURce1:FREQuency:FIXed {p.freq_hz:.9g}",
            f"SOURce1:VOLTage:LEVel:IMMediate:AMPLitude {p.amplitude_vpp:.6g}",
            "SOURce1:VOLTage:LEVel:IMMediate:OFFSet 0",
            "SOURce1:BURSt:MODE TRIGgered",
            f"SOURce1:BURSt:NCYCles {p.cycles_per_burst}",
            "SOURce1:BURSt:SOURce EXTernal",
            "SOURce1:BURSt:STATe ON",
            # CH2: PRF clock, cabled to the rear Ext Trig input
            "OUTPut2:IMPedance INFinity",
            "SOURce2:FUNCtion:SHAPe SQUare",
            f"SOURce2:FREQuency:FIXed {p.prf_hz:.9g}",
            f"SOURce2:VOLTage:LEVel:IMMediate:AMPLitude {CLOCK_HIGH_V:g}",
            f"SOURce2:VOLTage:LEVel:IMMediate:OFFSet {CLOCK_HIGH_V / 2:g}",
        ]
        for cmd in steps:
            self._send_checked(cmd)
        if self._failures:
            raise AFGError("Commands rejected by the instrument:\n" + "\n".join(self._failures))

    def readback(self) -> dict[str, str]:
        """Ask the instrument what it holds. A query it does not answer gives 'n/a'."""
        queries = [
            ("ch1_freq_hz", "SOURce1:FREQuency:FIXed?"),
            ("ch1_amplitude", "SOURce1:VOLTage:LEVel:IMMediate:AMPLitude?"),
            ("ch1_ncycles", "SOURce1:BURSt:NCYCles?"),
            ("ch1_burst_source", "SOURce1:BURSt:SOURce?"),
            ("ch2_prf_hz", "SOURce2:FREQuency:FIXed?"),
        ]
        out: dict[str, str] = {}
        old_timeout = self._inst.timeout if self._inst is not None else None
        if self._inst is not None:
            self._inst.timeout = 1500  # do not wait 5 s per unanswered query
        try:
            for key, q in queries:
                try:
                    if self.on_command:
                        self.on_command(q)
                    out[key] = self._query(q)
                except AFGError:
                    out[key] = "n/a"
                    if self.on_command:
                        self.on_command("   (no answer to that query)")
                    self._recover()
        finally:
            if self._inst is not None:
                self._inst.timeout = old_timeout
        return out

    def output_on(self) -> None:
        """CH1 first (it waits for triggers), then CH2 starts the PRF clock."""
        self._send("OUTPut1:STATe ON")
        self._send("OUTPut2:STATe ON")

    def output_off(self) -> None:
        """Stop the clock first, then the carrier."""
        self._send("OUTPut2:STATe OFF")
        self._send("OUTPut1:STATe OFF")


class SimulatedAFG(AFG1022):
    """Same interface, no hardware. Remembers commands so the GUI can be tried anywhere."""

    name = "Simulated AFG"

    def __init__(self):
        super().__init__("SIMULATED")
        self.state: dict[str, str] = {}
        self.commands: list[str] = []

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def _write(self, cmd: str) -> None:
        self.commands.append(cmd)
        head, _, value = cmd.partition(" ")
        self.state[head.upper()] = value

    def _query(self, cmd: str) -> str:
        if cmd == "*IDN?":
            return "SIMULATED,AFG1022,0,0.0"
        if cmd.startswith("SYSTem:ERRor"):
            return '0,"No error"'
        return self.state.get(cmd.rstrip("?").upper(), "?")
