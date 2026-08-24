"""Retry the probe until the container is warm.

Beam's gateway closes the connection while a cold container boots, so the first
few calls die mid-handshake. Each attempt still advances the boot, so retrying
eventually lands on a warm container.
"""
import configparser, json, os, socket, time, urllib.request

URL = "https://vicecoast-hunyuan-6b0060f-v3.app.beam.cloud"
cfg = configparser.ConfigParser(); cfg.read(os.path.expanduser("~/.beam/config.ini"))
TOK = cfg["default"]["token"]

for attempt in range(1, 9):
    socket.setdefaulttimeout(600)
    req = urllib.request.Request(
        URL, data=json.dumps({"probe": True}).encode(),
        headers={"Authorization": "Bearer " + TOK, "Content-Type": "application/json"},
        method="POST")
    try:
        body = urllib.request.urlopen(req, timeout=600).read()
        print(f"attempt {attempt}: OK")
        print(json.dumps(json.loads(body), indent=1)[:1500])
        break
    except Exception as e:
        print(f"attempt {attempt}: {type(e).__name__} {str(e)[:90]}", flush=True)
        time.sleep(20)
else:
    print("gave up after 8 attempts")
