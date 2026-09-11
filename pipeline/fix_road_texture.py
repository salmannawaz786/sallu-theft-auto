"""Flatten the baked-in lighting gradient from the road albedo tiles.

The generated asphalt textures carry a huge low-frequency sun gradient
(baked "golden hour" light). Tiled every few metres in-game, that gradient
is what makes the carriageway read as chopped sand instead of asphalt.

For each texture:
  1. estimate the low-frequency lighting field with a heavy Gaussian blur
  2. divide it out (flat-field correction), keeping the high-frequency detail
  3. re-anchor the result to a target asphalt luminance
  4. make the tile edge-neutral so RepeatWrapping seams disappear

Writes *_flat.jpg alongside the originals; originals are kept.
"""
import os
import numpy as np
from PIL import Image, ImageFilter

TEX = os.path.join(os.path.dirname(__file__), "..", "textures")

# target mean luminance (0-255) per file: asphalt should sit dark grey
JOBS = {
    "asphalt_road_day.jpg": ("asphalt_road_day_flat.jpg", 96),
    "asphalt_road.jpg": ("asphalt_road_flat.jpg", 78),
    "asphalt_wet.jpg": ("asphalt_wet_flat.jpg", 60),
    "road_detail_day.jpg": ("road_detail_day_flat.jpg", 100),
    "road_detail.jpg": ("road_detail_flat.jpg", 88),
}


def flatten(path_in, path_out, target_luma):
    im = Image.open(path_in).convert("RGB")
    a = np.asarray(im).astype(np.float32) + 1.0

    # low-frequency lighting field, per channel: a very heavy blur catches the
    # whole baked sun gradient, not just the small-scale shading
    r = max(im.size) // 3
    lf = np.asarray(im.filter(ImageFilter.GaussianBlur(radius=r))).astype(np.float32) + 1.0

    # divide the lighting out of every channel - this also kills the colour
    # cast, because the warm gradient lives in the low frequencies
    flat = a / lf

    # re-anchor to the target luminance
    cur = flat.mean()
    flat *= target_luma / cur

    # desaturate toward neutral asphalt grey: real tarmac has almost no chroma
    g = flat.mean(axis=2, keepdims=True)
    flat = g + (flat - g) * 0.35

    # edge-neutralise: cross-fade the borders with their wrap-around selves
    # so RepeatWrapping has no visible seam
    w = 24
    h, wd = flat.shape[:2]
    ramp = np.linspace(0, 1, w)[None, :, None]
    flat[:, :w] = flat[:, :w] * (1 - ramp) + flat[:, -w:][:, ::-1] * ramp
    flat[:, -w:] = flat[:, -w:] * (1 - ramp[:, ::-1]) + flat[:, :w][:, ::-1] * ramp[:, ::-1]
    rampy = np.linspace(0, 1, w)[:, None, None]
    flat[:w] = flat[:w] * (1 - rampy) + flat[-w:][::-1] * rampy
    flat[-w:] = flat[-w:] * (1 - rampy[::-1]) + flat[:w][::-1] * rampy[::-1]

    out = Image.fromarray(np.clip(flat, 0, 255).astype(np.uint8))
    out.save(path_out, quality=90)
    print(f"{os.path.basename(path_in)} -> {os.path.basename(path_out)}  "
          f"mean {cur - 1:.0f} -> {target_luma}")


def main():
    for src, (dst, luma) in JOBS.items():
        p = os.path.join(TEX, src)
        if os.path.exists(p):
            flatten(p, os.path.join(TEX, dst), luma)
        else:
            print(f"skip {src} (missing)")


if __name__ == "__main__":
    main()
