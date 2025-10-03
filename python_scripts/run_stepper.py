"""Helper functions to control two stepper motors via Adafruit MotorKit.

Configuration comes from `config.txt` (INI-style). Axis sections used:
  [Z]      -> Vertical linear axis on M1/M2 (kit.stepper1)
  [THETA]  -> Rotational axis on M3/M4 (kit.stepper2)

Other sections (e.g. [camera]) are ignored by this module.

Example usage in another script:
    from run_stepper import init_motors, move_angle, release_all
    kit = init_motors()
    move_angle(kit, 'Z', 90)
    release_all(kit)
"""

from __future__ import annotations

import math
import configparser
from pathlib import Path
import time
from typing import Literal, Optional

try:
	from adafruit_motorkit import MotorKit  # type: ignore
	from adafruit_motor import stepper  # type: ignore
except ImportError:  # pragma: no cover - provide graceful fallback
	class _DummyStepper:
		def onestep(self, *_, **__):
			pass
		def release(self):
			pass

	class MotorKit:  # type: ignore
		def __init__(self, *_, **__):
			self.stepper1 = _DummyStepper()
			self.stepper2 = _DummyStepper()

	class _DummyStepperConst:
		SINGLE=1; DOUBLE=2; INTERLEAVE=3; MICROSTEP=4
		FORWARD=1; BACKWARD=2

	stepper = _DummyStepperConst()  # type: ignore
	print("[run_stepper] Warning: Adafruit MotorKit libraries not installed; using no-op dummy motors.")

StepperID = Literal['Z', 'THETA']
StepStyle = Literal['SINGLE', 'DOUBLE', 'INTERLEAVE', 'MICROSTEP']

STYLE_MAP = {
	'SINGLE': stepper.SINGLE,
	'DOUBLE': stepper.DOUBLE,
	'INTERLEAVE': stepper.INTERLEAVE,
	'MICROSTEP': stepper.MICROSTEP,
}


CONFIG_FILENAME = "config.txt"


def load_config(path: Optional[str | Path] = None) -> configparser.ConfigParser:
	"""Load and return the global configuration parser.

	If path is None, look for CONFIG_FILENAME adjacent to this file.
	Creates a parser even if file missing (raises FileNotFoundError).
	"""
	cfg_path = Path(path) if path else Path(__file__).parent / CONFIG_FILENAME
	if not cfg_path.exists():  # Provide a clearer message
		raise FileNotFoundError(f"Configuration file not found: {cfg_path}")
	parser = configparser.ConfigParser()
	parser.read(cfg_path)
	return parser


## Removed calibration utilities; pitch now configured manually with 'screw_pitch'.


def _motor_section_name(motor_id: StepperID) -> str:
	# Axis sections are direct (Z / THETA)
	return motor_id.upper()


def get_motor_settings(motor_id: StepperID, cfg: Optional[configparser.ConfigParser] = None) -> dict:
	"""Return axis settings from config for the given axis id (Z / THETA).

	No shared defaults are used; each axis must fully define its parameters.
	"""
	if cfg is None:
		cfg = load_config()
	section_name = _motor_section_name(motor_id)
	if section_name not in cfg:
		raise KeyError(f"Axis section '{section_name}' not found in config")
	data = dict(cfg[section_name])

	def _float(key, fallback=None):
		if key not in data:
			return fallback
		raw = data[key]
		# Strip inline comments beginning with '#' or ';'
		for sep in ('#', ';'):
			if sep in raw:
				raw = raw.split(sep, 1)[0]
		try:
			return float(raw.strip())
		except ValueError:
			return fallback

	parsed = {
		**data,
		'axis_id': motor_id,
		'degrees_per_step': _float('degrees_per_step', 1.8),
		'microsteps_per_full_step': int(_float('microsteps_per_full_step', 8)),
		'default_speed_mm_s': _float('default_speed_mm_s', 0),
		'default_speed_deg_s': _float('default_speed_deg_s', 0),
		'current_limit_amps': _float('current_limit_amps', 0),
		'voltage': _float('voltage', 0),
		'screw_pitch': _float('screw_pitch', 0),  # For Z: mm/rev, For THETA: deg/rev (optional)
		'max_travel_mm': _float('max_travel_mm', 0),
	}

	# Heuristic adjustment for THETA: if user provided screw_pitch (deg per motor rev)
	# but left degrees_per_step as the raw motor angle (likely 1.8), derive effective
	# axis degrees per step = screw_pitch / full_steps_per_motor_rev (assumed 200 for 1.8 deg motor).
	if motor_id == 'THETA':
		screw_pitch = parsed.get('screw_pitch') or 0
		if screw_pitch > 0 and abs(parsed['degrees_per_step'] - 1.8) < 1e-6:
			parsed['degrees_per_step'] = screw_pitch / 200.0
			parsed['__auto_theta_derived'] = True  # mark for status/debug if needed
	return parsed


