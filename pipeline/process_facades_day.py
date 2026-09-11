"""Turn the raw Runware facade renders into tileable game textures.

The game repeats each facade about three times across a building face and
three or four times up it, so a tile whose edges do not meet puts a hard line
across every building in the city.

Two things were wrong with the raw renders, and the measurements said which:

1. A low-frequency brightness gradient. Flux lights the top of a wall
   differently from the bottom, so row 0 and row h-1 are simply different
   exposures - the vertical seam ratio was as bad as 32x an ordinary row step
   on facade_tower_dark. Cropping to a whole number of window bays cannot
   touch that, which is why the first attempt at this barely moved the numbers.
   Flat-fielding (dividing by a heavily blurred copy of itself) removes the
   gradient while leaving local contrast alone, and it also fixes a second
   problem nobody had noticed yet: without it, tiling the wall four times up a
   tower stacks four visible bright-to-dark bands.

2. The residual vertical join, which a short cross-fade closes.

The horizontal join is not blended at all. Cross-fading a hard architectural
grid smears a ghost band through the join that reads worse than the seam it
replaces, so instead the game samples these with MirroredRepeatWrapping across
S - exact by construction, no processing, no lost sharpness, and a mirrored
window grid is not something you can see. Vertical stays a normal repeat
because mirroring there would hang every other band of balconies and air
conditioners upside down.

Seam ratio is mean |edge difference| over mean |difference| between
neighbouring interior lines. 1.0 means the join is no more visible than any
other line in the texture.
"""
import json
import pathlib

import numpy as np
from PIL import Image, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "pipeline" / "out" / "facades_day"
OUT = ROOT / "textures"

TOWER = (512, 1024)
LOW = (512, 512)
FEATHER = 0.10          # fraction of height cross-faded to close the V join


def seam_ratio(a):
    g = a.astype(np.float32).mean(axis=2)
    h = np.abs(g[:, 0] - g[:, -1]).mean() / max(np.abs(np.diff(g, axis=1)).mean(), 1e-6)
    v = np.abs(g[0, :] - g[-1, :]).mean() / max(np.abs(np.diff(g, axis=0)).mean(), 1e-6)
    return h, v


def flat_field(im):
    """Remove the lighting gradient, keep the detail."""
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    r = max(im.size) / 6.0
    blur = np.asarray(im.convert("RGB").filter(
        ImageFilter.GaussianBlur(radius=r))).astype(np.float32)
    blur = np.maximum(blur, 1.0)
    out = a / blur * blur.mean(axis=(0, 1), keepdims=True)
    return np.clip(out, 0, 255)


def wrap_v(a, feather):
    """Cross-fade the top and bottom bands so the texture repeats up the wall."""
    h = a.shape[0]
    n = max(2, int(h * feather))
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    t = (t * t * (3 - 2 * t))[:, None, None]          # smoothstep
    top, bot = a[:n].copy(), a[-n:].copy()
    a[:n] = bot * (1.0 - t) + top * t
    return a


def main():
    sheet = json.loads((ROOT / "pipeline" / "prompts_facades_day.json").read_text())
    print(f"{'id':<26} {'seam before H/V':<18} {'seam after H/V':<18} out")
    print("-" * 88)
    worst = 0.0
    for j in sheet["jobs"]:
        src = RAW / (j["id"] + "_day.png")
        if not src.exists():
            print(f"{j['id']:<26} MISSING")
            continue
        im = Image.open(src)
        before = seam_ratio(np.asarray(im.convert("RGB")))
        flat = flat_field(im)
        # Widen the cross-fade until the join actually measures closed rather
        # than assuming one fixed width does it. The gradient-dominated walls
        # pass at 10%; the ones whose top and bottom are genuinely different
        # content (a motel walkway, a steel spandrel band) need more, and
        # paying that cost only where it is needed keeps the rest sharp.
        # Keep the BEST candidate, not the last one tried. A wider feather is
        # not monotonically better - on facade_glass_blue it dragged a band of
        # cloud reflection across the join and measured worse than no feather
        # at all - so each width is scored and the winner kept.
        a, used, best = None, FEATHER, 1e9
        for f in (FEATHER, 0.15, 0.20, 0.26, 0.32):
            cand = wrap_v(flat.copy(), f)
            sv = seam_ratio(cand)[1]
            if sv < best:
                a, used, best = cand, f, sv
            if sv <= 2.5:
                break
        after = seam_ratio(a)
        worst = max(worst, after[1])

        size = LOW if j.get("low") else TOWER
        out = Image.fromarray(a.astype(np.uint8)).resize(size, Image.LANCZOS)
        dest = OUT / (j["id"] + "_day.jpg")
        out.save(dest, quality=90, subsampling=0)
        print(f"{j['id']:<26} {before[0]:6.2f} {before[1]:6.2f}     "
              f"{after[0]:6.2f} {after[1]:6.2f}   f={used:.2f}  "
              f"{dest.name} {size[0]}x{size[1]}")
    print(f"\nworst vertical seam after: {worst:.2f}  "
          f"(horizontal is handled by MirroredRepeatWrapping in-game)")


if __name__ == "__main__":
    main()
