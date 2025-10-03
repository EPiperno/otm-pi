# --- camera init (drop into your script before cam.stream_on()) ---
import gxipy as gx
import numpy as np
import cv2
from flask import Flask, Response

app = Flask(__name__)

dm = gx.DeviceManager()
dev_num, devs = dm.update_device_list()
assert dev_num > 0, "No Daheng cameras found"
cam = dm.open_device_by_sn(devs[0]["sn"])

# 1) Make sure we are in FREE-RUN (no external/software trigger needed)
try:
    cam.TriggerMode.set(gx.GxSwitchEntry.OFF)  # continuous acquisition
except Exception:
    pass  # some models may not expose this exactly; safe to ignore if absent

# 2) Set a safe pixel format (8-bit Bayer or 8-bit color)
#    We'll convert to RGB later; if your sensor is mono use MONO8 instead.
try:
    # Try Bayer 8-bit first (common on color MER/MER2 cameras)
    cam.PixelFormat.set(gx.GxPixelFormatEntry.BAYER_RG8)
except Exception:
    try:
        cam.PixelFormat.set(gx.GxPixelFormatEntry.BAYER_BG8)
    except Exception:
        # Fallback to MONO8 if it's a mono sensor
        cam.PixelFormat.set(gx.GxPixelFormatEntry.MONO8)

# 3) Exposure / Gain: start bright so we see something
try:
    # turn off auto exposure so we control it
    cam.ExposureAuto.set(gx.GxAutoEntry.OFF)
except Exception:
    pass

# 10 ms exposure is a good start; increase if dark (e.g., 20000–40000 us)
try:
    cam.ExposureTime.set(20000.0)  # microseconds
except Exception:
    pass

# modest gain to avoid pure black if lighting is low
try:
    # if auto-gain exists, disable then set manual
    cam.GainAuto.set(gx.GxAutoEntry.OFF)
except Exception:
    pass
try:
    cam.Gain.set(6.0)  # dB-ish; adjust as needed
except Exception:
    pass

# white balance (for color)
try:
    cam.BalanceWhiteAuto.set(gx.GxAutoEntry.ONCE)  # or CONTINUOUS
except Exception:
    pass

# Optional: reduce resolution/FPS to ease the Pi
# try:
#     cam.Width.set(1280); cam.Height.set(720)
# except Exception:
#     pass

# If your model exposes frame rate control:
# try:
#     cam.AcquisitionFrameRateMode.set(gx.GxSwitchEntry.ON)
#     cam.AcquisitionFrameRate.set(15.0)
# except Exception:
#     pass

cam.stream_on()

def gen_frames():
    while True:
        raw = cam.data_stream[0].get_image(timeout=1000)
        if raw is None:
            continue

        # Convert to RGB; if MONO8, produce a 3-channel for JPEG
        # Many Daheng SDK builds support raw.convert("RGB")
        try:
            rgb = raw.convert("RGB")
            frame = rgb.get_numpy_array()  # HxWx3 (uint8)
        except Exception:
            # Fallback for MONO8 or if convert not available
            mono = raw.get_numpy_array()   # HxW (uint8 or 16)
            if mono is None:
                continue
            if mono.dtype != np.uint8:
                # scale 10/12/16-bit to 8-bit for viewing
                mono8 = (mono / mono.max() * 255).astype(np.uint8)
            else:
                mono8 = mono
            frame = cv2.cvtColor(mono8, cv2.COLOR_GRAY2RGB)

        # Diagnostics: see if we’re getting darkness vs. zeros
        m, M, mean = frame.min(), frame.max(), frame.mean()
        # Print occasionally; comment out once stable
        print(f"min:{m} max:{M} mean:{mean:.1f}")

        ok, jpg = cv2.imencode(".jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR),
                               [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            continue

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")

@app.route("/video")
def video():
    return Response(gen_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/")
def index():
    return '<html><body style="margin:0;background:#000;"><img src="/video" style="width:100%;height:auto;display:block;"></body></html>'

if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:
        try:
            cam.stream_off()
            cam.close_device()
        except Exception:
            pass
