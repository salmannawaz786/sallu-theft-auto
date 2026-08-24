"""
Driver for the Klein 4B texture batch.

    python generate_textures.py <ENDPOINT_URL> [prompts_trial.json]

The endpoint URL is what `beam deploy flux_klein_beam.py:generate` prints.
The auth token is read from ~/.beam/config.ini - it is never printed, logged,
or written anywhere by this script.

Sends every prompt in ONE request so the batch pays a single cold start,
then tells you exactly how much GPU time it burned.
"""

import configparser
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def beam_token(context="default"):
    cfg = configparser.ConfigParser()
    cfg.read(os.path.expanduser("~/.beam/config.ini"))
    if context not in cfg or "token" not in cfg[context]:
        sys.exit("No Beam token found in ~/.beam/config.ini - run: beam configure default")
    return cfg[context]["token"]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    url = sys.argv[1]
    sheet_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "prompts_trial.json")

    with open(sheet_path, encoding="utf-8") as f:
        sheet = json.load(f)

    jobs = sheet["jobs"]
    payload = {
        "jobs": jobs,
        "out": sheet.get("out", "trial_v1"),
        "steps": sheet.get("steps", 2),
        "seed": sheet.get("seed", 1234),
    }

    px = sum(j.get("w", 1024) * j.get("h", 1024) for j in jobs)
    print(f"Sending {len(jobs)} prompts ({px / 1_000_000:.1f} megapixels total) at "
          f"{payload['steps']} steps -> {payload['out']}")
    print("First call includes a cold start (weights download on the very first run "
          "only, then cached on the volume).\n")

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {beam_token()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            result = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:600]}")

    wall = time.time() - t0

    if "error" in result:
        sys.exit(f"Endpoint error: {result['error']}")

    print(f"\n{'id':<24}{'size':>12}{'seconds':>10}")
    print("-" * 46)
    for im in result["images"]:
        print(f"{im['id']:<24}{im['w']}x{im['h']:>6}{im['seconds']:>10.2f}")

    print("-" * 46)
    print(f"GPU time generating : {result['total_seconds']:.1f}s "
          f"({result['avg_seconds']:.2f}s per image)")
    print(f"Wall clock          : {wall:.1f}s "
          f"(the gap is cold start + transfer)")
    print(f"\nPull the PNGs down with:\n"
          f"  beam cp beam://vicecoast-textures/{result['out']} \"{HERE}\\out\"")


if __name__ == "__main__":
    main()
