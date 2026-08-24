"""Poll the meshes volume until GLBs appear or a fresh error file shows up."""
import os, subprocess, sys, time
VOL = "vicecoast-meshes"; BATCH = sys.argv[1] if len(sys.argv) > 1 else "vehicles_v1"
env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
t0 = time.time()
while time.time() - t0 < 2100:
    try:
        top = subprocess.run(["beam","ls",VOL], capture_output=True, text=True,
                             timeout=90, env=env).stdout
        inner = subprocess.run(["beam","ls",f"{VOL}/{BATCH}"], capture_output=True,
                               text=True, timeout=90, env=env).stdout
    except Exception as e:
        print(f"[{(time.time()-t0)/60:4.1f}m] ls failed {e}", flush=True)
        time.sleep(40); continue
    err = [l.split()[0] for l in top.splitlines() if "_error" in l]
    glbs = [l.split()[0] for l in inner.splitlines() if ".glb" in l]
    print(f"[{(time.time()-t0)/60:4.1f}m] glb={len(glbs)} err={len(err)} {' '.join(sorted(glbs))}", flush=True)
    if err:
        print("NEW ERROR:", err, flush=True); break
    if len(glbs) >= 8:
        print("ALL DONE", flush=True); break
    time.sleep(40)
