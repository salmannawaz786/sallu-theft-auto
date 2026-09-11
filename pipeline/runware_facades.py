"""Generate the daytime facade set on Runware (FLUX.2 [klein] 9B).

Every call here is billed, so the design is defensive:

  * --only lets a single job be run first as a test shot, before committing
    the rest of the sheet.
  * Runware returns a `cost` per image. It is accumulated and written to
    pipeline/runware_spend.json so the running total survives a crash and
    cannot be lost to a scrolled-away terminal.
  * Images already present on disk are skipped unless --force, so a re-run
    after a network failure does not re-bill the ones that succeeded.

The key is read from .env and never printed.
"""
import argparse
import json
import os
import pathlib
import sys
import time
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "textures"
RAW = ROOT / "pipeline" / "out" / "facades_day"
SPEND = ROOT / "pipeline" / "runware_spend.json"
URL = "https://api.runware.ai/v1"

for line in (ROOT / ".env").read_text().splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
KEY = os.environ["RUNWARE_API_KEY"]


def call(tasks, timeout=300):
    req = urllib.request.Request(
        URL,
        data=json.dumps(tasks).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + KEY},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def record(entry):
    log = json.loads(SPEND.read_text()) if SPEND.exists() else {"runs": []}
    log["runs"].append(entry)
    log["total_usd"] = round(sum(r.get("cost", 0) or 0 for r in log["runs"]), 6)
    log["image_count"] = sum(1 for r in log["runs"] if r.get("cost") is not None)
    SPEND.write_text(json.dumps(log, indent=1))
    return log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default="pipeline/prompts_facades_day.json")
    ap.add_argument("--only", help="run just this job id (test shot)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    sheet = json.loads((ROOT / a.sheet).read_text())
    jobs = sheet["jobs"]
    if a.only:
        jobs = [j for j in jobs if j["id"] == a.only]
        if not jobs:
            sys.exit("no job with id " + a.only)

    RAW.mkdir(parents=True, exist_ok=True)
    todo = []
    for j in jobs:
        dest = RAW / (j["id"] + "_day.png")
        if dest.exists() and not a.force:
            print("skip (already generated): " + j["id"])
            continue
        todo.append((j, dest))

    print(f"\n{len(todo)} image(s) to generate on {sheet['model']} "
          f"at {sheet['steps']} steps")
    if a.dry_run:
        for j, _ in todo:
            print(f"  {j['id']:<26} {j['w']}x{j['h']}")
        return

    total = 0.0
    for n, (j, dest) in enumerate(todo, 1):
        t0 = time.time()
        task = {
            "taskType": "imageInference",
            "taskUUID": str(uuid.uuid4()),
            "positivePrompt": j["prompt"],
            "model": sheet["model"],
            "width": j["w"],
            "height": j["h"],
            "steps": sheet["steps"],
            "numberResults": 1,
            "outputType": "URL",
            "outputFormat": "PNG",
            # off by default: without it the response carries no price at all
            "includeCost": True,
        }
        try:
            res = call([task])
        except Exception as e:
            print(f"  [{n}/{len(todo)}] {j['id']}  FAILED: {e}")
            record({"id": j["id"], "cost": None, "error": str(e)})
            continue

        data = (res.get("data") or [])
        if not data:
            print(f"  [{n}/{len(todo)}] {j['id']}  no data: "
                  f"{json.dumps(res)[:300]}")
            record({"id": j["id"], "cost": None, "error": json.dumps(res)[:300]})
            continue

        d = data[0]
        cost = d.get("cost")
        url = d.get("imageURL")
        if url:
            urllib.request.urlretrieve(url, dest)
        total += cost or 0
        log = record({"id": j["id"], "cost": cost, "w": j["w"], "h": j["h"],
                      "model": sheet["model"], "file": str(dest.name)})
        print(f"  [{n}/{len(todo)}] {j['id']:<26} {j['w']}x{j['h']}  "
              f"{time.time()-t0:5.1f}s  ${cost if cost is not None else '?'}"
              f"   running total ${log['total_usd']}")

    print(f"\nthis run: ${round(total, 6)}")
    if SPEND.exists():
        log = json.loads(SPEND.read_text())
        print(f"all runs: ${log['total_usd']} over {log['image_count']} images")
    print("raw PNGs in " + str(RAW))


if __name__ == "__main__":
    main()
