import pytest

from lifu_gui.afg1022 import SimulatedAFG
from lifu_gui.protocol import Limits, Protocol


def test_derived_parameters():
    p = Protocol(freq_hz=500e3, prf_hz=1000, duty_cycle_pct=50, duration_s=2)
    assert p.cycles_per_burst == 250
    assert p.actual_duty_cycle_pct == pytest.approx(50)
    assert p.n_bursts == 2000
    assert p.prp_s == pytest.approx(1e-3)


def test_duty_cycle_rounds_to_whole_cycles():
    p = Protocol(freq_hz=500e3, prf_hz=1000, duty_cycle_pct=0.3)
    assert p.cycles_per_burst == 2  # 1.5 -> 2
    _, warnings = p.validate(Limits())
    assert warnings


def test_limits_reject():
    errors, _ = Protocol(amplitude_vpp=50).validate(Limits())
    assert any("Amplitude" in e for e in errors)
    errors, _ = Protocol(duty_cycle_pct=95).validate(Limits())
    assert errors


def test_burst_cycle_limit_is_configurable():
    p = Protocol(freq_hz=1.5e6, prf_hz=10, duty_cycle_pct=40)  # 60 000 cycles
    assert p.cycles_per_burst == 60000
    errors, _ = p.validate(Limits(burst_cycles=(1, 50_000)))
    assert any("cycles per burst" in e for e in errors)
    errors, _ = p.validate(Limits())
    assert not errors


def test_duration_shorter_than_period():
    errors, _ = Protocol(prf_hz=10, duration_s=0.05).validate(Limits())
    assert any("shorter" in e for e in errors)


def test_simulated_driver_configure():
    drv = SimulatedAFG()
    drv.configure(Protocol(prf_hz=1000))
    assert drv.state["SOURCE1:BURST:NCYCLES"] == "250"
    assert drv.state["SOURCE1:BURST:SOURCE"] == "EXTernal"
    assert drv.state["SOURCE2:FUNCTION:SHAPE"] == "SQUare"
    assert float(drv.state["SOURCE2:FREQUENCY:FIXED"]) == pytest.approx(1000)
    assert drv.readback()["ch1_ncycles"] == "250"
    drv.output_on()
    assert drv.state["OUTPUT1:STATE"] == "ON" and drv.state["OUTPUT2:STATE"] == "ON"
    drv.output_off()
    assert drv.state["OUTPUT2:STATE"] == "OFF"
