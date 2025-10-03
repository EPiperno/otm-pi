"""Camera control GUI.

Features (initial version):
 - Live video preview (start/stop)
 - Exposure and gain sliders (attempts to set via OpenCV properties)
 - Reads default camera settings from config.txt [camera] section if available
 - Designed for Raspberry Pi / Linux with a USB or CSI camera accessible via OpenCV

Next planned enhancements (future steps):
 - Object tracking overlay
 - Auto-centering by commanding Z / THETA motors
 - Recording snapshots or video

Run:
    python camera_gui.py

Dependencies:
    sudo apt-get install python3-pil python3-opencv   (or pip install opencv-python pillow)
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import configparser
from pathlib import Path
from typing import Optional

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore

try:
    from PIL import Image, ImageTk  # type: ignore
except ImportError:  # pragma: no cover
    Image = None  # type: ignore
    ImageTk = None  # type: ignore


CONFIG_FILENAME = "config.txt"


class CameraController:
    def __init__(self, device: int | str = 0, width: int | None = None, height: int | None = None, fps: int | None = None):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.cap = None
        self.lock = threading.Lock()
        self.running = False
        self.last_frame = None

    def open(self) -> bool:
        if cv2 is None:
            return False
        self.cap = cv2.VideoCapture(self.device)
        if not self.cap.isOpened():
            return False
        if self.width:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if self.fps:
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        return True

    def set_exposure(self, value: float):  # value expected in milliseconds or driver-specific units
        if self.cap is not None:
            # Many UVC cams require exposure to be set to a negative to enable manual; we attempt direct.
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)  # 1 = manual for some backends
            self.cap.set(cv2.CAP_PROP_EXPOSURE, float(value))

    def set_gain(self, value: float):
        if self.cap is not None:
            self.cap.set(cv2.CAP_PROP_GAIN, float(value))

    def read(self):
        if self.cap is None:
            return None
        ok, frame = self.cap.read()
        if not ok:
            return None
        return frame

    def close(self):
        with self.lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None


class CameraGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Camera Control")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.resizable(False, False)

        self.cfg = self._load_config()
        cam_section = self.cfg['camera'] if 'camera' in self.cfg else {}
        device = cam_section.get('device', '/dev/video0')
        # If device is a path, derive numeric index if possible
        device_index: int | str = device
        if isinstance(device, str) and device.startswith('/dev/video'):
            try:
                device_index = int(device.replace('/dev/video', ''))
            except ValueError:
                pass
        resolution = cam_section.get('resolution', '640x480')
        try:
            w_s, h_s = resolution.lower().split('x')
            w_i, h_i = int(w_s), int(h_s)
        except Exception:
            w_i, h_i = 640, 480
        fps = None
        try:
            fps = int(cam_section.get('fps', '0')) or None
        except ValueError:
            fps = None

        self.camera = CameraController(device=device_index, width=w_i, height=h_i, fps=fps)

        # UI elements
        self.preview_label = tk.Label(self, text="(No video)", width=60, height=20, bg="black", fg="white")
        self.preview_label.grid(row=0, column=0, columnspan=4, padx=8, pady=8)

        self.btn_toggle = ttk.Button(self, text="Start Preview", command=self.toggle_stream)
        self.btn_toggle.grid(row=1, column=0, pady=4, padx=4, sticky="ew")

    # Exposure control
        self.exposure_var = tk.DoubleVar(value=0.0)
        ttk.Label(self, text="Exposure").grid(row=1, column=1)
        self.exposure_scale = ttk.Scale(self, from_=-10, to=10, orient=tk.HORIZONTAL, variable=self.exposure_var, command=self.on_exposure_change)
        self.exposure_scale.grid(row=1, column=2, padx=4, sticky="ew")
        self.btn_exp_apply = ttk.Button(self, text="Apply", command=lambda: self.on_exposure_change(None, apply_click=True))
        self.btn_exp_apply.grid(row=1, column=3, padx=4)

        # Gain control
        self.gain_var = tk.DoubleVar(value=0.0)
        ttk.Label(self, text="Gain").grid(row=2, column=1)
        self.gain_scale = ttk.Scale(self, from_=0, to=64, orient=tk.HORIZONTAL, variable=self.gain_var, command=self.on_gain_change)
        self.gain_scale.grid(row=2, column=2, padx=4, sticky="ew")
        self.btn_gain_apply = ttk.Button(self, text="Apply", command=lambda: self.on_gain_change(None, apply_click=True))
        self.btn_gain_apply.grid(row=2, column=3, padx=4)

        # Resolution & FPS selectors
        ttk.Label(self, text="Resolution").grid(row=3, column=0, padx=4, sticky="e")
        self.common_resolutions = [
            "640x480", "800x600", "1024x768", "1280x720",
            "1280x800", "1280x960", "1920x1080"
        ]
        self.resolution_var = tk.StringVar(value=f"{w_i}x{h_i}")
        self.res_select = ttk.Combobox(self, textvariable=self.resolution_var, values=self.common_resolutions, state="readonly", width=12)
        self.res_select.grid(row=3, column=1, padx=4, sticky="ew")

        ttk.Label(self, text="FPS").grid(row=3, column=2, padx=4, sticky="e")
        self.common_fps = ["15", "24", "30", "45", "60"]
        self.fps_var = tk.StringVar(value=str(fps or 30))
        self.fps_select = ttk.Combobox(self, textvariable=self.fps_var, values=self.common_fps, state="readonly", width=6)
        self.fps_select.grid(row=3, column=3, padx=4, sticky="ew")

        self.btn_video_apply = ttk.Button(self, text="Apply Video Settings", command=self.apply_video_settings)
        self.btn_video_apply.grid(row=4, column=0, columnspan=4, pady=(4,2), padx=4, sticky="ew")

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(self, textvariable=self.status_var).grid(row=5, column=0, columnspan=4, pady=6)

        for col in range(4):
            self.grid_columnconfigure(col, weight=1)

        self._stop_event = threading.Event()
        self._frame_thread: Optional[threading.Thread] = None
        self._image_cache = None  # keep reference to avoid GC

    def _load_config(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        cfg_path = Path(__file__).parent / CONFIG_FILENAME
        if cfg_path.exists():
            parser.read(cfg_path)
        return parser

    def toggle_stream(self):
        if not self.camera.running:
            if not self.camera.open():
                messagebox.showerror("Camera", "Failed to open camera device")
                return
            self.camera.running = True
            self._stop_event.clear()
            self.btn_toggle.configure(text="Stop Preview")
            self.status_var.set("Streaming")
            self._frame_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._frame_thread.start()
        else:
            self._stop_stream()

    def _stop_stream(self):
        self._stop_event.set()
        self.camera.running = False
        self.btn_toggle.configure(text="Start Preview")
        self.status_var.set("Stopped")
        self.camera.close()

    def on_exposure_change(self, _value, apply_click: bool = False):
        # For some cameras continuous updates cause flicker; only apply on button if needed.
        if apply_click or not self.camera.running:
            try:
                self.camera.set_exposure(self.exposure_var.get())
                self.status_var.set(f"Exposure set: {self.exposure_var.get():.2f}")
            except Exception as e:
                self.status_var.set(f"Exposure error: {e}")

    def on_gain_change(self, _value, apply_click: bool = False):
        if apply_click or not self.camera.running:
            try:
                self.camera.set_gain(self.gain_var.get())
                self.status_var.set(f"Gain set: {self.gain_var.get():.1f}")
            except Exception as e:
                self.status_var.set(f"Gain error: {e}")

    def _capture_loop(self):
        while not self._stop_event.is_set():
            frame = self.camera.read()
            if frame is None:
                time.sleep(0.05)
                continue
            # Convert BGR -> RGB for display
            if Image is not None:
                try:
                    frame_rgb = frame[:, :, ::-1]
                    img = Image.fromarray(frame_rgb)
                    # Optionally scale down if very large
                    if img.width > 960:
                        img = img.resize((960, int(img.height * 960 / img.width)))
                    tk_img = ImageTk.PhotoImage(img)
                    # schedule update on main thread
                    self.after(0, self._update_preview, tk_img)
                except Exception as e:  # pragma: no cover
                    self.status_var.set(f"Frame error: {e}")
            else:
                # Fallback: show placeholder text
                self.after(0, self.preview_label.config, {"text": "PIL not installed"})
            # Dynamic sleep based on requested FPS (fallback 30)
            target_fps = self.camera.fps or 30
            delay = 1.0 / max(1, target_fps)
            # Slightly under-sleep to compensate GUI overhead
            time.sleep(delay * 0.9)

    def apply_video_settings(self):
        res_str = self.resolution_var.get().strip().lower()
        try:
            w_s, h_s = res_str.split('x')
            new_w, new_h = int(w_s), int(h_s)
        except Exception:
            messagebox.showerror("Resolution", f"Invalid resolution format: {res_str}")
            return
        try:
            new_fps = int(self.fps_var.get())
        except ValueError:
            messagebox.showerror("FPS", f"Invalid FPS: {self.fps_var.get()}")
            return
        was_running = self.camera.running
        if was_running:
            self._stop_stream()
        # Update camera settings
        self.camera.width = new_w
        self.camera.height = new_h
        self.camera.fps = new_fps
        self.status_var.set(f"Video settings applied: {new_w}x{new_h}@{new_fps}fps")
        if was_running:
            # restart stream automatically
            self.toggle_stream()

    def _update_preview(self, tk_img):
        self._image_cache = tk_img
        self.preview_label.configure(image=tk_img, text="")

    def on_close(self):
        if self.camera.running:
            self._stop_stream()
        self.destroy()


def main():  # pragma: no cover
    # Detect headless environment
    if not os.environ.get("DISPLAY"):
        print("No DISPLAY detected. For headless operation, run: python camera_web.py")
        return
    app = CameraGUI()
    app.mainloop()


if __name__ == "__main__":  # pragma: no cover
    main()