def init_motors(i2c_address: int = 0x60, i2c_bus=None) -> MotorKit:
	"""Initialize and return a MotorKit instance.

	i2c_address: Override the default Motor HAT address if needed.
	i2c_bus: Provide a pre-configured busio.I2C object if desired.
	"""
	kit = MotorKit(address=i2c_address, i2c=i2c_bus)
	return kit


def _get_stepper(kit: MotorKit, motor_id: StepperID):
	if motor_id == 'Z':
		return kit.stepper1
	if motor_id == 'THETA':
		return kit.stepper2
	raise ValueError(f"Unknown axis '{motor_id}' (expected 'Z' or 'THETA')")


def _resolve_style(style: Optional[StepStyle], motor_id: StepperID, cfg=None) -> int:
	settings = get_motor_settings(motor_id, cfg)
	style_name = (style or settings['recommended_style']).upper()
	if style_name not in STYLE_MAP:
		raise ValueError(f"Unsupported step style '{style_name}'")
	return STYLE_MAP[style_name]


def steps_per_revolution(motor_id: StepperID, cfg=None) -> int:
	settings = get_motor_settings(motor_id, cfg)
	deg_per_step = settings['degrees_per_step']
	return int(round(360.0 / deg_per_step))


def angle_to_steps(motor_id: StepperID, angle_degrees: float, style: Optional[StepStyle] = None, cfg=None) -> int:
	settings = get_motor_settings(motor_id, cfg)
	base_steps = steps_per_revolution(motor_id, cfg)
	# If using microstep style, adjust effective steps per revolution
	if (style or settings['recommended_style']).upper() == 'MICROSTEP':
		micro = settings['microsteps_per_full_step']
		base_steps *= micro
	steps = int(round((angle_degrees / 360.0) * base_steps))
	return steps


