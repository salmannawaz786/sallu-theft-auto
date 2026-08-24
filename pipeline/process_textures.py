"""
Turn raw Klein output into game-ready textures. Pure CPU - no GPU time.

Three jobs:

  1. SEAMLESS  Ground textures must tile. We offset the image by half so the
               discontinuity lands in the middle, then cross-fade a feathered
               band over it. Ghosting is invisible on noisy surfaces like
               asphalt, which is exactly what we tile.

  2. EMISSIVE  The engine drives building glow off the day/night cycle, so a
               single baked image is no good - lit windows would stay lit at
               noon. We split each facade into an unlit albedo and an emissive
               mask of just the glowing parts, and the shader recombines them.

  3. SHRINK    1024px facades are wasted on buildings that render 40px tall,
               and this has to load fast on a laptop. Albedo goes out as JPEG,
               emissive as a small PNG.

    python process_textures.py facades_v2
"""

import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "out")
DST = os.path.join(HERE, "..", "textures")

# id -> how to treat it
RECIPE = {
    "asphalt_wet":           {"kind": "tile",   "size": 512},
    "facade_tower_dark":     {"kind": "facade", "size": (256, 512)},
    "facade_tower_concrete": {"kind": "facade", "size": (256, 512)},
    "facade_deco_pastel":    {"kind": "facade", "size": (512, 512)},
    "facade_brick_walkup":   {"kind": "facade", "size": (512, 512)},
    "shopfront_row":         {"kind": "facade", "size": (512, 256)},
    "shopfront_bar":         {"kind": "facade", "size": (512, 256)},
    "facade_glass_blue":     {"kind": "facade", "size": (256, 512)},
    "facade_projects":       {"kind": "facade", "size": (256, 512)},
    "facade_warehouse":      {"kind": "facade", "size": (512, 256)},
    "facade_hotel":          {"kind": "facade", "size": (512, 512)},
    "facade_office_grid":    {"kind": "facade", "size": (512, 512)},
    "facade_stucco_pink":    {"kind": "facade", "size": (512, 512)},
    "shopfront_a":           {"kind": "facade", "size": (512, 256)},
    "shopfront_b":           {"kind": "facade", "size": (512, 256)},
    "shopfront_c":           {"kind": "facade", "size": (512, 256)},
    "shopfront_d":           {"kind": "facade", "size": (512, 256)},
    "road_detail":           {"kind": "tile",   "size": 1024},
    "road_markings":         {"kind": "tile",   "size": 512},
    "neon_signs_sheet":      {"kind": "glow",   "size": 512},

    # ---- ground pass v3 ----
    # The carriageway is real geometry with world-tiled UVs now, so these are
    # kept at 1024 rather than the 512 the canvas-baked versions were shrunk
    # to. At 7.5m per tile that is ~136 px/metre on screen instead of 3.5.
    "asphalt_road":          {"kind": "tile",   "size": 1024},
    "asphalt_worn":          {"kind": "tile",   "size": 1024},
    "pavement_wet":          {"kind": "tile",   "size": 1024},
    "plaza_tile":            {"kind": "tile",   "size": 512},
    "grass_park":            {"kind": "tile",   "size": 512},
    "sand_beach":            {"kind": "tile",   "size": 512},
    "dirt_path":             {"kind": "tile",   "size": 512},
    "kerb_strip":            {"kind": "tile",   "size": (512, 256)},
    "facade_artdeco_teal":   {"kind": "facade", "size": (256, 512)},
    "facade_brutalist":      {"kind": "facade", "size": (256, 512)},
    "facade_neon_motel":     {"kind": "facade", "size": (512, 256)},
    "facade_market_arcade":  {"kind": "facade", "size": (512, 512)},
    "facade_tower_gold":     {"kind": "facade", "size": (256, 512)},
    "facade_redbrick_loft":  {"kind": "facade", "size": (512, 512)},
    "shopfront_diner":       {"kind": "facade", "size": (512, 256)},
    "shopfront_laundromat":  {"kind": "facade", "size": (512, 256)},
    "billboard_sheet":       {"kind": "flat",   "size": (512, 256)},
}


