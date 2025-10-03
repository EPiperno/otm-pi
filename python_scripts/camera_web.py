"""Headless web camera interface with exposure/gain controls.

Usage:
    python camera_web.py

Features:
 - MJPEG streaming endpoint at /stream.mjpg
 - Simple HTML control page at /
 - POST /settings to update exposure & gain (form or JSON)
 - Reads optional [camera] section from config.txt

Future integration:
 - Object tracking overlay
 - Motor control endpoints to center object
"""

from __future__ import annotations

import threading
import time
import io
import configparser
import os
from pathlib import Path
from typing import Optional

from flask import Flask, Response, request, jsonify, render_template_string

try:  # OpenCV optional
    import cv2  # type: ignore
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore

try:  # Daheng SDK optional
    from gxipy import DeviceManager  # type: ignore
except Exception:  # pragma: no cover
    DeviceManager = None  # type: ignore


CONFIG_FILENAME = "config.txt"

HTML_PAGE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <title>Camera Web UI</title>
    <style>
        body { font-family: sans-serif; margin: 1rem; background: #111; color: #eee; }
        .layout { display:flex; flex-wrap:wrap; gap:1rem; align-items:flex-start; }
        .video-panel { background:#222; padding:1rem; border-radius:8px; flex:1 1 480px; max-width:60%; }
        .controls-panel { background:#222; padding:1rem; border-radius:8px; flex:1 1 300px; max-width:38%; }
        h2 { margin-top:0; }
        label { display:inline-block; width:90px; }
        input[type=number], select { width:120px; background:#111; color:#eee; border:1px solid #333; }
        button { padding:0.4rem 0.8rem; margin-top:0.5rem; }
        img { max-width:100%; border:1px solid #333; background:#000; display:block; }
        .row { margin:0.3rem 0; }
        #metrics { font-size:0.9rem; margin-top:1rem; line-height:1.2; }
        #metrics span { display:inline-block; min-width:140px; }
        @media (max-width:1000px){ .video-panel, .controls-panel { max-width:100%; flex:1 1 100%; } }
    </style>
</head>
<body>
    <div class=\"layout\">
        <div class=\"video-panel\">
            <h2>Live Stream</h2>
            <img id=\"stream\" src=\"/stream.mjpg\" />
        </div>
        <div class=\"controls-panel\">
            <h2>Camera Settings</h2>
            <form id=\"settingsForm\" onsubmit=\"applySettings(event)\">
                <div class=\"row\">
                    <label for=\"exposure\">Exposure</label>
                    <input type=\"number\" step=\"0.1\" id=\"exposure\" name=\"exposure\" value=\"0\">
                </div>
                <div class=\"row\">
                    <label for=\"gain\">Gain</label>
                    <input type=\"number\" step=\"0.5\" id=\"gain\" name=\"gain\" value=\"0\">
                </div>
                <button type=\"submit\">Apply</button>
            </form>
            <h2>Video Config</h2>
            <form id=\"videoForm\" onsubmit=\"applyVideo(event)\">
                <div class=\"row\">
                    <label for=\"resolution\">Resolution</label>
                    <select id=\"resolution\" name=\"resolution\"></select>
                </div>
                <div class=\"row\">
                    <label for=\"fps\">FPS</label>
                    <select id=\"fps\" name=\"fps\">
                        <option>15</option>
                        <option>24</option>
                        <option selected>30</option>
                        <option>45</option>
                        <option>60</option>
                    </select>
                </div>
                <button type=\"submit\">Apply Video</button>
            </form>
            <p id=\"status\">Idle</p>
            <h2>Metrics</h2>
            <div id=\"metrics\">\n                <div><span>Frames:</span><span id=\"m_frames\">0</span> <span>Cap FPS(avg):</span><span id=\"m_fps\">0</span></div>\n                <div><span>Cap FPS(inst):</span><span id=\"m_fps_inst\">0</span> <span>Served FPS:</span><span id=\"m_served_fps\">0</span></div>\n                <div><span>Acquire ms:</span><span id=\"m_acq\">0</span> <span>Process ms:</span><span id=\"m_proc\">0</span> <span>Encode ms:</span><span id=\"m_enc\">0</span></div>\n                <div><span>Interval ms:</span><span id=\"m_int\">0</span></div>\n            </div>
        </div>
    </div>
<script>
const commonRes = ["640x480","800x600","1024x768","1280x720","1280x800","1280x960","1920x1080"];
const resSel = document.getElementById('resolution');
commonRes.forEach(r => { const o=document.createElement('option'); o.text=r; o.value=r; resSel.appendChild(o); });

async function applySettings(e){
    e.preventDefault();
    const exposure = parseFloat(document.getElementById('exposure').value);
    const gain = parseFloat(document.getElementById('gain').value);
    const r = await fetch('/settings', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({exposure, gain})
    });
    const data = await r.json();
    document.getElementById('status').textContent = data.message || 'Updated';
}

async function applyVideo(e){
    e.preventDefault();
    const resolution = document.getElementById('resolution').value;
    const fps = document.getElementById('fps').value;
    const r = await fetch('/video_settings', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({resolution, fps: parseInt(fps,10)})
    });
    const data = await r.json();
    document.getElementById('status').textContent = data.message || 'Video updated';
    if (data.applied_resolution) {
        document.getElementById('resolution').value = data.applied_resolution;
    }
    if (data.applied_fps) {
        document.getElementById('fps').value = data.applied_fps;
    }
}

async function initVideoForm(){
    try {
        const r = await fetch('/video_settings');
        const d = await r.json();
        if(d.resolution) document.getElementById('resolution').value = d.resolution;
        if(d.fps) document.getElementById('fps').value = d.fps;
    } catch(e) { console.log(e); }
}

initVideoForm();

async function pollMetrics(){
    try {
        const r = await fetch('/metrics');
        const d = await r.json();
        if(d.frames_total !== undefined){
            document.getElementById('m_frames').textContent = d.frames_total;
            if(d.fps !== undefined) document.getElementById('m_fps').textContent = d.fps.toFixed(1);
            if(d.fps_inst !== undefined) document.getElementById('m_fps_inst').textContent = d.fps_inst.toFixed(1);
            if(d.served_fps !== undefined) document.getElementById('m_served_fps').textContent = d.served_fps.toFixed(1);
            document.getElementById('m_acq').textContent = d.acquire_ms.toFixed(2);
            document.getElementById('m_proc').textContent = d.process_ms.toFixed(2);
            document.getElementById('m_enc').textContent = d.encode_ms.toFixed(2);
            document.getElementById('m_int').textContent = d.frame_interval_ms.toFixed(2);
        }
    } catch(e){ /* ignore */ }
    setTimeout(pollMetrics, 1000);
}
pollMetrics();
</script>
</body>
</html>
"""


class CameraThread:
    def __init__(self, device=0, width=None, height=None, fps=None, jpeg_quality=80, downscale=1, frame_skip=0, roi=None, flip_mode='none', no_buffer_mode=False, flush_reads=0):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.cap = None
        self.frame_lock = threading.Lock()
        self.latest_jpeg = None
        self.running = False
        self.thread = None
        self.exposure = None
        self.gain = None
        self.jpeg_quality = int(jpeg_quality) if jpeg_quality else 80
        self.downscale = max(1, int(downscale) if downscale else 1)
        self.frame_skip = max(0, int(frame_skip) if frame_skip else 0)
        self.roi = roi  # (x,y,w,h) or None
        self._frame_counter = 0
        self.flip_mode = flip_mode  # none|h|v|hv
        self.no_buffer_mode = no_buffer_mode
        self.flush_reads = max(0, int(flush_reads))  # number of extra frames to drop each capture in no-buffer mode
        self._metrics = {
            'frames_total': 0,
            'served_frames_total': 0,
            'acquire_ms': 0.0,
            'process_ms': 0.0,
            'encode_ms': 0.0,
            'frame_interval_ms': 0.0,
            'last_timestamp': None,
            'last_served_timestamp': None,
            'fps': 0.0,
            'fps_inst': 0.0,
            'served_fps': 0.0,
        }

    def start(self):
        if cv2 is None:
            raise RuntimeError("OpenCV backend selected but opencv-python not installed")
        if self.running:
            return
        self.cap = cv2.VideoCapture(self.device)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera (OpenCV) device={self.device}")
        if self.width:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if self.fps:
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.running = True
        if not self.no_buffer_mode:
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def _loop(self):
        target_delay = 1 / (self.fps or 30)
        while self.running:
            t_loop_start = time.monotonic()
            t0 = time.monotonic()
            ok, frame = self.cap.read() if self.cap else (False, None)
            t1 = time.monotonic()
            if not ok:
                time.sleep(0.05)
                continue
            # Optional ROI crop
            if self.roi:
                x, y, w, h = self.roi
                h_img, w_img = frame.shape[:2]
                if 0 <= x < w_img and 0 <= y < h_img:
                    frame = frame[y:min(y+h, h_img), x:min(x+w, w_img)]
            # Optional flip
            if self.flip_mode and self.flip_mode != 'none':
                if self.flip_mode == 'h':
                    frame = cv2.flip(frame, 1)
                elif self.flip_mode == 'v':
                    frame = cv2.flip(frame, 0)
                elif self.flip_mode in ('hv','vh','both'):
                    frame = cv2.flip(frame, -1)
            # Optional downscale (integer factor)
            t2 = time.monotonic()
            if self.downscale > 1:
                frame = cv2.resize(frame, (frame.shape[1]//self.downscale, frame.shape[0]//self.downscale), interpolation=cv2.INTER_AREA)
            # Frame skipping
            self._frame_counter += 1
            if self.frame_skip and (self._frame_counter % (self.frame_skip + 1)) != 1:
                # Update interval metric even when skipping
                t_now = time.monotonic()
                if self._metrics['last_timestamp'] is not None:
                    self._metrics['frame_interval_ms'] = (t_now - self._metrics['last_timestamp']) * 1000.0
                self._metrics['last_timestamp'] = t_now
                time.sleep(target_delay)
                continue
            t3 = time.monotonic()
            ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
            t4 = time.monotonic()
            if ret:
                with self.frame_lock:
                    self.latest_jpeg = buf.tobytes()
            # Metrics update
            m = self._metrics
            m['frames_total'] += 1
            m['acquire_ms'] = (t1 - t0) * 1000.0
            m['process_ms'] = (t3 - t2) * 1000.0
            m['encode_ms'] = (t4 - t3) * 1000.0
            if m['last_timestamp'] is not None:
                m['frame_interval_ms'] = (t_loop_start - m['last_timestamp']) * 1000.0
                # Simple EMA for fps based on interval
                interval = (t_loop_start - m['last_timestamp'])
                if interval > 0:
                    inst_fps = 1.0 / interval
                    m['fps_inst'] = inst_fps
                    m['fps'] = 0.85 * m['fps'] + 0.15 * inst_fps if m['fps'] else inst_fps
            m['last_timestamp'] = t_loop_start
            time.sleep(target_delay)

    def read_and_encode(self):
        """Direct capture path for no-buffer mode; returns latest JPEG bytes or None."""
        if not self.no_buffer_mode or self.cap is None:
            return None
        t_loop_start = time.monotonic()
        t0 = time.monotonic()
        ok, frame = self.cap.read()
        if self.flush_reads and self.cap is not None:
            for _ in range(self.flush_reads):
                ok2, f2 = self.cap.read()
                if not ok2:
                    break
                ok, frame = ok2, f2
        t1 = time.monotonic()
        if not ok:
            return None
        # ROI
        if self.roi:
            x, y, w, h = self.roi
            h_img, w_img = frame.shape[:2]
            if 0 <= x < w_img and 0 <= y < h_img:
                frame = frame[y:min(y+h, h_img), x:min(x+w, w_img)]
        # Flip
        if self.flip_mode and self.flip_mode != 'none':
            if self.flip_mode == 'h':
                frame = cv2.flip(frame, 1)
            elif self.flip_mode == 'v':
                frame = cv2.flip(frame, 0)
            elif self.flip_mode in ('hv','vh','both'):
                frame = cv2.flip(frame, -1)
        t2 = time.monotonic()
        if self.downscale > 1:
            frame = cv2.resize(frame, (frame.shape[1]//self.downscale, frame.shape[0]//self.downscale), interpolation=cv2.INTER_AREA)
        t3 = time.monotonic()
        ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        t4 = time.monotonic()
        if not ret:
            return None
        # Update metrics (reuse structure)
        m = self._metrics
        m['frames_total'] += 1
        m['acquire_ms'] = (t1 - t0) * 1000.0
        m['process_ms'] = (t3 - t2) * 1000.0
        m['encode_ms'] = (t4 - t3) * 1000.0
        if m['last_timestamp'] is not None:
            interval = (t_loop_start - m['last_timestamp'])
            m['frame_interval_ms'] = interval * 1000.0
            if interval > 0:
                inst_fps = 1.0 / interval
                m['fps_inst'] = inst_fps
                m['fps'] = 0.85 * m['fps'] + 0.15 * inst_fps if m['fps'] else inst_fps
        m['last_timestamp'] = t_loop_start
        return buf.tobytes()

    def get_frame(self):
        with self.frame_lock:
            return self.latest_jpeg

    def set_exposure(self, value):
        if self.cap is not None:
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
            self.cap.set(cv2.CAP_PROP_EXPOSURE, float(value))
        self.exposure = value

    def set_gain(self, value):
        if self.cap is not None:
            self.cap.set(cv2.CAP_PROP_GAIN, float(value))
        self.gain = value

    def stop(self):
        self.running = False
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.thread = None

    def reconfigure(self, width=None, height=None, fps=None):
        # Stop, apply new settings, restart to ensure hardware picks them up
        was_running = self.running
        if was_running:
            self.stop()
        if width: self.width = width
        if height: self.height = height
        if fps: self.fps = fps
        if was_running:
            self.start()

class DahengCameraThread:
    """Daheng industrial camera acquisition thread.

    Provides a similar interface to CameraThread so the rest of the web app can stay agnostic.
    Exposure is expected in microseconds (Daheng uses ExposureTime in µs). Gain is in dB.
    """

    def __init__(self, index=1, width=None, height=None, fps=None, serial=None, jpeg_quality=80, downscale=1, frame_skip=0, roi=None, flip_mode='none', no_buffer_mode=False, flush_reads=0):
        if DeviceManager is None:
            raise RuntimeError("gxipy (Daheng SDK) not installed; install vendor SDK and python package")
        self.index = index
        self.serial = serial
        self.width = width
        self.height = height
        self.fps = fps
        self.dm = None
        self.dev = None
        self.running = False
        self.frame_lock = threading.Lock()
        self.latest_jpeg = None
        self.thread = None
        self.exposure = None  # microseconds
        self.gain = None  # dB
        self.jpeg_quality = int(jpeg_quality) if jpeg_quality else 80
        self.downscale = max(1, int(downscale) if downscale else 1)
        self.frame_skip = max(0, int(frame_skip) if frame_skip else 0)
        self.roi = roi
        self._frame_counter = 0
        self.flip_mode = flip_mode  # none|h|v|hv
        self.no_buffer_mode = no_buffer_mode
        self.flush_reads = max(0, int(flush_reads))
        self._metrics = {
            'frames_total': 0,
            'served_frames_total': 0,
            'acquire_ms': 0.0,
            'process_ms': 0.0,
            'encode_ms': 0.0,
            'frame_interval_ms': 0.0,
            'last_timestamp': None,
            'last_served_timestamp': None,
            'fps': 0.0,
            'fps_inst': 0.0,
            'served_fps': 0.0,
        }

    def start(self):
        self.dm = DeviceManager()
        num, info_list = self.dm.update_device_list()
        if num == 0:
            raise RuntimeError("No Daheng cameras detected")
        if self.serial:
            # Attempt open by serial
            try:
                self.dev = self.dm.open_device_by_sn(self.serial)
            except Exception:
                raise RuntimeError(f"Failed to open Daheng camera by serial {self.serial}")
        else:
            if self.index < 1 or self.index > num:
                raise RuntimeError(f"Daheng camera index {self.index} out of range (found {num})")
            self.dev = self.dm.open_device_by_index(self.index)
        # Turn off auto features to allow manual control
        try:
            if hasattr(self.dev, 'ExposureAuto'):
                self.dev.ExposureAuto.set(0)  # Off
            if hasattr(self.dev, 'GainAuto'):
                self.dev.GainAuto.set(0)  # Off
        except Exception:
            pass
        # Width/height/fps adjustments (guarded)
        try:
            if self.width and hasattr(self.dev, 'Width'):
                self.dev.Width.set(self.width)
            if self.height and hasattr(self.dev, 'Height'):
                self.dev.Height.set(self.height)
            if self.fps and hasattr(self.dev, 'AcquisitionFrameRateEnable') and hasattr(self.dev, 'AcquisitionFrameRate'):
                try:
                    self.dev.AcquisitionFrameRateEnable.set(True)
                    self.dev.AcquisitionFrameRate.set(float(self.fps))
                except Exception:
                    pass
        except Exception:
            pass
        # Start stream
        self.dev.stream_on()
        self.running = True
        if not self.no_buffer_mode:
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def read_and_encode(self):
        if not self.no_buffer_mode or self.dev is None:
            return None
        ds = self.dev.data_stream[0]
        t_loop_start = time.monotonic()
        t0 = time.monotonic()
        raw_image = ds.get_image(timeout=100)
    # (Daheng SDK typically delivers most recent frame already; flush not applied here)
        if raw_image is None:
            return None
        rgb_image = raw_image.convert('RGB')
        frame = rgb_image.get_numpy_array()
        if frame is None:
            return None
        t1 = time.monotonic()
        if self.roi:
            x, y, w, h = self.roi
            h_img, w_img = frame.shape[:2]
            if 0 <= x < w_img and 0 <= y < h_img:
                frame = frame[y:min(y+h, h_img), x:min(x+w, w_img)]
        if self.flip_mode and self.flip_mode != 'none' and cv2 is not None:
            if self.flip_mode == 'h':
                frame = cv2.flip(frame, 1)
            elif self.flip_mode == 'v':
                frame = cv2.flip(frame, 0)
            elif self.flip_mode in ('hv','vh','both'):
                frame = cv2.flip(frame, -1)
        t2 = time.monotonic()
        if self.downscale > 1:
            frame = cv2.resize(frame, (frame.shape[1]//self.downscale, frame.shape[0]//self.downscale), interpolation=cv2.INTER_AREA)
        t3 = time.monotonic()
        if cv2 is None:
            return None
        ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        t4 = time.monotonic()
        if not ret:
            return None
        m = self._metrics
        m['frames_total'] += 1
        m['acquire_ms'] = (t1 - t0) * 1000.0
        m['process_ms'] = (t3 - t2) * 1000.0
        m['encode_ms'] = (t4 - t3) * 1000.0
        if m['last_timestamp'] is not None:
            interval = (t_loop_start - m['last_timestamp'])
            m['frame_interval_ms'] = interval * 1000.0
            if interval > 0:
                inst_fps = 1.0 / interval
                m['fps_inst'] = inst_fps
                m['fps'] = 0.85 * m['fps'] + 0.15 * inst_fps if m['fps'] else inst_fps
        m['last_timestamp'] = t_loop_start
        return buf.tobytes()

    def _loop(self):
        target_delay = 1 / (self.fps or 30)
        ds = self.dev.data_stream[0] if self.dev else None
        while self.running and ds is not None:
            try:
                t_loop_start = time.monotonic()
                t0 = time.monotonic()
                raw_image = ds.get_image(timeout=100)
                if raw_image is None:
                    time.sleep(0.005)
                    continue
                rgb_image = raw_image.convert('RGB')
                frame = rgb_image.get_numpy_array()
                if frame is None:
                    continue
                t1 = time.monotonic()
                # Optional ROI
                if self.roi:
                    x, y, w, h = self.roi
                    h_img, w_img = frame.shape[:2]
                    if 0 <= x < w_img and 0 <= y < h_img:
                        frame = frame[y:min(y+h, h_img), x:min(x+w, w_img)]
                t2 = time.monotonic()
                if self.flip_mode and self.flip_mode != 'none' and cv2 is not None:
                    if self.flip_mode == 'h':
                        frame = cv2.flip(frame, 1)
                    elif self.flip_mode == 'v':
                        frame = cv2.flip(frame, 0)
                    elif self.flip_mode in ('hv','vh','both'):
                        frame = cv2.flip(frame, -1)
                if self.downscale > 1:
                    frame = cv2.resize(frame, (frame.shape[1]//self.downscale, frame.shape[0]//self.downscale), interpolation=cv2.INTER_AREA)
                self._frame_counter += 1
                if self.frame_skip and (self._frame_counter % (self.frame_skip + 1)) != 1:
                    t_now = time.monotonic()
                    m = self._metrics
                    if m['last_timestamp'] is not None:
                        m['frame_interval_ms'] = (t_now - m['last_timestamp']) * 1000.0
                    m['last_timestamp'] = t_now
                    time.sleep(target_delay)
                    continue
                t3 = time.monotonic()
                if cv2 is not None:
                    ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                else:
                    # Fallback simple manual JPEG via Pillow if desired (not implemented); skip if no cv2
                    ret, buf = False, None
                t4 = time.monotonic()
                if ret:
                    with self.frame_lock:
                        self.latest_jpeg = buf.tobytes()
                # Metrics update
                m = self._metrics
                m['frames_total'] += 1
                m['acquire_ms'] = (t1 - t0) * 1000.0
                m['process_ms'] = (t3 - t2) * 1000.0
                m['encode_ms'] = (t4 - t3) * 1000.0
                if m['last_timestamp'] is not None:
                    m['frame_interval_ms'] = (t_loop_start - m['last_timestamp']) * 1000.0
                    interval = (t_loop_start - m['last_timestamp'])
                    if interval > 0:
                        inst_fps = 1.0 / interval
                        m['fps_inst'] = inst_fps
                        m['fps'] = 0.85 * m['fps'] + 0.15 * inst_fps if m['fps'] else inst_fps
                m['last_timestamp'] = t_loop_start
            except Exception:
                time.sleep(0.01)
            time.sleep(target_delay)

    def get_frame(self):
        with self.frame_lock:
            return self.latest_jpeg

    def set_exposure(self, value):
        # Expect value in microseconds for Daheng; user might give milliseconds so adapt if small
        if value < 1:  # treat as milliseconds
            value_us = value * 1000.0
        elif value < 100:  # ambiguous range; assume ms if under 100
            value_us = value * 1000.0
        else:
            value_us = value
        if self.dev is not None and hasattr(self.dev, 'ExposureTime'):
            try:
                self.dev.ExposureTime.set(float(value_us))
            except Exception:
                pass
        self.exposure = value_us

    def set_gain(self, value: float):
        if self.dev is not None and hasattr(self.dev, 'Gain'):
            try:
                self.dev.Gain.set(float(value))
            except Exception:
                pass
        self.gain = value

    def stop(self):
        self.running = False
        try:
            if self.dev:
                self.dev.stream_off()
                self.dev.close_device()
        finally:
            self.dev = None
        self.thread = None

    def reconfigure(self, width=None, height=None, fps=None):
        was_running = self.running
        if was_running:
            self.stop()
        if width: self.width = width
        if height: self.height = height
        if fps: self.fps = fps
        if was_running:
            self.start()

    # (Removed duplicate OpenCV methods that belonged to CameraThread)


def load_config():
    parser = configparser.ConfigParser()
    cfg_path = Path(__file__).parent / CONFIG_FILENAME
    if cfg_path.exists():
        parser.read(cfg_path)
    return parser


def create_app() -> Flask:
    cfg = load_config()
    cam_section = cfg['camera'] if 'camera' in cfg else {}
    backend = cam_section.get('backend', 'opencv').lower()
    resolution = cam_section.get('resolution', '640x480')
    try:
        w_s, h_s = resolution.lower().split('x')
        w_i, h_i = int(w_s), int(h_s)
    except Exception:
        w_i, h_i = 640, 480
    def _clean_int(key, default):
        raw = cam_section.get(key)
        if not raw:
            return default
        raw = raw.split('#', 1)[0].strip()
        if raw == '':
            return default
        try:
            return int(raw)
        except Exception:
            return default
    fps = _clean_int('fps', 0) or None
    jpeg_quality = _clean_int('jpeg_quality', 80)
    downscale = max(1, _clean_int('downscale', 1))
    frame_skip = max(0, _clean_int('frame_skip', 0))
    flip_mode = cam_section.get('flip_mode', 'none').split('#',1)[0].strip().lower() if cam_section.get('flip_mode') else 'none'
    no_buffer_mode = bool(_clean_int('no_buffer', 0))  # 1 to disable background buffering/thread
    flush_reads = _clean_int('flush_reads', 0)
    # ROI specified as x,y,w,h
    roi = None
    if cam_section.get('roi'):
        try:
            parts = [int(p.split('#',1)[0].strip()) for p in cam_section.get('roi').split(',')]
            if len(parts) == 4:
                roi = tuple(parts)
        except Exception:
            roi = None
    def _clean_float(key):
        raw = cam_section.get(key)
        if not raw:
            return None
        raw = raw.split('#', 1)[0].strip()
        if raw == '':
            return None
        try:
            return float(raw)
        except Exception:
            return None
    exposure_us_cfg = _clean_float('exposure_us')
    gain_db_cfg = _clean_float('gain_db')

    cam: CameraThread | DahengCameraThread
    if backend.startswith('daheng'):
        # Optional index (1-based) for Daheng backend; default 1
        try:
            dh_index = int(cam_section.get('index', '1'))
        except ValueError:
            dh_index = 1
        serial_raw = cam_section.get('serial')
        serial = None
        if serial_raw:
            # Strip inline comment portion and whitespace
            sr = serial_raw.split('#', 1)[0].strip()
            if sr:
                serial = sr
        cam = DahengCameraThread(index=dh_index, serial=serial, width=w_i, height=h_i, fps=fps, jpeg_quality=jpeg_quality, downscale=downscale, frame_skip=frame_skip, roi=roi, flip_mode=flip_mode, no_buffer_mode=no_buffer_mode, flush_reads=flush_reads)
    else:
        device = cam_section.get('device', '/dev/video0')
        device_index: int | str = device
        if isinstance(device, str) and device.startswith('/dev/video'):
            try:
                device_index = int(device.replace('/dev/video', ''))
            except ValueError:
                pass
        cam = CameraThread(device=device_index, width=w_i, height=h_i, fps=fps, jpeg_quality=jpeg_quality, downscale=downscale, frame_skip=frame_skip, roi=roi, flip_mode=flip_mode, no_buffer_mode=no_buffer_mode, flush_reads=flush_reads)

    cam.start()
    # Apply initial exposure/gain if provided
    try:
        if exposure_us_cfg:
            val = float(exposure_us_cfg)
            cam.set_exposure(val if backend.startswith('daheng') else val/1000.0)  # crude adapt
        if gain_db_cfg:
            cam.set_gain(float(gain_db_cfg))
    except Exception:
        pass

    app = Flask(__name__)

    @app.route('/')
    def index():
        return render_template_string(HTML_PAGE)

    @app.route('/stream.mjpg')
    def stream():
        def gen():
            # MJPEG generator
            while True:
                if getattr(cam, 'no_buffer_mode', False):
                    frame = cam.read_and_encode()
                    if frame is None:
                        time.sleep(0.001)
                        continue
                else:
                    frame = cam.get_frame()
                    if frame is None:
                        time.sleep(0.05)
                        continue
                # Served frame metrics
                m = getattr(cam, '_metrics', None)
                if m is not None:
                    now = time.monotonic()
                    m['served_frames_total'] = m.get('served_frames_total', 0) + 1
                    if m.get('last_served_timestamp') is not None:
                        interval = now - m['last_served_timestamp']
                        if interval > 0:
                            inst_served = 1.0 / interval
                            m['served_fps'] = 0.85 * m.get('served_fps', 0.0) + 0.15 * inst_served if m.get('served_fps', 0.0) else inst_served
                    m['last_served_timestamp'] = now
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
        resp = Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp

    @app.route('/settings', methods=['GET', 'POST'])
    def settings():
        if request.method == 'POST':
            data = request.get_json(silent=True) or request.form
            resp = {}
            if 'exposure' in data:
                try:
                    exp = float(data['exposure'])
                    cam.set_exposure(exp)
                    resp['exposure'] = exp
                except Exception as e:  # pragma: no cover
                    resp['exposure_error'] = str(e)
            if 'gain' in data:
                try:
                    g = float(data['gain'])
                    cam.set_gain(g)
                    resp['gain'] = g
                except Exception as e:  # pragma: no cover
                    resp['gain_error'] = str(e)
            if not resp:
                resp['message'] = 'No settings updated'
            else:
                resp['message'] = 'Settings updated'
            return jsonify(resp)
        return jsonify({"exposure": cam.exposure, "gain": cam.gain})

    @app.route('/health')
    def health():
        return {"status": "ok", "has_frame": cam.get_frame() is not None}

    @app.route('/video_settings', methods=['GET', 'POST'])
    def video_settings():
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            res = data.get('resolution')
            fps_new = data.get('fps')
            flip_new = data.get('flip_mode')
            response = {}
            try:
                w_new = h_new = None
                if res:
                    parts = res.lower().split('x')
                    if len(parts)==2:
                        w_new, h_new = int(parts[0]), int(parts[1])
                # Apply flip (does not require full restart, but keep simple)
                if flip_new is not None:
                    fv = str(flip_new).lower()
                    if fv in ('none','h','v','hv','vh','both'):
                        cam.flip_mode = fv
                # Perform full reconfigure if resolution or fps change requested
                if w_new or h_new or fps_new:
                    cam.reconfigure(width=w_new, height=h_new, fps=int(fps_new) if fps_new else None)
                response['applied_resolution'] = f"{cam.width}x{cam.height}" if cam.width and cam.height else None
                response['applied_fps'] = cam.fps
                response['flip_mode'] = cam.flip_mode
                response['message'] = 'Video settings applied'
            except Exception as e:
                response = {'error': str(e), 'message': 'Failed to apply video settings'}
            return jsonify(response)
        return jsonify({'resolution': f"{cam.width}x{cam.height}" if cam.width and cam.height else None, 'fps': cam.fps, 'flip_mode': getattr(cam,'flip_mode','none')})

    @app.route('/metrics')
    def metrics():
        m = getattr(cam, '_metrics', None)
        if not m:
            return jsonify({'error': 'metrics unavailable'})
        out = {k: v for k, v in m.items() if k not in ('last_timestamp','last_served_timestamp')}
        return jsonify(out)

    return app


def main(host: str = '0.0.0.0', port: int = 5001):  # pragma: no cover
    if cv2 is None:
        print("ERROR: opencv-python not installed. Install with: pip install opencv-python")
        return
    app = create_app()
    print(f"Camera web UI running on http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    app.run(host=host, port=port, threaded=True)


if __name__ == '__main__':  # pragma: no cover
    main()