def move_steps(
	kit: MotorKit,
	motor_id: StepperID,
	steps: int,
	*,
	direction: Literal['forward', 'backward'] | None = None,
	style: StepStyle | None = None,
	speed_mm_s: Optional[float] = None,
	speed_deg_s: Optional[float] = None,
	release: bool = False,
	delay_override: Optional[float] = None,
	ramp_fraction: Optional[float] = None,
	min_speed_factor: float = 0.3,
	enable_ramp: bool = True,
) -> None:
	"""Move a motor by a number of (possibly micro) steps.

	direction: inferred from sign of steps if not provided.
	speed_mm_s / speed_deg_s: target surface speed (axis dependent).
	release: release coils after movement.
	delay_override: bypass speed logic with fixed delay per step.
	ramp_fraction: fraction (0-0.5) of total steps used to accelerate (and same to decelerate if room).
	min_speed_factor: starting speed as fraction of target (0<factor<=1) when ramping.
	enable_ramp: disable to use flat speed profile.
	"""
	if steps == 0:
		return
	cfg = None  # Lazy load only if needed inside helpers
	settings = get_motor_settings(motor_id, cfg)
	style_enum = _resolve_style(style, motor_id, cfg)
	stepper_obj = _get_stepper(kit, motor_id)

	# Determine direction and magnitude
	if direction is None:
		direction = 'forward' if steps > 0 else 'backward'
	step_dir_enum = stepper.FORWARD if direction == 'forward' else stepper.BACKWARD
	steps_remaining = abs(steps)

	# Derive delay per step from speed if provided.
	if delay_override is not None:
		delay_per_step = delay_override
	else:
		# Determine steps per unit (mm or degree) depending on axis type
		spr = steps_per_revolution(motor_id, cfg)
		if style_enum == stepper.MICROSTEP:
			spr *= settings['microsteps_per_full_step']
		if motor_id == 'Z':
			pitch = settings.get('screw_pitch', 0) or 0
			if pitch <= 0:
				# Cannot compute linear speed; fallback to conservative delay
				delay_per_step = 0.01
			else:
				use_speed = speed_mm_s if speed_mm_s is not None else settings.get('default_speed_mm_s', 0.0)
				if use_speed <= 0:
					# default fallback 0.1 mm/s
					use_speed = 0.1
				# mm/s -> rev/s -> steps/s
				rev_per_s = use_speed / pitch
				steps_per_s = rev_per_s * spr
				delay_per_step = 1.0 / steps_per_s if steps_per_s > 0 else 0.0
		else:  # THETA (angular)
			deg_per_step = 360.0 / spr
			use_speed = speed_deg_s if speed_deg_s is not None else settings.get('default_speed_deg_s', 0.0)
			if use_speed <= 0:
				use_speed = 1.0  # default 1 deg/s fallback
			steps_per_s = use_speed / deg_per_step
			delay_per_step = 1.0 / steps_per_s if steps_per_s > 0 else 0.0

	# Prepare ramp parameters (allow config default)
	if ramp_fraction is None:
		cfg_full = load_config()
		try:
			ramp_fraction = float(cfg_full[_motor_section_name(motor_id)].get('ramp_fraction', '0.15'))
		except Exception:
			ramp_fraction = 0.15
	ramp_fraction = max(0.0, min(ramp_fraction, 0.5))
	if not enable_ramp or steps_remaining < 10 or ramp_fraction == 0:
		# Flat profile
		for _ in range(steps_remaining):
			stepper_obj.onestep(direction=step_dir_enum, style=style_enum)
			if delay_per_step > 0:
				time.sleep(delay_per_step)
	else:
		ramp_steps = max(1, int(steps_remaining * ramp_fraction))
		decel_start = steps_remaining - ramp_steps
		start_factor = max(1e-3, min_speed_factor)
		for i in range(steps_remaining):
			# Determine speed factor
			if i < ramp_steps:  # accelerating
				f = start_factor + (1 - start_factor) * (i / ramp_steps)
			elif i >= decel_start:  # decelerating
				j = i - decel_start
				f = start_factor + (1 - start_factor) * ((steps_remaining - i - 1) / ramp_steps)
				f = max(start_factor, f)
			else:
				f = 1.0
			adj_delay = delay_per_step / f if delay_per_step > 0 else 0
			stepper_obj.onestep(direction=step_dir_enum, style=style_enum)
			if adj_delay > 0:
				time.sleep(adj_delay)

	if release:
		stepper_obj.release()


def move_angle(
	kit: MotorKit,
	motor_id: StepperID,
	angle_degrees: float,
	*,
	style: StepStyle | None = None,
	speed_deg_s: Optional[float] = None,
	release: bool = False,
	**profile_kwargs,
) -> int:
	"""Move axis by an angle in degrees. Returns steps actually taken."""
	steps = angle_to_steps(motor_id, angle_degrees, style)
	move_steps(kit, motor_id, steps, style=style, speed_deg_s=speed_deg_s, release=release, **profile_kwargs)
	return steps


