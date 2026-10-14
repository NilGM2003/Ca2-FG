"""Tkinter GUI: pick a sonication protocol, configure the AFG1022 and run it."""
from __future__ import annotations

import json
import threading
import time
import tkinter as tk
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from .afg1022 import AFG1022, SimulatedAFG
from .protocol import Limits, Protocol

DATA_DIR = Path("data")
PRESETS_FILE = DATA_DIR / "presets.json"
LIMITS_FILE = DATA_DIR / "limits.json"
LOG_FILE = DATA_DIR / "sonication_log.jsonl"

# key, label, unit, default
FIELDS = [
    ("freq_khz", "Carrier frequency", "kHz", "500"),
    ("amplitude_vpp", "Amplitude", "Vpp", "0.1"),
    ("prf_hz", "PRF", "Hz", "1000"),
    ("duty_cycle_pct", "Duty cycle", "%", "50"),
    ("duration_s", "Sonication duration", "s", "1"),
]


class ColorButton(tk.Label):
    """Coloured button built from a Label (macOS Tk ignores colours on real buttons)."""

    def __init__(self, master, text, color, command, **kw):
        super().__init__(
            master, text=text, bg=color, fg="white", padx=14, pady=8,
            font=("TkDefaultFont", 12, "bold"), cursor="hand2", **kw,
        )
        self._color = color
        self._command = command
        self._enabled = True
        self.bind("<Button-1>", self._click)

    def _click(self, _event) -> None:
        if self._enabled:
            self._command()

    def configure(self, **kw):
        state = kw.pop("state", None)
        if state is not None:
            self._enabled = state != "disabled"
            super().configure(bg=self._color if self._enabled else "#9e9e9e")
        if kw:
            super().configure(**kw)

    config = configure


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LIFU sonication control")
        DATA_DIR.mkdir(exist_ok=True)
        self.limits = Limits.load(LIMITS_FILE)
        self.driver: AFG1022 | None = None
        self.running = False
        self.current: Protocol | None = None
        self._end_id = None
        self._tick_id = None
        self._t0 = 0.0
        self._started_at = ""
        self._readback: dict = {}
        self._locked: list[tuple[ttk.Widget, str]] = []

        self._scanning = False
        self._scan_result: list[str] | None = None

        self._build()
        self._refresh_presets()
        self._update_derived()
        self._fit_window()
        self.after(300, self._refresh_resources)  # after the window is on screen
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _e: self._stop("stopped by user"))

    def _fit_window(self) -> None:
        """Size the window to its content explicitly (macOS Tk can leave it tiny otherwise)."""
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.minsize(w, h)
        self.geometry(f"{w}x{h}+80+60")
        self.lift()
        self.focus_force()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # Instrument
        conn = ttk.LabelFrame(self, text="Instrument")
        conn.grid(row=0, column=0, sticky="ew", **pad)
        self.res_var = tk.StringVar()
        self.res_combo = ttk.Combobox(conn, textvariable=self.res_var, width=46)
        self.res_combo.grid(row=0, column=0, columnspan=3, sticky="ew", padx=4, pady=2)
        ttk.Button(conn, text="Refresh", command=self._refresh_resources).grid(row=0, column=3, padx=4)
        self.sim_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(conn, text="Simulation (no instrument)", variable=self.sim_var).grid(
            row=1, column=0, sticky="w", padx=4
        )
        self.conn_btn = ttk.Button(conn, text="Connect", command=self._toggle_connection)
        self.conn_btn.grid(row=1, column=3, padx=4, pady=2)
        self.conn_status = tk.StringVar(value="Not connected")
        ttk.Label(conn, textvariable=self.conn_status).grid(row=2, column=0, columnspan=4, sticky="w", padx=4)

        # Protocol parameters
        par = ttk.LabelFrame(self, text="Protocol")
        par.grid(row=1, column=0, sticky="ew", **pad)
        self.vars: dict[str, tk.StringVar] = {}
        for i, (key, label, unit, default) in enumerate(FIELDS):
            ttk.Label(par, text=label).grid(row=i, column=0, sticky="w", padx=4, pady=2)
            var = tk.StringVar(value=default)
            var.trace_add("write", self._update_derived)
            ent = ttk.Entry(par, textvariable=var, width=12)
            ent.grid(row=i, column=1, padx=4)
            ttk.Label(par, text=unit).grid(row=i, column=2, sticky="w")
            self.vars[key] = var
            self._locked.append((ent, "normal"))
        n = len(FIELDS)

        ttk.Label(par, text="CH1 load setting").grid(row=n, column=0, sticky="w", padx=4, pady=2)
        self.load_var = tk.StringVar(value="50")
        load_combo = ttk.Combobox(par, textvariable=self.load_var, values=("50", "HighZ"), width=9, state="readonly")
        load_combo.grid(row=n, column=1, padx=4)
        ttk.Label(par, text="Ω / High-Z").grid(row=n, column=2, sticky="w")
        self._locked.append((load_combo, "readonly"))

        ttk.Label(
            par,
            text="Wiring: CH1 -> transducer chain.  CH2 -> rear 'Ext Trig/Burst/FSK In' (BNC);\n"
                 "CH2 carries the PRF clock that triggers every burst.",
            foreground="#555",
        ).grid(row=n + 1, column=0, columnspan=3, sticky="w", padx=4, pady=(6, 2))

        ttk.Label(par, text=self.limits.summary(), foreground="#555", wraplength=380).grid(
            row=n + 2, column=0, columnspan=3, sticky="w", padx=4, pady=(2, 2)
        )

        # Presets
        pre = ttk.LabelFrame(self, text="Presets")
        pre.grid(row=2, column=0, sticky="ew", **pad)
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(pre, textvariable=self.preset_var, width=28, state="readonly")
        self.preset_combo.grid(row=0, column=0, padx=4, pady=2)
        self.preset_combo.bind("<<ComboboxSelected>>", self._apply_preset)
        b1 = ttk.Button(pre, text="Save as…", command=self._save_preset)
        b2 = ttk.Button(pre, text="Delete", command=self._delete_preset)
        b1.grid(row=0, column=1, padx=4)
        b2.grid(row=0, column=2, padx=4)
        self._locked += [(self.preset_combo, "readonly"), (b1, "normal"), (b2, "normal")]

        # Derived values
        der = ttk.LabelFrame(self, text="What the generator will do")
        der.grid(row=3, column=0, sticky="ew", **pad)
        self.derived_var = tk.StringVar()
        ttk.Label(der, textvariable=self.derived_var, justify="left").grid(row=0, column=0, sticky="w", padx=4, pady=2)

        # Run controls
        run = ttk.Frame(self)
        run.grid(row=4, column=0, sticky="ew", **pad)
        self.start_btn = ColorButton(run, "START SONICATION", "#2e7d32", self._start, width=20)
        self.start_btn.grid(row=0, column=0, padx=4, pady=4)
        self.stop_btn = ColorButton(run, "STOP (Esc)", "#c62828", lambda: self._stop("stopped by user"), width=14)
        self.stop_btn.grid(row=0, column=1, padx=4, pady=4)
        self.stop_btn.configure(state="disabled")
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(run, variable=self.progress_var, maximum=100, length=360).grid(
            row=1, column=0, columnspan=2, padx=4, sticky="ew"
        )
        self.time_var = tk.StringVar(value="idle")
        ttk.Label(run, textvariable=self.time_var).grid(row=2, column=0, columnspan=2, sticky="w", padx=4)

        # Log
        logf = ttk.LabelFrame(self, text="Log")
        logf.grid(row=5, column=0, sticky="ew", **pad)
        self.log = ScrolledText(logf, height=9, width=64, state="disabled")
        self.log.grid(row=0, column=0, padx=4, pady=4)

    def _set_locked(self, locked: bool) -> None:
        for widget, normal in self._locked:
            widget.configure(state="disabled" if locked else normal)

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {msg}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------ protocol
    def _read_protocol(self, name: str = "custom") -> Protocol:
        try:
            v = {k: float(var.get().replace(",", ".")) for k, var in self.vars.items()}
        except ValueError as exc:
            raise ValueError("All parameters must be numbers.") from exc
        return Protocol(
            name=name,
            freq_hz=v["freq_khz"] * 1e3,
            amplitude_vpp=v["amplitude_vpp"],
            prf_hz=v["prf_hz"],
            duty_cycle_pct=v["duty_cycle_pct"],
            duration_s=v["duration_s"],
            load=self.load_var.get(),
            channels=[1],
        )

    def _update_derived(self, *_args) -> None:
        try:
            p = self._read_protocol()
            text = (
                f"Cycles per burst:        {p.cycles_per_burst}\n"
                f"Actual duty cycle:       {p.actual_duty_cycle_pct:.3g} %\n"
                f"Burst length:            {p.burst_length_s * 1e6:.4g} µs\n"
                f"Pulse repetition period: {p.prp_s * 1e3:.4g} ms\n"
                f"Number of bursts:        {p.n_bursts}\n"
                f"PRF clock on CH2:        {p.prf_hz:g} Hz square wave"
            )
        except (ValueError, ZeroDivisionError):
            text = "—"
        self.derived_var.set(text)

    # ------------------------------------------------------------- presets
    def _load_presets(self) -> dict:
        if PRESETS_FILE.exists():
            return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
        return {}

    def _refresh_presets(self) -> None:
        self.preset_combo["values"] = sorted(self._load_presets())

    def _apply_preset(self, _event=None) -> None:
        d = self._load_presets().get(self.preset_var.get())
        if not d:
            return
        p = Protocol.from_dict(d)
        self.vars["freq_khz"].set(f"{p.freq_hz / 1e3:g}")
        self.vars["amplitude_vpp"].set(f"{p.amplitude_vpp:g}")
        self.vars["prf_hz"].set(f"{p.prf_hz:g}")
        self.vars["duty_cycle_pct"].set(f"{p.duty_cycle_pct:g}")
        self.vars["duration_s"].set(f"{p.duration_s:g}")
        self.load_var.set(p.load)

    def _save_preset(self) -> None:
        name = simpledialog.askstring("Save preset", "Preset name:", parent=self)
        if not name:
            return
        try:
            p = self._read_protocol(name)
        except ValueError as exc:
            messagebox.showerror("Cannot save", str(exc))
            return
        presets = self._load_presets()
        presets[name] = asdict(p)
        PRESETS_FILE.write_text(json.dumps(presets, indent=2), encoding="utf-8")
        self._refresh_presets()
        self.preset_var.set(name)
        self._log(f"Preset saved: {name}")

    def _delete_preset(self) -> None:
        name = self.preset_var.get()
        presets = self._load_presets()
        if name in presets and messagebox.askyesno("Delete preset", f"Delete '{name}'?"):
            del presets[name]
            PRESETS_FILE.write_text(json.dumps(presets, indent=2), encoding="utf-8")
            self.preset_var.set("")
            self._refresh_presets()

    # ---------------------------------------------------------- connection
    def _refresh_resources(self) -> None:
        """Scan for VISA resources in a background thread (the scan can take seconds)."""
        if self._scanning:
            return
        self._scanning = True
        self._scan_result = None
        self._log("Scanning for instruments…")
        threading.Thread(target=self._scan, daemon=True).start()
        self.after(200, self._poll_scan)

    def _scan(self) -> None:
        self._scan_result = AFG1022.list_resources()

    def _poll_scan(self) -> None:
        if self._scan_result is None:
            self.after(200, self._poll_scan)
            return
        res = self._scan_result
        self._scanning = False
        self.res_combo["values"] = res
        if res:
            if not self.res_var.get():
                usb = [r for r in res if r.upper().startswith("USB")]
                self.res_var.set((usb or res)[0])
            self._log(f"Found {len(res)} resource(s).")
        else:
            self._log("No VISA resources found. On macOS: `brew install libusb`, "
                      "check the USB cable/power, then press Refresh.")

    def _toggle_connection(self) -> None:
        if self.driver is None:
            self._connect()
        else:
            self._disconnect()

    def _connect(self) -> None:
        try:
            drv = SimulatedAFG() if self.sim_var.get() else AFG1022(self.res_var.get())
            drv.on_command = lambda c: self._log(f"SCPI> {c}")
            drv.connect()
            idn = drv.idn()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Connection failed", str(exc))
            return
        self.driver = drv
        self.conn_btn.configure(text="Disconnect")
        self.conn_status.set(f"Connected: {idn}")
        self._log(f"Connected: {idn}")

    def _disconnect(self) -> None:
        if self.running:
            self._stop("disconnected")
        if self.driver:
            self.driver.close()
        self.driver = None
        self.conn_btn.configure(text="Connect")
        self.conn_status.set("Not connected")
        self._log("Disconnected")

    # ---------------------------------------------------------- run / stop
    def _start(self) -> None:
        if self.running:
            return
        if self.driver is None:
            messagebox.showerror("Not connected", "Connect to the generator (or tick Simulation) first.")
            return
        try:
            p = self._read_protocol(self.preset_var.get() or "custom")
        except ValueError as exc:
            messagebox.showerror("Invalid parameters", str(exc))
            return
        errors, warnings = p.validate(self.limits)
        if errors:
            messagebox.showerror("Protocol rejected", "\n".join(errors))
            return
        if warnings and not messagebox.askokcancel("Check protocol", "\n".join(warnings) + "\n\nContinue?"):
            return

        try:
            self.driver.configure(p)
            self._readback = self.driver.readback()
            self._log("Readback: " + ", ".join(f"{k}={v}" for k, v in self._readback.items()))
            got = self._readback.get("ch1_ncycles", "n/a")
            try:
                held = float(got)
            except ValueError:
                held = None
                self._log("Warning: the generator did not report its cycle count; check it on the scope.")
            if held is not None and abs(held - p.cycles_per_burst) > 0.5:
                raise RuntimeError(
                    f"The generator holds {got} cycles per burst instead of the requested "
                    f"{p.cycles_per_burst}. Sonication aborted (the value was probably clamped)."
                )
            self.driver.output_on()
        except Exception as exc:  # noqa: BLE001
            self._safe_off()
            messagebox.showerror("Configuration failed", str(exc))
            return

        self.running = True
        self.current = p
        self._t0 = time.monotonic()
        self._started_at = datetime.now().isoformat(timespec="seconds")
        self._set_locked(True)
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._log(f"Output ON ({p.n_bursts} bursts of {p.cycles_per_burst} cycles, {p.duration_s:g} s)")
        self._end_id = self.after(int(p.duration_s * 1000), lambda: self._stop("completed"))
        self._tick()

    def _tick(self) -> None:
        if not self.running:
            return
        dur = self.current.duration_s
        elapsed = time.monotonic() - self._t0
        self.progress_var.set(min(100.0, 100.0 * elapsed / dur))
        self.time_var.set(f"SONICATING  {min(elapsed, dur):.2f} / {dur:.2f} s")
        self._tick_id = self.after(50, self._tick)

    def _stop(self, reason: str) -> None:
        if not self.running:
            return
        self.running = False
        for id_ in (self._end_id, self._tick_id):
            if id_ is not None:
                self.after_cancel(id_)
        elapsed = time.monotonic() - self._t0
        try:
            self.driver.output_off()
        except Exception as exc:  # noqa: BLE001
            reason += " (OUTPUT-OFF COMMAND FAILED)"
            messagebox.showerror("OUTPUT-OFF FAILED", f"Switch the generator output off manually!\n\n{exc}")
        self._log_run(reason, elapsed)
        self._log(f"Output OFF: {reason} after {elapsed:.3f} s")
        if reason == "completed":
            self.progress_var.set(100.0)
        self.time_var.set(f"idle (last: {reason}, {elapsed:.2f} s)")
        self._set_locked(False)
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def _safe_off(self) -> None:
        try:
            self.driver.output_off()
        except Exception:  # noqa: BLE001
            pass

    def _log_run(self, reason: str, elapsed: float) -> None:
        record = {
            "started_at": self._started_at,
            "ended_at": datetime.now().isoformat(timespec="seconds"),
            "end_reason": reason,
            "requested_duration_s": self.current.duration_s,
            "actual_duration_s": round(elapsed, 4),
            "protocol": asdict(self.current),
            "derived": {
                "cycles_per_burst": self.current.cycles_per_burst,
                "actual_duty_cycle_pct": self.current.actual_duty_cycle_pct,
                "n_bursts": self.current.n_bursts,
            },
            "instrument_readback": self._readback,
            "instrument": self.driver.name,
        }
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def _on_close(self) -> None:
        if self.running:
            self._stop("window closed")
        if self.driver:
            self.driver.close()
        self.destroy()


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
