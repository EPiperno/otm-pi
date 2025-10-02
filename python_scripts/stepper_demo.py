# stepper_safe_single.py
import time
from adafruit_motorkit import MotorKit
from adafruit_motor import stepper

kit = MotorKit(address=0x60)  # default address
motor = kit.stepper1          # M1+M2 = stepper1

STEPS_PER_REV = 200           # 1.8°/step
STYLE = stepper.SINGLE        # single-coil only (lower heat)
MIN_DELAY = 0.0025            # slowest (safer) ~2.5 ms/step
MAX_DELAY = 0.0009            # fastest end of ramp; increase if it stalls
RAMP_STEPS = 50               # steps to accelerate/decelerate

def step_with_ramp(steps, direction):
    # accelerate
    for i in range(1, RAMP_STEPS + 1):
        motor.onestep(direction=direction, style=STYLE)
        # simple linear ramp; you can make it more gentle if needed
        delay = MIN_DELAY - (MIN_DELAY - MAX_DELAY) * (i / RAMP_STEPS)
        time.sleep(max(delay, MAX_DELAY))

    # cruise
    cruise_steps = max(0, steps - 2 * RAMP_STEPS)
    for _ in range(cruise_steps):
        motor.onestep(direction=direction, style=STYLE)
        time.sleep(MAX_DELAY)

    # decelerate
    for i in range(RAMP_STEPS, 0, -1):
        motor.onestep(direction=direction, style=STYLE)
        delay = MIN_DELAY - (MIN_DELAY - MAX_DELAY) * (i / RAMP_STEPS)
        time.sleep(max(delay, MAX_DELAY))

try:
    print("Forward 1 rev (SINGLE)...")
    step_with_ramp(STEPS_PER_REV, stepper.FORWARD)
    time.sleep(0.5)

    print("Backward 1 rev (SINGLE)...")
    step_with_ramp(STEPS_PER_REV, stepper.BACKWARD)
    time.sleep(0.5)

    print("Done.")
finally:
    motor.release()  # de-energize coils (reduces heating)