def move_revolutions(
	kit: MotorKit,
	motor_id: StepperID,
	revolutions: float,
	*,
	style: StepStyle | None = None,
	speed_deg_s: Optional[float] = None,
	release: bool = False,
	**profile_kwargs,
) -> int:
	"""Move axis by fractional revolutions (positive or negative). Returns steps taken.

	Note: For THETA axis only; for Z use move_mm or move_steps.
	"""
	angle = revolutions * 360.0
	return move_angle(kit, motor_id, angle, style=style, speed_deg_s=speed_deg_s, release=release, **profile_kwargs)


def steps_to_mm(motor_id: StepperID, steps: int, style: Optional[StepStyle] = None, cfg=None) -> float:
	"""Convert a step count to millimeters using configured lead screw pitch.

	If pitch not defined (0), returns 0.0.
	"""
	settings = get_motor_settings(motor_id, cfg)
	pitch = settings.get('screw_pitch', 0) or 0
	if pitch <= 0:
		return 0.0
	# Determine effective steps per full revolution for the style used
	spr = steps_per_revolution(motor_id, cfg)
	if (style or settings['recommended_style']).upper() == 'MICROSTEP':
		spr *= settings['microsteps_per_full_step']
	return (steps / spr) * pitch


def mm_to_steps(motor_id: StepperID, mm: float, style: Optional[StepStyle] = None, cfg=None) -> int:
	settings = get_motor_settings(motor_id, cfg)
	pitch = settings.get('screw_pitch', 0) or 0
	if pitch <= 0:
		raise ValueError("screw_pitch not set in config for linear motion (mm per rev)")
	spr = steps_per_revolution(motor_id, cfg)
	if (style or settings['recommended_style']).upper() == 'MICROSTEP':
		spr *= settings['microsteps_per_full_step']
	steps = int(round((mm / pitch) * spr))
	return steps


def move_mm(
	kit: MotorKit,
	motor_id: StepperID,
	distance_mm: float,
	*,
	style: StepStyle | None = None,
	speed_mm_s: Optional[float] = None,
	release: bool = False,
	limit_check: bool = True,
	cfg=None,
	**profile_kwargs,
) -> int:
	"""Move motor a linear distance in mm (positive or negative).

	This function does not keep absolute position internally; integrate with an
	upper-level position tracker or homing routine for safety. If limit_check is
	True and max_travel_mm is set (>0), only warns (does not block) if requested
	distance exceeds that range, because absolute position unknown.
	"""
	settings = get_motor_settings(motor_id, cfg)
	max_travel = settings.get('max_travel_mm', 0) or 0
	steps = mm_to_steps(motor_id, distance_mm, style, cfg)
	if limit_check and max_travel > 0:
		# Since we lack current absolute position, we provide an advisory.
		abs_dist = abs(distance_mm)
		if abs_dist > max_travel:
			print(f"Warning: requested move {abs_dist}mm exceeds configured max_travel_mm {max_travel} (advisory only)")
	move_steps(kit, motor_id, steps, style=style, speed_mm_s=speed_mm_s, release=release, **profile_kwargs)
	return steps


def release_motor(kit: MotorKit, motor_id: StepperID) -> None:
	_get_stepper(kit, motor_id).release()


def release_all(kit: MotorKit) -> None:
	for axis in ('Z', 'THETA'):
		try:
			release_motor(kit, axis)  # type: ignore[arg-type]
		except Exception:
			pass


def demo(kit: MotorKit):  # pragma: no cover - convenience runtime demo
	print("Demo: Z 1.2mm up/down with ramp, THETA 15 degrees")
	move_mm(kit, 'Z', 1.2, style='SINGLE', speed_mm_s=0.3, ramp_fraction=0.2)
	move_mm(kit, 'Z', -1.2, style='SINGLE', speed_mm_s=0.3, ramp_fraction=0.2, release=True)
	move_angle(kit, 'THETA', 15, style='DOUBLE', speed_deg_s=2.0, ramp_fraction=0.15, release=True)
	print("Demo complete.")


if __name__ == "__main__":  # pragma: no cover
	k = init_motors()
	demo(k)

