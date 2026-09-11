"""Search Runware's catalogue so model IDs are looked up, not guessed.

A wrong AIR identifier is a wasted (billed) generation, so this runs first.
Reads RUNWARE_API_KEY from .env - never pass the key on the command line,
it ends up in shell history.
"""
import json, os, sys, uuid, urllib.request, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text().splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

KEY = os.environ["RUNWARE_API_KEY"]
URL = "https://api.runware.ai/v1"

def call(tasks):
    req = urllib.request.Request(
        URL,
        data=json.dumps(tasks).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + KEY},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())

term = sys.argv[1] if len(sys.argv) > 1 else "flux"
res = call([{
    "taskType": "modelSearch",
    "taskUUID": str(uuid.uuid4()),
    "search": term,
    "category": "checkpoint",
    "limit": 30,
}])

items = (res.get("data") or [{}])[0].get("results", [])
if not items:
    print(json.dumps(res, indent=1)[:3000])
else:
    print(f"{len(items)} results for {term!r}\n")
    for m in items:
        print(f"  {m.get('air','?'):<34} {m.get('name','?')[:46]:<48}"
              f" arch={m.get('architecture','?'):<12} steps~{m.get('defaultSteps','?')}")
