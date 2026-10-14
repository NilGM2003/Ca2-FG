# lifu-gui

Tkinter GUI to pick an in-vitro LIFU sonication protocol (carrier frequency, amplitude,
PRF, duty cycle, duration), program a Tektronix AFG1022 over USB/VISA and switch the
channels on and off.

## Run

```
uv sync
uv run lifu-gui        # or: uv run python -m lifu_gui
uv run pytest          # tests (no instrument needed)
```

Tick **Simulation** in the GUI to try everything without hardware; the SCPI commands
that would be sent appear in the log pane.

## Wiring (one BNC cable)

Connect the **CH2 output** to the rear **Ext Trig/Burst/FSK In** connector of the AFG1022.
CH1 goes to your transducer chain as usual.

Why: the AFG1022 has no SCPI command for its internal trigger interval (front panel only),
and burst mode exists on CH1 only. So CH2 produces a 0 to 3.3 V square wave at the PRF and
every rising edge triggers one CH1 burst. The PRF is then set entirely from the GUI.

## How a protocol becomes a generator setting

- CH1: sine carrier at the chosen frequency, N-cycle burst, burst source EXTernal.
  N = round(DC x f / PRF); the GUI shows the actual duty cycle after rounding to whole
  cycles. The AFG1022 allows 1 to 50,000 cycles per burst.
- CH2: continuous square wave at the PRF, high-Z load setting, 3.3 Vpp with 1.65 V offset.
- Amplitude is sent as a bare number: the **unit (Vpp) is a front-panel setting** on this
  generator. Check that the display shows Vpp. The load setting (50 Ohm / High-Z) applies to CH1.
- Duration: both outputs are switched off by the GUI after T seconds (software timer, a few
  ms of jitter). The actual duration is logged.
- Stop button / Esc / closing the window switch both outputs off.

## Files in `data/` (created on first run, relative to where you launch the app)

- `limits.json`: allowed ranges; edit freely. Protocols outside them are rejected.
- `presets.json`: saved protocols.
- `sonication_log.jsonl`: one line per sonication (protocol, instrument readback,
  requested vs actual duration, how it ended).

## USB / VISA

On macOS: `brew install libusb` (needed by pyusb), then replug the generator.
The `SSL_CERT_FILE` warnings printed by uv come from a stale environment variable in
your shell profile; they are harmless.

Either install NI-VISA (pyvisa will use it automatically), or rely on the bundled
`pyvisa-py` + `pyusb`, which needs a libusb driver for the AFG1022 on Windows.

## Verify before trusting on hardware

On the first real run put an oscilloscope on CH1 and check the carrier frequency, the number
of cycles per burst, and the time between bursts (= 1/PRF). `uv run python -m lifu_gui.probe`
sends the GUI's commands one by one and reports what the generator accepts (never turns an
output on).
