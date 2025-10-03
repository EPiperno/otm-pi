"""Motor configuration for stepper motors used on the Adafruit Stepper Motor HAT.

Edit the values in MOTOR_CONFIG to match your hardware. These settings are
referenced by functions in `run_stepper.py`.

Notes:
  - 1.8 deg/step => 200 full steps per revolution (360 / 1.8).
  - styles: SINGLE, DOUBLE, INTERLEAVE, MICROSTEP (if supported by hardware)
  - current_limit is informational only; the Motor HAT (TB6612) does not allow
    you to set a current limit in software. Keep it here for documentation.
  - microsteps_per_full_step is used only if you choose the MICROSTEP style.
"""

from __future__ import annotations

MOTOR_CONFIG = {
    # Global defaults applied if a specific motor key omits a field.
    "defaults": {
        "degrees_per_step": 1.8,          # Mechanical full-step angle
        "microsteps_per_full_step": 8,     # Library treats MICROSTEP as 8 (classic Adafruit shield)
        "recommended_style": "SINGLE",    # Default drive style
        "rpm": 10,                        # Default speed if not overridden by call
        "current_limit_amps": 1.3,        # Informational
        "voltage": 5.0,                   # Supply voltage (informational)
    },
    # Motor A: connected to M1/M2 (MotorKit.stepper1)
    "A": {
        "description": "Primary axis stepper on M1/M2",
        # Override per-motor settings here if desired.
    },
    # Motor B: connected to M3/M4 (MotorKit.stepper2)
    "B": {
        "description": "Secondary axis stepper on M3/M4",
    },
}


def get_motor_settings(motor_id: str) -> dict:
    """Return merged settings for the given motor id (e.g. 'A' or 'B')."""
    mid = motor_id.upper()
    defaults = MOTOR_CONFIG.get("defaults", {})
    specific = MOTOR_CONFIG.get(mid, {})
    merged = {**defaults, **specific}
    merged["motor_id"] = mid
    return merged


__all__ = ["MOTOR_CONFIG", "get_motor_settings"]
