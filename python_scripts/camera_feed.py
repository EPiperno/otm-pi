"""Camera feed abstraction.

Currently supports two backends:
 1. OpenCV (V4L2) devices (/dev/videoN)
 2. Daheng industrial cameras via gxipy (backend = daheng)

create_camera_from_config() inspects the [camera] section of config.txt
to decide which backend to instantiate. It returns an object implementing:
    start(), stop(), get_frame(), reconfigure(width,height,fps),
    set_exposure(value), set_gain(value)

If the requested backend cannot be initialized, it will raise a RuntimeError
with a descriptive message. The caller (Flask app) can report this upstream.
"""
from __future__ import annotations
import time, threading, configparser
from pathlib import Path
from typing import Optional

try:  # OpenCV is optional but preferred for generic USB/UVC cameras
    import cv2  # type: ignore
except Exception:  # pragma: no cover - import guard
    cv2 = None  # type: ignore

try:  # Daheng SDK (gxipy) optional
    import gxipy as gx  # type: ignore
except Exception:  # pragma: no cover - import guard
    gx = None  # type: ignore

CONFIG_FILENAME = "config.txt"

class _BaseCameraThread:
    """Interface contract shared by backend implementations."""
    def start(self): raise NotImplementedError
    def stop(self): raise NotImplementedError
    def get_frame(self): raise NotImplementedError
    def reconfigure(self, width=None, height=None, fps=None): raise NotImplementedError
    def set_exposure(self, value): pass
    def set_gain(self, value): pass


class OpenCVCameraThread(_BaseCameraThread):
    def __init__(self, device=0, width=640, height=480, fps: int | None = None,
                 jpeg_quality=80, flip_mode: str = "none"):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.jpeg_quality = int(jpeg_quality)
        self.flip_mode = flip_mode
        self.cap = None
        self.running = False
        self.thread = None
        self._lock = threading.Lock()
        self._latest: bytes | None = None
        self.no_buffer_mode = False
        self.exposure = None
        self.gain = None
        self.last_frame_time: float | None = None
        self.frame_fail_count = 0

    def start(self):
        if cv2 is None:
            raise RuntimeError("OpenCV not installed (needed for backend=opencv)")
        if self.running:
            return
        self.cap = cv2.VideoCapture(self.device)
        if not self.cap or not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera device {self.device}")
        if self.width:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if self.fps:
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None
        self.thread = None

    def _loop(self):
        delay = 1 / (self.fps or 30)
        while self.running:
            ok, frame = self.cap.read() if self.cap else (False, None)
            if not ok:
                self.frame_fail_count += 1
                time.sleep(0.05)
                continue
            if self.flip_mode == 'h':
                frame = cv2.flip(frame, 1)
            elif self.flip_mode == 'v':
                frame = cv2.flip(frame, 0)
            elif self.flip_mode in ('hv', 'vh', 'both'):
                frame = cv2.flip(frame, -1)
            ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
            if ret:
                with self._lock:
                    self._latest = buf.tobytes()
                    self.last_frame_time = time.time()
                    self.frame_fail_count = 0
            time.sleep(delay)

    def get_frame(self):
        with self._lock:
            return self._latest

    def reconfigure(self, width=None, height=None, fps=None):
        was = self.running
        if was:
            self.stop()
        if width:
            self.width = width
        if height:
            self.height = height
        if fps:
            self.fps = fps
        if was:
            self.start()

    def set_exposure(self, value):  # Best effort via OpenCV props
        self.exposure = value
        if self.cap is not None and value is not None:
            try:
                # Many drivers expect exposure in log2 or ms; we just attempt.
                self.cap.set(cv2.CAP_PROP_EXPOSURE, float(value))
            except Exception:
                pass

    def set_gain(self, value):
        self.gain = value
        if self.cap is not None and value is not None:
            try:
                self.cap.set(cv2.CAP_PROP_GAIN, float(value))
            except Exception:
                pass

    def get_status(self) -> dict:
        return {
            'backend': 'opencv',
            'device': self.device,
            'width': self.width,
            'height': self.height,
            'fps_setting': self.fps,
            'running': self.running,
            'has_frame': self._latest is not None,
            'last_frame_age_s': (time.time() - self.last_frame_time) if self.last_frame_time else None,
            'frame_fail_count': self.frame_fail_count,
            'exposure': self.exposure,
            'gain': self.gain
        }