def make_seamless(img: Image.Image, feather: float = 0.12) -> Image.Image:
    """Offset by half, then cross-fade the seam cross that lands in the middle."""
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    h, w = a.shape[:2]

    rolled = np.roll(np.roll(a, w // 2, axis=1), h // 2, axis=0)

    fx, fy = max(2, int(w * feather)), max(2, int(h * feather))

    # weight 1 in the clean areas, ramping to 0.5 exactly on the seam, where we
    # mix in the mirrored neighbour so both sides meet continuously
    out = rolled.copy()

    xs = np.arange(w)
    band_x = np.clip((np.abs(xs - w / 2) / fx), 0, 1)          # 0 on seam, 1 outside
    wx = (0.5 + 0.5 * band_x)[None, :, None]
    out = out * wx + np.flip(rolled, axis=1) * (1 - wx)

    ys = np.arange(h)
    band_y = np.clip((np.abs(ys - h / 2) / fy), 0, 1)
    wy = (0.5 + 0.5 * band_y)[:, None, None]
    out = out * wy + np.flip(out, axis=0) * (1 - wy)

    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def split_emissive(img: Image.Image, thresh: float = 0.55, boost: float = 1.0):
    """Separate the glowing bits (lit windows, neon) from the dead surface.

    Returns (albedo, emissive). Albedo has the glow knocked down so the shader
    can add it back scaled by how dark it is outside - otherwise windows would
    blaze at midday."""
    a = np.asarray(img.convert("RGB")).astype(np.float32) / 255.0

    lum = a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1e-4)

    # emissive = bright, OR strongly coloured and reasonably bright (neon tubes
    # are saturated but not always high luminance)
    m = np.maximum(
        np.clip((lum - thresh) / max(1e-4, 1 - thresh), 0, 1),
        np.clip((sat - 0.45) * 1.6, 0, 1) * np.clip((lum - 0.22) * 2.4, 0, 1),
    )
    m = np.asarray(
        Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.1)),
        dtype=np.float32,
    ) / 255.0

    emis = np.clip(a * m[..., None] * boost, 0, 1)
    albedo = np.clip(a * (1 - 0.72 * m[..., None]), 0, 1)

    return (Image.fromarray((albedo * 255).astype(np.uint8)),
            Image.fromarray((emis * 255).astype(np.uint8)))


def fit(img, size):
    if isinstance(size, int):
        size = (size, size)
    return img.resize(size, Image.LANCZOS)


def main():
    batch = sys.argv[1] if len(sys.argv) > 1 else "trial_v1"
    src = os.path.join(SRC, batch)
    if not os.path.isdir(src):
        sys.exit(f"No such batch: {src}")

    os.makedirs(DST, exist_ok=True)
    made = []

    for fn in sorted(os.listdir(src)):
        if not fn.lower().endswith(".png"):
            continue
        tid = os.path.splitext(fn)[0]
        rec = RECIPE.get(tid)
        if not rec:
            print(f"  skip {tid} (no recipe)")
            continue

        img = Image.open(os.path.join(src, fn))
        kind, size = rec["kind"], rec["size"]

        if kind == "tile":
            out = fit(make_seamless(img), size)
            p = os.path.join(DST, f"{tid}.jpg")
            out.save(p, "JPEG", quality=86, optimize=True)
            made.append((tid, "tiling", os.path.getsize(p)))

        elif kind == "facade":
            albedo, emis = split_emissive(img)
            p = os.path.join(DST, f"{tid}.jpg")
            fit(albedo, size).save(p, "JPEG", quality=84, optimize=True)
            pe = os.path.join(DST, f"{tid}_e.jpg")
            fit(emis, size).save(pe, "JPEG", quality=78, optimize=True)
            made.append((tid, "albedo+emissive", os.path.getsize(p) + os.path.getsize(pe)))

        elif kind == "glow":
            # already on black - it IS the emissive, additive in engine
            p = os.path.join(DST, f"{tid}.jpg")
            fit(img, size).save(p, "JPEG", quality=86, optimize=True)
            made.append((tid, "additive glow", os.path.getsize(p)))

        else:
            p = os.path.join(DST, f"{tid}.jpg")
            fit(img, size).save(p, "JPEG", quality=85, optimize=True)
            made.append((tid, "flat", os.path.getsize(p)))

    total = sum(m[2] for m in made)
    print(f"\n{'texture':<24}{'kind':<18}{'KB':>8}")
    print("-" * 50)
    for tid, kind, sz in made:
        print(f"{tid:<24}{kind:<18}{sz/1024:>8.0f}")
    print("-" * 50)
    print(f"{len(made)} textures, {total/1024:.0f} KB total -> {os.path.normpath(DST)}")

    with open(os.path.join(DST, "index.json"), "w") as f:
        json.dump({"batch": batch, "textures": [m[0] for m in made]}, f, indent=2)


if __name__ == "__main__":
    main()
