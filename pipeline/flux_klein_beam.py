"""
FLUX.2 [klein] 4B batch texture generator for VICE COAST, on Beam.cloud.

Reuses the weights already sitting on the flux-klein-weights volume (populated
2026-07-26 by the watermark app), so there is NO 13GB download - a cold start
is just the model load off the volume.

Conventions and the two non-obvious fixes below are lifted from
D:/Ai video editor/beam_app/klein_fill_beam.py, which already has this working:

  * torch pinned to cu126. Beam's 4090 hosts run driver 12.8 and an unpinned
    resolve grabs a CUDA 13 build that cannot initialise.
  * HF_HOME points at /tmp, not the volume. huggingface_hub locks
    <HF_HOME>/token and Beam volumes do not support flock.

Everything is generated in ONE call: a cold start costs real GPU seconds, so
fifty separate calls would bill far more than one fifty-image batch.

Deploy:
    beam deploy flux_klein_beam.py:generate

Drive it with generate_textures.py, which sends the prompt sheet and prints
the per-image timings.
"""

import json
import os
import time

from beam import Image, Volume, endpoint

KLEIN_DIR = "/klein"
OUT_DIR = "/textures"

# already populated - base/ (bf16), fp8/ and gguf/ variants all present
klein_vol = Volume(name="flux-klein-weights", mount_path=KLEIN_DIR)
out_vol = Volume(name="vicecoast-textures", mount_path=OUT_DIR)

image = (
    Image(python_version="python3.11")
    .add_commands([
        "apt-get update -y && apt-get install -y libgl1 libglib2.0-0",
        # cu126 pin - see module docstring. Do not let this resolve freely.
        "pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 "
        "--index-url https://download.pytorch.org/whl/cu126",
    ])
    .add_python_packages([
        "diffusers>=0.36.0", "transformers>=4.46.2", "accelerate", "safetensors",
        "sentencepiece", "protobuf", "pillow", "ftfy", "numpy",
        "huggingface_hub[hf_transfer]",
    ])
)


def load_model():
    """Runs once per container boot, straight off the volume - no network."""
    os.environ["HF_HOME"] = "/tmp/hf"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    import torch
    from diffusers import Flux2KleinPipeline

    t0 = time.perf_counter()
    pipe = Flux2KleinPipeline.from_pretrained(
        os.path.join(KLEIN_DIR, "base"), torch_dtype=torch.bfloat16
    ).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    print(f"[on_start] klein loaded in {time.perf_counter() - t0:.1f}s "
          f"on {torch.cuda.get_device_name(0)}")
    return pipe


@endpoint(
    name="vicecoast-flux-klein",
    image=image,
    volumes=[klein_vol, out_vol],
    gpu="RTX4090",
    cpu=4,
    memory="32Gi",
    on_start=load_model,
    # stay hot between batches so a prompt-tweaking loop does not pay a fresh
    # model load every time
    keep_warm_seconds=240,
    timeout=1800,
)
def generate(context, **inputs):
    import torch

    pipe = context.on_start_value

    jobs = inputs.get("jobs") or []
    if not jobs:
        return {"error": "no jobs supplied"}

    out_name = inputs.get("out", "v1")
    steps = int(inputs.get("steps", 2))
    base_seed = int(inputs.get("seed", 1234))

    target = os.path.join(OUT_DIR, out_name)
    os.makedirs(target, exist_ok=True)

    manifest = []
    t_start = time.perf_counter()

    for i, job in enumerate(jobs):
        jid = job.get("id") or f"img_{i:03d}"
        # klein wants dimensions on a multiple of 16
        w = (int(job.get("w", 1024)) // 16) * 16
        h = (int(job.get("h", 1024)) // 16) * 16
        seed = int(job.get("seed", base_seed + i))

        t0 = time.perf_counter()
        img = pipe(
            prompt=job["prompt"],
            width=w,
            height=h,
            num_inference_steps=int(job.get("steps", steps)),
            guidance_scale=float(job.get("guidance", 1.0)),
            generator=torch.Generator(device="cpu").manual_seed(seed),
        ).images[0]
        dt = time.perf_counter() - t0

        img.save(os.path.join(target, f"{jid}.png"), "PNG", optimize=True)
        manifest.append({"id": jid, "file": f"{jid}.png", "w": w, "h": h,
                         "seed": seed, "seconds": round(dt, 2)})
        print(f"[{i+1}/{len(jobs)}] {jid} {w}x{h} in {dt:.2f}s")

    total = time.perf_counter() - t_start
    with open(os.path.join(target, "manifest.json"), "w") as f:
        json.dump({"out": out_name, "images": manifest,
                   "total_seconds": round(total, 2)}, f, indent=2)

    return {
        "count": len(manifest),
        "out": out_name,
        "total_seconds": round(total, 2),
        "avg_seconds": round(total / len(manifest), 2),
        "images": manifest,
    }