class DahengCameraThread(_BaseCameraThread):  # pragma: no cover - hardware dependent
    def __init__(self, index=1, serial: str | None = None, width=640, height=480,
                 fps: int | None = None, jpeg_quality=80, flip_mode: str = 'none'):
        if gx is None:
            raise RuntimeError("gxipy (Daheng SDK) not installed but backend=daheng requested")
        self.index = index  # 1-based per Daheng API
        self.serial = serial.strip() if serial else None
        self.width = width
        self.height = height
        self.fps = fps
        self.jpeg_quality = int(jpeg_quality)
        self.flip_mode = flip_mode
        self.running = False
        self.thread = None
        self._lock = threading.Lock()
        self._latest: bytes | None = None
        self.no_buffer_mode = False
        self.exposure = None
        self.gain = None
        self.cam = None
        self.last_frame_time: float | None = None
        self.frame_fail_count = 0

    def start(self):
        if self.running:
            return
        dm = gx.DeviceManager()
        dev_num, dev_info_list = dm.update_device_list()
        if dev_num == 0:
            raise RuntimeError("No Daheng cameras found")
        try:
            if self.serial:
                self.cam = dm.open_device_by_sn(self.serial)
            else:
                self.cam = dm.open_device_by_index(int(self.index))
        except Exception as e:
            raise RuntimeError(f"Failed to open Daheng camera (serial={self.serial} index={self.index}): {e}")
        # Stream on
        try:
            self.cam.stream_on()
        except Exception as e:
            raise RuntimeError(f"Failed to start Daheng stream: {e}")
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.cam:
            try:
                self.cam.stream_off()
            except Exception:
                pass
            try:
                self.cam.close_device()
            except Exception:
                pass
        self.cam = None
        self.thread = None

    def _loop(self):
        # Daheng data_stream[0] typical, fallback if not
        while self.running:
            try:
                ds = self.cam.data_stream[0]
                raw = ds.get_image(timeout=100)  # 100 ms
                if raw is None:
                    continue
                try:
                    rgb = raw.convert("RGB")
                    frame = rgb.get_numpy_array()
                except Exception:
                    # Some SDK versions: raw.get_numpy_array() already returns BGR
                    frame = raw.get_numpy_array()
                if frame is None:
                    continue
                if self.flip_mode == 'h' and cv2 is not None:
                    frame = cv2.flip(frame, 1)
                elif self.flip_mode == 'v' and cv2 is not None:
                    frame = cv2.flip(frame, 0)
                elif self.flip_mode in ('hv','vh','both') and cv2 is not None:
                    frame = cv2.flip(frame, -1)
                if cv2 is None:
                    # Cannot JPEG encode without OpenCV; skip
                    continue
                ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                if ret:
                    with self._lock:
                        self._latest = buf.tobytes()
                        self.last_frame_time = time.time()
                        self.frame_fail_count = 0
            except Exception:
                self.frame_fail_count += 1
                time.sleep(0.05)
                continue

    def get_frame(self):
        with self._lock:
            return self._latest

    def reconfigure(self, width=None, height=None, fps=None):
        # Minimal: restart stream if size/fps would change; many Daheng params require stop/start
        do_restart = width or height or fps
        if do_restart and self.running:
            self.stop()
        if width: self.width = width
        if height: self.height = height
        if fps: self.fps = fps
        if do_restart:
            self.start()

    def set_exposure(self, value):
        self.exposure = value
        if self.cam and value is not None:
            for attr in ("ExposureTime", "ExposureTimeRaw"):
                try:
                    node = getattr(self.cam, attr)
                    node.set(float(value))
                    break
                except Exception:
                    continue

    def set_gain(self, value):
        self.gain = value
        if self.cam and value is not None:
            for attr in ("Gain", "GainRaw"):
                try:
                    node = getattr(self.cam, attr)
                    node.set(float(value))
                    break
                except Exception:
                    continue

    def get_status(self) -> dict:
        return {
            'backend': 'daheng',
            'index': self.index,
            'serial': self.serial,
            'width': self.width,
            'height': self.height,
            'fps_setting': self.fps,
            'running': self.running,
            'has_frame': self._latest is not None,
            'last_frame_age_s': (time.time() - self.last_frame_time) if self.last_frame_time else None,
            'frame_fail_count': self.frame_fail_count,
            'exposure': self.exposure,
            'gain': self.gain
        }


