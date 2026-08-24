"""Submit the batch, then poll the volume for results OR the error file."""
import base64, configparser, io, json, os, subprocess, sys, time, urllib.request
from PIL import Image as PILImage

URL = sys.argv[1]
BATCH = sys.argv[2] if len(sys.argv) > 2 else "vehicles_v1"
HERE = os.path.dirname(os.path.abspath(__file__))
VOL = "vicecoast-meshes"

cfg = configparser.ConfigParser(); cfg.read(os.path.expanduser("~/.beam/config.ini"))
TOK = cfg["default"]["token"]

SHEET = sys.argv[3] if len(sys.argv) > 3 else None
sheet = json.load(open(os.path.join(HERE, SHEET))) if SHEET else None
src = os.path.join(HERE, "out", BATCH)

jobs = []
specs = {j["id"]: j for j in sheet["jobs"]} if sheet else {}
for fn in sorted(os.listdir(src)):
    if not fn.endswith(".png"):
        continue
    jid = os.path.splitext(fn)[0]
    if specs and jid not in specs:
        continue
    im = PILImage.open(os.path.join(src, fn)).convert("RGB")
    im.thumbnail((896, 896), PILImage.LANCZOS)
    b = io.BytesIO(); im.save(b, "JPEG", quality=94)
    job = {"id": jid, "image_b64": base64.b64encode(b.getvalue()).decode()}
    if jid in specs:
        for k in ("face_budget", "octree_resolution", "steps"):
            if k in specs[jid]:
                job[k] = specs[jid][k]
    jobs.append(job)

out_name = (sheet or {}).get("out", BATCH)
req = urllib.request.Request(
    URL, data=json.dumps({"jobs": jobs, "out": out_name,
                          "steps": (sheet or {}).get("steps", 12),
                          "octree_resolution": (sheet or {}).get("octree_resolution", 256),
                          "face_budget": 1800}).encode(),
    headers={"Authorization": "Bearer " + TOK, "Content-Type": "application/json"},
    method="POST")
print(f"submitting {len(jobs)} jobs", flush=True)
print(urllib.request.urlopen(req, timeout=180).read().decode()[:200], flush=True)

env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
t0 = time.time()
while time.time() - t0 < 2400:
    time.sleep(40)
    try:
        r = subprocess.run(["beam", "ls", VOL], capture_output=True, text=True,
                           timeout=90, env=env)
        top = r.stdout
        r2 = subprocess.run(["beam", "ls", f"{VOL}/{out_name}"], capture_output=True,
                            text=True, timeout=90, env=env)
        inner = r2.stdout
    except Exception as e:
        print(f"[{(time.time()-t0)/60:4.1f}m] ls failed: {e}", flush=True); continue

    err = [l for l in top.splitlines() if "_error" in l]
    glbs = [l.split()[0] for l in inner.splitlines() if ".glb" in l]
    print(f"[{(time.time()-t0)/60:4.1f}m] glb={len(glbs)} err={len(err)}", flush=True)
    if err:
        print("ERROR FILE PRESENT:", err, flush=True); break
    if len(glbs) >= len(jobs):
        print("ALL MESHES DONE:", glbs, flush=True); break
