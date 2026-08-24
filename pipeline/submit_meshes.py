"""
Submit the mesh batch to the Hunyuan task queue, then poll for results.

    python submit_meshes.py <TASKQUEUE_URL> [batch_dir]

Why polling the VOLUME rather than a task status API: several Beam CLI paths are
broken on this machine (beam logs dies with an SSL error, beam cp mangles remote
paths on Windows), so "did the .glb files appear" is the most reliable signal
available. The task queue returns immediately, so nothing has to survive a
multi-minute cold start on one socket.
"""

import base64
import configparser
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VOL = "vicecoast-meshes"


def beam_token(context="default"):
    cfg = configparser.ConfigParser()
    cfg.read(os.path.expanduser("~/.beam/config.ini"))
    return cfg[context]["token"]


def remote_files(out_dir):
    """List what has landed on the volume so far."""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run(["beam", "ls", f"{VOL}/{out_dir}"],
                           capture_output=True, text=True, timeout=90, env=env)
    except Exception:
        return []
    return [ln.split()[0] for ln in r.stdout.splitlines()
            if ".glb" in ln or "manifest.json" in ln]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    url = sys.argv[1]
    batch = sys.argv[2] if len(sys.argv) > 2 else "vehicles_v1"
    src = os.path.join(HERE, "out", batch)
    if not os.path.isdir(src):
        sys.exit(f"No such batch: {src}")

    from PIL import Image as PILImage

    jobs = []
    for fn in sorted(os.listdir(src)):
        if not fn.lower().endswith(".png"):
            continue
        im = PILImage.open(os.path.join(src, fn)).convert("RGB")
        im.thumbnail((768, 768), PILImage.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=92)
        jobs.append({"id": os.path.splitext(fn)[0],
                     "image_b64": base64.b64encode(buf.getvalue()).decode()})

    payload = {"jobs": jobs, "out": batch, "steps": 12,
               "octree_resolution": 256, "face_budget": 1800}

    print(f"Submitting {len(jobs)} jobs to the task queue...")
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {beam_token()}",
                 "Content-Type": "application/json"}, method="POST")
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=180).read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:800]}")

    print(f"Accepted: {json.dumps(resp)[:200]}")
    print("\nThe container still has to boot and pull the model on the first "
          "run. Polling the volume for results.\n")

    expected = len(jobs)
    t0 = time.time()
    seen = 0
    while time.time() - t0 < 2700:          # 45 minutes
        files = remote_files(batch)
        glbs = [f for f in files if f.endswith(".glb")]
        if len(glbs) != seen:
            seen = len(glbs)
            print(f"[{(time.time()-t0)/60:5.1f} min] {seen}/{expected} meshes: "
                  f"{', '.join(sorted(glbs))}")
        if seen >= expected or "manifest.json" in files:
            print("\nDone. Pull them with:  python pull_meshes.py " + batch)
            return
        time.sleep(45)

    print("\nTimed out waiting. Check `beam task list` for the task state.")


if __name__ == "__main__":
    main()