def load_camera_config(path: str | Path | None = None):
    cfg_path = Path(path) if path else Path(__file__).parent / CONFIG_FILENAME
    parser = configparser.ConfigParser()
    if cfg_path.exists():
        parser.read(cfg_path)
    return parser


def create_camera_from_config(cfg: Optional[configparser.ConfigParser] = None):
    if cfg is None:
        cfg = load_camera_config()
    sec = cfg['camera'] if 'camera' in cfg else {}

    backend = (sec.get('backend', 'opencv') or 'opencv').split('#',1)[0].strip().lower()
    res = sec.get('resolution', '640x480')
    try:
        w, h = [int(x) for x in res.lower().replace('x','X').split('X')]
    except Exception:
        w, h = 640, 480
    fps_raw = sec.get('fps')
    try:
        fps = int(str(fps_raw).split('#',1)[0]) if fps_raw else None
    except Exception:
        fps = None
    flip = (sec.get('flip_mode', 'none') or 'none').split('#', 1)[0].strip().lower()

    # Sanitize jpeg_quality
    jq_raw = str(sec.get('jpeg_quality', 80))
    if '#' in jq_raw:
        jq_raw = jq_raw.split('#',1)[0]
    jq_raw = jq_raw.strip()
    import re as _re
    m = _re.match(r'(\d+)', jq_raw)
    jq_val = int(m.group(1)) if m else 80
    jq_val = max(10, min(100, jq_val))

    # Common optional fields
    serial = (sec.get('serial') or '').split('#',1)[0].strip() or None
    index_raw = (sec.get('index') or '').split('#',1)[0].strip()
    try:
        index = int(index_raw) if index_raw else 1
    except Exception:
        index = 1

    # Device path (OpenCV) fallback: if device key present use it; else derive from index (1-based -> /dev/video{index-1})
    device_key = sec.get('device')
    if device_key:
        device_key = device_key.split('#',1)[0].strip()
    if backend == 'opencv':
        if device_key:
            dev_obj: int | str = device_key
            if isinstance(dev_obj, str) and dev_obj.startswith('/dev/video'):
                try:
                    dev_obj = int(dev_obj.replace('/dev/video',''))
                except ValueError:
                    pass
        else:
            dev_obj = index - 1  # convert 1-based index to /dev/videoN number
        cam = OpenCVCameraThread(device=dev_obj, width=w, height=h, fps=fps,
                                 jpeg_quality=jq_val, flip_mode=flip)
    elif backend == 'daheng':
        cam = DahengCameraThread(index=index, serial=serial, width=w, height=h,
                                 fps=fps, jpeg_quality=jq_val, flip_mode=flip)
    else:
        raise RuntimeError(f"Unknown camera backend '{backend}' (expected opencv or daheng)")

    # Start camera with fallback logic for OpenCV backend (scan other indices if first fails)
    try:
        cam.start()
    except Exception as e:
        if isinstance(cam, OpenCVCameraThread) and isinstance(cam.device, int):
            original_err = str(e)
            for alt in range(0, 6):  # try /dev/video0-5
                if alt == cam.device:
                    continue
                try:
                    alt_cam = OpenCVCameraThread(device=alt, width=w, height=h, fps=fps,
                                                 jpeg_quality=jq_val, flip_mode=flip)
                    alt_cam.start()
                    cam = alt_cam
                    break
                except Exception:
                    continue
            else:
                raise RuntimeError(f"Failed to start OpenCV camera (initial device {cam.device}): {original_err}")
        else:
            raise

    # Optional initial exposure/gain
    try:
        exp_val = (sec.get('exposure_us') or '').split('#',1)[0].strip()
        if exp_val:
            cam.set_exposure(float(exp_val))
        gain_val = (sec.get('gain_db') or '').split('#',1)[0].strip()
        if gain_val:
            cam.set_gain(float(gain_val))
    except Exception:
        pass
    return cam


def mjpeg_frame_generator(cam, boundary: bytes = b'frame'):
    while True:
        frame = cam.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue
        yield (b'--' + boundary + b'\r\n'
               b'Content-Type: image/jpeg\r\n'
               b'Content-Length: ' + str(len(frame)).encode() + b'\r\n\r\n' +
               frame + b'\r\n')