"""Sonication protocol model, derived burst parameters and safety-limit validation."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

# Default ceiling for cycles per burst (AFG1000-series programmer manual range).
# Editable as "burst_cycles" in data/limits.json; the app also checks what the generator holds.
MAX_BURST_CYCLES = 1_000_000


@dataclass(frozen=True)
class Limits:
    """Allowed ranges (min, max) in base units. Edit data/limits.json to change them."""

    freq_hz: tuple[float, float] = (50e3, 5e6)
    amplitude_vpp: tuple[float, float] = (0.01, 5.0)
    prf_hz: tuple[float, float] = (1.0, 10e3)
    duty_cycle_pct: tuple[float, float] = (0.1, 90.0)
    duration_s: tuple[float, float] = (0.01, 600.0)
    burst_cycles: tuple[float, float] = (1, MAX_BURST_CYCLES)

    @classmethod
    def load(cls, path: Path) -> "Limits":
        """Load limits from JSON; create the file with defaults if it does not exist."""
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(cls()), indent=2), encoding="utf-8")
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: tuple(v) for k, v in raw.items()})

    def summary(self) -> str:
        return (
            f"Limits: f {self.freq_hz[0]/1e3:g}–{self.freq_hz[1]/1e3:g} kHz, "
            f"amp {self.amplitude_vpp[0]:g}–{self.amplitude_vpp[1]:g} Vpp, "
            f"PRF {self.prf_hz[0]:g}–{self.prf_hz[1]:g} Hz, "
            f"DC {self.duty_cycle_pct[0]:g}–{self.duty_cycle_pct[1]:g} %, "
            f"dur {self.duration_s[0]:g}–{self.duration_s[1]:g} s, "
            f"cycles/burst ≤ {self.burst_cycles[1]:g}"
        )


@dataclass
class Protocol:
    name: str = "custom"
    freq_hz: float = 500e3
    amplitude_vpp: float = 0.1
    prf_hz: float = 1000.0
    duty_cycle_pct: float = 50.0
    duration_s: float = 1.0
    load: str = "50"  # "50" (ohm) or "HighZ"
    channels: list[int] = field(default_factory=lambda: [1])

    # ---- derived burst parameters -------------------------------------
    @property
    def prp_s(self) -> float:
        """Pulse repetition period (burst-to-burst), s."""
        return 1.0 / self.prf_hz

    @property
    def cycles_per_burst(self) -> int:
        return max(1, round(self.duty_cycle_pct / 100.0 * self.freq_hz / self.prf_hz))

    @property
    def burst_length_s(self) -> float:
        return self.cycles_per_burst / self.freq_hz

    @property
    def actual_duty_cycle_pct(self) -> float:
        return 100.0 * self.burst_length_s * self.prf_hz

    @property
    def n_bursts(self) -> int:
        return round(self.duration_s * self.prf_hz)

    # ---- (de)serialisation --------------------------------------------
    @classmethod
    def from_dict(cls, d: dict) -> "Protocol":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    # ---- validation ---------------------------------------------------
    def validate(self, limits: Limits) -> tuple[list[str], list[str]]:
        """Return (errors, warnings). Any error means the protocol must not be run."""
        errors: list[str] = []
        warnings: list[str] = []

        if not self.channels or any(c not in (1, 2) for c in self.channels):
            errors.append("Select at least one channel (1 and/or 2).")
        if self.load not in ("50", "HighZ"):
            errors.append("Load must be '50' or 'HighZ'.")
        for label, val in [
            ("Carrier frequency", self.freq_hz),
            ("Amplitude", self.amplitude_vpp),
            ("PRF", self.prf_hz),
            ("Duty cycle", self.duty_cycle_pct),
            ("Duration", self.duration_s),
        ]:
            if not val > 0:
                errors.append(f"{label} must be positive.")
        if errors:
            return errors, warnings

        def check(label, value, bounds, unit, scale=1.0):
            lo, hi = bounds
            if not lo <= value <= hi:
                errors.append(
                    f"{label} = {value / scale:g} {unit} is outside the allowed range "
                    f"{lo / scale:g}–{hi / scale:g} {unit}."
                )

        check("Carrier frequency", self.freq_hz, limits.freq_hz, "kHz", 1e3)
        check("Amplitude", self.amplitude_vpp, limits.amplitude_vpp, "Vpp")
        check("PRF", self.prf_hz, limits.prf_hz, "Hz")
        check("Duty cycle", self.duty_cycle_pct, limits.duty_cycle_pct, "%")
        check("Duration", self.duration_s, limits.duration_s, "s")

        n = self.cycles_per_burst
        actual = self.actual_duty_cycle_pct
        if n > limits.burst_cycles[1]:
            errors.append(
                f"{n} cycles per burst is above the limit of {limits.burst_cycles[1]:g} "
                f"(edit \"burst_cycles\" in data/limits.json to change it)."
            )
        if actual >= 100.0:
            errors.append("Burst is as long as the pulse period (duty cycle would be 100 %).")
        elif actual > limits.duty_cycle_pct[1]:
            errors.append(
                f"After rounding to whole cycles the duty cycle is {actual:.3g} %, "
                f"above the limit of {limits.duty_cycle_pct[1]:g} %."
            )
        elif abs(actual - self.duty_cycle_pct) > 0.05 * self.duty_cycle_pct:
            warnings.append(
                f"Duty cycle rounds to {actual:.3g} % ({n} cycles) instead of {self.duty_cycle_pct:g} %."
            )
        if self.n_bursts < 1:
            errors.append("Duration is shorter than one pulse repetition period.")
        return errors, warnings
