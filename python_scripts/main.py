"""Entry point script for testing motion axes (Z and THETA) with MotorKit.

Axes:
    Z      -> Linear vertical stage (stepper1 M1/M2)
    THETA  -> Rotational stage (stepper2 M3/M4)

Configuration is loaded from `config.txt` with sections [Z] and [THETA].

Examples:
        python main.py --axis Z --angle 90
        python main.py --axis THETA --revs 0.25 --style DOUBLE --rpm 5
        python main.py --axis Z --mm 5 --rpm 6 --release
        python main.py --demo
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from run_stepper import (
    init_motors,
    move_angle,
    move_revolutions,
    move_mm,
    release_all,
    load_config,
    get_motor_settings,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Stepper motor control test harness")
    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument("--angle", type=float, help="Angle in degrees to move (can be negative)")
    g.add_argument("--revs", type=float, help="Revolutions to move (can be negative)")
    g.add_argument("--mm", type=float, help="Linear millimeters to move (requires screw_pitch in config for Z)")
    p.add_argument("--axis", choices=["Z", "THETA"], default="Z", help="Axis ID (Z linear, THETA rotational)")
    p.add_argument("--style", choices=["SINGLE", "DOUBLE", "INTERLEAVE", "MICROSTEP"], help="Step style override")
    speed_group = p.add_mutually_exclusive_group(required=False)
    speed_group.add_argument("--speed-mm-s", type=float, help="Linear speed (mm/s) for Z axis")
    speed_group.add_argument("--speed-deg-s", type=float, help="Angular speed (deg/s) for THETA axis")
    p.add_argument("--ramp-fraction", type=float, default=0.15, help="Fraction of steps for accel/decel (0-0.5)")
    p.add_argument("--no-ramp", action="store_true", help="Disable acceleration ramping")
    p.add_argument("--release", action="store_true", help="Release coils after move")
    p.add_argument("--demo", action="store_true", help="Run built-in short demo sequence")
    p.add_argument("--status", action="store_true", help="Print derived axis parameters and exit")
    p.add_argument("--test-suite", action="store_true", help="Run a small automated motion test for both axes")
    p.add_argument("--config", type=str, help="Path to config.txt if not in script directory")
    return p


def run_demo(kit):
    print("Demo: 90 deg Z -> -90 deg Z -> 0.5 rev THETA")
    move_angle(kit, 'Z', 90, style='SINGLE', rpm=10)
    move_angle(kit, 'Z', -90, style='SINGLE', rpm=10, release=True)
    move_revolutions(kit, 'THETA', 0.5, style='DOUBLE', rpm=5, release=True)
    print("Demo complete")


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)

    # Load config early for validation
    cfg_path = args.config if args.config else None
    try:
        cfg = load_config(cfg_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    kit = init_motors()

    if args.status:
        for axis in ("Z", "THETA"):
            try:
                s = get_motor_settings(axis, cfg)
            except Exception as e:
                print(f"Axis {axis}: error: {e}")
                continue
            spr = int(round(360 / s['degrees_per_step']))
            micro = s['microsteps_per_full_step']
            screw_pitch = s.get('screw_pitch')
            if axis == 'Z' and screw_pitch:
                mm_per_full_step = screw_pitch / spr
                mm_per_micro = mm_per_full_step / (micro if micro else 1)
                print(f"[STATUS] {axis}: screw_pitch={screw_pitch} mm/rev steps/rev={spr} mm/full-step={mm_per_full_step:.6f} mm/microstep={mm_per_micro:.6f}")
            elif axis == 'THETA':
                deg_per_step = s['degrees_per_step']
                if screw_pitch:
                    flag = " (auto-derived)" if s.get('__auto_theta_derived') else ""
                    print(f"[STATUS] {axis}: screw_pitch={screw_pitch} deg/rev deg/step={deg_per_step}{flag}")
                else:
                    print(f"[STATUS] {axis}: deg/step={deg_per_step}")
        return 0

    if args.test_suite:
        print("Running test suite: small Z and THETA motions")
        # Z test: forward/back 2 mm
        try:
            move_mm(kit, 'Z', 2.0, style=args.style or 'SINGLE', speed_mm_s=args.speed_mm_s or 0.5, ramp_fraction=args.ramp_fraction)
            move_mm(kit, 'Z', -2.0, style=args.style or 'SINGLE', speed_mm_s=args.speed_mm_s or 0.5, ramp_fraction=args.ramp_fraction, release=False)
        except Exception as e:
            print(f"Z test error: {e}")
        # THETA test: 5 degrees forward/back
        try:
            move_angle(kit, 'THETA', 5.0, style=args.style or 'SINGLE', speed_deg_s=args.speed_deg_s or 1.0, ramp_fraction=args.ramp_fraction)
            move_angle(kit, 'THETA', -5.0, style=args.style or 'SINGLE', speed_deg_s=args.speed_deg_s or 1.0, ramp_fraction=args.ramp_fraction, release=False)
        except Exception as e:
            print(f"THETA test error: {e}")
        if args.release:
            release_all(kit)
        print("Test suite complete")
        return 0

    if args.demo:
        run_demo(kit)
        release_all(kit)
        return 0

    if args.angle is None and args.revs is None and args.mm is None and not args.demo:
        parser.error("One of --angle, --revs, --mm or --demo must be provided")

    # Axis-specific unit safety (Requirement #4)
    if args.axis == 'Z' and args.revs is not None:
        parser.error("Z axis is linear: use --mm (or --angle only if you intentionally treat Z as angular).")
    if args.axis == 'THETA' and args.mm is not None:
        parser.error("THETA axis is angular: use --angle or --revs, not --mm.")

    speed_mm_s = args.speed_mm_s
    speed_deg_s = args.speed_deg_s
    style = args.style
    motor_id = args.axis
    # Show settings summary
    settings = get_motor_settings(motor_id, cfg)
    steps_per_rev = int(round(360/settings['degrees_per_step']))
    if motor_id == 'Z':
        print(f"Axis {motor_id} settings: steps/rev={steps_per_rev} default_speed_mm_s={settings.get('default_speed_mm_s')}")
    else:
        print(f"Axis {motor_id} settings: steps/rev={steps_per_rev} default_speed_deg_s={settings.get('default_speed_deg_s')}")

    profile_kwargs = {
        'ramp_fraction': args.ramp_fraction,
        'enable_ramp': not args.no_ramp,
    }

    if args.angle is not None:
        print(f"Moving axis {motor_id} by {args.angle} degrees (style={style or 'default'} speed_deg_s={speed_deg_s or 'default'})")
        move_angle(kit, motor_id, args.angle, style=style, speed_deg_s=speed_deg_s, release=args.release, **profile_kwargs)
    elif args.revs is not None:
        print(f"Moving axis {motor_id} by {args.revs} revolutions (style={style or 'default'} speed_deg_s={speed_deg_s or 'default'})")
        move_revolutions(kit, motor_id, args.revs, style=style, speed_deg_s=speed_deg_s, release=args.release, **profile_kwargs)
    else:
        print(f"Moving axis {motor_id} by {args.mm} mm (style={style or 'default'} speed_mm_s={speed_mm_s or 'default'})")
        move_mm(kit, motor_id, args.mm, style=style, speed_mm_s=speed_mm_s, release=args.release, **profile_kwargs)

    if not args.release:
        print("Note: coils still energized (use --release or power cycle to disable)")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
