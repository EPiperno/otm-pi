"""Unified web controller for OTM project.

Responsibilities of this file ONLY:
 - Provide a Flask web application.
 - Serve a simple HTML page containing: live MJPEG camera stream, camera
   setting forms, and motor control forms for Z and THETA.
 - Expose HTTP endpoints to:
     * Get/Set camera exposure & gain.
     * Get/Set camera video settings (resolution, fps, flip_mode).
     * Move Z axis by mm, move THETA by degrees (or optional revolutions),
       using functions imported from run_stepper.

No camera capture implementation or motor low-level logic lives here; those
reside in camera_feed.py and run_stepper.py respectively.

Quick start:
    python otm_controller.py
Then open http://<pi-address>:5000/
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from flask import Flask, Response, request, jsonify, render_template_string

# Import camera abstraction & generator
from camera_feed import create_camera_from_config, mjpeg_frame_generator

# Import motor utilities
from run_stepper import (
    init_motors,
    move_mm,
    move_angle,
    move_revolutions,
    release_all,
    get_motor_settings,
)

# -------------------------- HTML TEMPLATE (No Metrics) -----------------------
PAGE_HTML = """<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='utf-8'/>
<title>OTM Controller</title>
<style>
 body { font-family: sans-serif; background:#111; color:#eee; margin:0; padding:0; }
 header { background:#222; padding:0.8rem 1rem; }
 h1 { margin:0; font-size:1.3rem; }
 main { display:flex; flex-wrap:wrap; gap:1rem; padding:1rem; }
 .panel { background:#1e1e1e; padding:1rem; border-radius:8px; flex:1 1 380px; max-width:48%; }
 .panel.full { max-width:100%; }
 img { max-width:100%; border:1px solid #333; background:#000; display:block; }
 label { display:inline-block; width:110px; }
 input, select { background:#222; color:#eee; border:1px solid #333; padding:0.2rem 0.4rem; }
 button { padding:0.4rem 0.8rem; margin-top:0.4rem; }
 .row { margin:0.3rem 0; }
 #status { margin-top:0.5rem; font-size:0.9rem; color:#9f9; }
 @media (max-width:1000px){ .panel { max-width:100%; flex:1 1 100%; } }
</style>
</head>
<body>
<header><h1>OTM Controller</h1></header>
<main>
  <div class='panel'>
    <h2>Live Camera</h2>
    <img id='stream' src='/stream.mjpg'/>
  </div>
  <div class='panel'>
    <h2>Camera Settings</h2>
    <form id='camSettings' onsubmit='applyCamSettings(event)'>
      <div class='row'><label for='exposure'>Exposure</label><input type='number' step='0.1' id='exposure' name='exposure' value='0'></div>
      <div class='row'><label for='gain'>Gain</label><input type='number' step='0.5' id='gain' name='gain' value='0'></div>
      <button type='submit'>Apply</button>
    </form>
    <h2>Video Config</h2>
    <form id='videoForm' onsubmit='applyVideo(event)'>
      <div class='row'><label for='resolution'>Resolution</label><select id='resolution' name='resolution'></select></div>
      <div class='row'><label for='fps'>FPS</label><select id='fps' name='fps'><option>15</option><option>24</option><option selected>30</option><option>45</option><option>60</option></select></div>
      <div class='row'><label for='flip_mode'>Flip</label><select id='flip_mode' name='flip_mode'><option value='none'>none</option><option value='h'>h</option><option value='v'>v</option><option value='hv'>hv</option></select></div>
      <button type='submit'>Apply Video</button>
    </form>
    <p id='status'>Idle</p>
  </div>
  <div class='panel full'>
    <h2>Motor Control</h2>
    <form id='motorZ' onsubmit='moveZ(event)'>
      <strong>Z Axis</strong>
      <div class='row'><label for='z_mm'>Distance (mm)</label><input type='number' step='0.01' id='z_mm' name='z_mm' value='1.0'></div>
      <div class='row'><label for='z_speed'>Speed (mm/s)</label><input type='number' step='0.01' id='z_speed' name='z_speed' value='0.5'></div>
      <div class='row'><label for='z_style'>Style</label><select id='z_style'><option>SINGLE</option><option>DOUBLE</option><option>INTERLEAVE</option><option>MICROSTEP</option></select></div>
      <div class='row'><label for='z_ramp'>Ramp frac</label><input type='number' step='0.01' id='z_ramp' name='z_ramp' value='0.15'></div>
      <button type='submit'>Move Z</button>
    </form>
    <form id='motorTheta' onsubmit='moveTheta(event)'>
      <strong>THETA Axis</strong>
      <div class='row'><label for='theta_deg'>Angle (deg)</label><input type='number' step='0.1' id='theta_deg' name='theta_deg' value='15'></div>
      <div class='row'><label for='theta_speed'>Speed (deg/s)</label><input type='number' step='0.1' id='theta_speed' name='theta_speed' value='2'></div>
      <div class='row'><label for='theta_style'>Style</label><select id='theta_style'><option>SINGLE</option><option>DOUBLE</option><option>INTERLEAVE</option><option>MICROSTEP</option></select></div>
      <div class='row'><label for='theta_ramp'>Ramp frac</label><input type='number' step='0.01' id='theta_ramp' name='theta_ramp' value='0.15'></div>
      <button type='submit'>Move THETA</button>
    </form>
    <form id='releaseAll' onsubmit='releaseAll(event)'>
      <button type='submit'>Release Motors</button>
    </form>
    <pre id='motor_status'></pre>
  </div>
</main>
<script>
const commonRes = ["640x480","800x600","1024x768","1280x720","1280x800","1280x960","1920x1080"]; const resSel = document.getElementById('resolution');
commonRes.forEach(r => { const o=document.createElement('option'); o.text=r; o.value=r; resSel.appendChild(o); });
async function applyCamSettings(e){ e.preventDefault(); const exposure=parseFloat(exposure.value); const gain=parseFloat(gain.value); const r=await fetch('/camera/settings',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({exposure,gain})}); const d=await r.json(); document.getElementById('status').textContent=d.message||'Updated'; }
async function applyVideo(e){ e.preventDefault(); const resolution=document.getElementById('resolution').value; const fps=parseInt(document.getElementById('fps').value,10); const flip_mode=document.getElementById('flip_mode').value; const r=await fetch('/camera/video',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({resolution,fps,flip_mode})}); const d=await r.json(); document.getElementById('status').textContent=d.message||'Video updated'; if(d.applied_resolution) document.getElementById('resolution').value=d.applied_resolution; if(d.applied_fps) document.getElementById('fps').value=d.applied_fps; if(d.flip_mode) document.getElementById('flip_mode').value=d.flip_mode; }
async function initVideo(){ try{ const r=await fetch('/camera/video'); const d=await r.json(); if(d.resolution) document.getElementById('resolution').value=d.resolution; if(d.fps) document.getElementById('fps').value=d.fps; if(d.flip_mode) document.getElementById('flip_mode').value=d.flip_mode; }catch(e){} } initVideo();
async function moveZ(e){ e.preventDefault(); const dist=parseFloat(document.getElementById('z_mm').value); const speed=parseFloat(document.getElementById('z_speed').value); const style=document.getElementById('z_style').value; const ramp=parseFloat(document.getElementById('z_ramp').value); const r=await fetch('/motor/move_z',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({distance_mm:dist,speed_mm_s:speed,style:style,ramp_fraction:ramp})}); const d=await r.json(); document.getElementById('motor_status').textContent=JSON.stringify(d,null,2); }
async function moveTheta(e){ e.preventDefault(); const ang=parseFloat(document.getElementById('theta_deg').value); const speed=parseFloat(document.getElementById('theta_speed').value); const style=document.getElementById('theta_style').value; const ramp=parseFloat(document.getElementById('theta_ramp').value); const r=await fetch('/motor/move_theta',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({angle_deg:ang,speed_deg_s:speed,style:style,ramp_fraction:ramp})}); const d=await r.json(); document.getElementById('motor_status').textContent=JSON.stringify(d,null,2); }
async function releaseAll(e){ e.preventDefault(); const r=await fetch('/motor/release_all',{method:'POST'}); const d=await r.json(); document.getElementById('motor_status').textContent=JSON.stringify(d,null,2); }
</script>
</body>
</html>"""

# -------------------------- App Factory -------------------------------------

def create_app() -> Flask:
    app = Flask(__name__)

    # Initialize camera & motors (singletons for process)
    camera = create_camera_from_config()
    kit = init_motors()

    # ---------------- Camera Routes ----------------
    @app.route('/')
    def index():
        return render_template_string(PAGE_HTML)

    @app.route('/stream.mjpg')
    def stream():
        return Response(mjpeg_frame_generator(camera), mimetype='multipart/x-mixed-replace; boundary=frame')

    @app.route('/camera/status')
    def camera_status():
        status = {}
        try:
            if hasattr(camera, 'get_status'):
                status = camera.get_status()
            else:
                status = {
                    'running': getattr(camera, 'running', None),
                    'has_frame': camera.get_frame() is not None
                }
            frame = camera.get_frame()
            status['current_frame_size'] = len(frame) if frame else None
        except Exception as e:
            status['error'] = str(e)
        return jsonify(status)

    @app.route('/camera/settings', methods=['GET', 'POST'])
    def camera_settings():
        if request.method == 'POST':
            data = request.get_json(silent=True) or request.form
            resp = {}
            if 'exposure' in data:
                try:
                    exp = float(data['exposure'])
                    camera.set_exposure(exp)
                    resp['exposure'] = exp
                except Exception as e:
                    resp['exposure_error'] = str(e)
            if 'gain' in data:
                try:
                    g = float(data['gain'])
                    camera.set_gain(g)
                    resp['gain'] = g
                except Exception as e:
                    resp['gain_error'] = str(e)
            resp['message'] = 'Settings updated' if ('exposure' in resp or 'gain' in resp) else 'No settings updated'
            return jsonify(resp)
        return jsonify({'exposure': getattr(camera, 'exposure', None), 'gain': getattr(camera, 'gain', None)})

    @app.route('/camera/video', methods=['GET', 'POST'])
    def camera_video():
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
                if flip_new is not None:
                    fv = str(flip_new).lower()
                    if fv in ('none','h','v','hv','vh','both'):
                        camera.flip_mode = fv
                if w_new or h_new or fps_new:
                    camera.reconfigure(width=w_new, height=h_new, fps=int(fps_new) if fps_new else None)
                response['applied_resolution'] = f"{camera.width}x{camera.height}" if camera.width and camera.height else None
                response['applied_fps'] = camera.fps
                response['flip_mode'] = camera.flip_mode
                response['message'] = 'Video settings applied'
            except Exception as e:
                response = {'error': str(e), 'message': 'Failed to apply video settings'}
            return jsonify(response)
        return jsonify({'resolution': f"{camera.width}x{camera.height}" if camera.width and camera.height else None, 'fps': camera.fps, 'flip_mode': getattr(camera,'flip_mode','none')})

    # ---------------- Motor Routes -----------------
    @app.route('/motor/move_z', methods=['POST'])
    def motor_move_z():
        data = request.get_json(silent=True) or {}
        dist = float(data.get('distance_mm', 0))
        speed = data.get('speed_mm_s')
        speed_val = float(speed) if speed is not None else None
        style = data.get('style')
        ramp_fraction = data.get('ramp_fraction')
        ramp_val = float(ramp_fraction) if ramp_fraction is not None else None
        try:
            steps = move_mm(kit, 'Z', dist, style=style, speed_mm_s=speed_val, ramp_fraction=ramp_val)
            return jsonify({'axis':'Z','requested_mm':dist,'steps_taken':steps,'style':style,'speed_mm_s':speed_val,'ramp_fraction':ramp_val})
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/motor/move_theta', methods=['POST'])
    def motor_move_theta():
        data = request.get_json(silent=True) or {}
        angle = data.get('angle_deg')
        revs = data.get('revolutions')
        speed = data.get('speed_deg_s')
        style = data.get('style')
        ramp_fraction = data.get('ramp_fraction')
        try:
            ramp_val = float(ramp_fraction) if ramp_fraction is not None else None
            if angle is not None:
                angle_val = float(angle)
                steps = move_angle(kit, 'THETA', angle_val, style=style, speed_deg_s=float(speed) if speed is not None else None, ramp_fraction=ramp_val)
                return jsonify({'axis':'THETA','requested_deg':angle_val,'steps_taken':steps,'style':style,'speed_deg_s':speed,'ramp_fraction':ramp_val})
            elif revs is not None:
                rev_val = float(revs)
                steps = move_revolutions(kit, 'THETA', rev_val, style=style, speed_deg_s=float(speed) if speed is not None else None, ramp_fraction=ramp_val)
                return jsonify({'axis':'THETA','requested_revs':rev_val,'steps_taken':steps,'style':style,'speed_deg_s':speed,'ramp_fraction':ramp_val})
            else:
                return jsonify({'error':'Provide angle_deg or revolutions'}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/motor/release_all', methods=['POST'])
    def motor_release_all():
        try:
            release_all(kit)
            return jsonify({'message':'Motors released'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/motor/status')
    def motor_status():
        try:
            z = get_motor_settings('Z')
            th = get_motor_settings('THETA')
            return jsonify({'Z': z, 'THETA': th})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return app

# --------------------------- Entrypoint --------------------------------------

def main(host: str='0.0.0.0', port: int=5000):  # pragma: no cover
    app = create_app()
    print(f"OTM Controller running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    app.run(host=host, port=port, threaded=True)

if __name__ == '__main__':  # pragma: no cover
    main()
