"""
TRELLIS image-to-3D on Beam, producing decimated GLB meshes for VICE COAST.

Why this file looks heavier than the Klein one: TRELLIS needs four custom CUDA
extensions that compile at image-build time (spconv, nvdiffrast, diffoctreerast,
vox2seq). The model itself is only ~1.2B params and runs fine on a 4090 - the
install is the hard part, not the inference.

Two deliberate choices to keep the build survivable:
  ATTN_BACKEND=xformers   prebuilt wheels, so we never compile flash-attn
  SPCONV_ALGO=native      skips spconv's autotune, which needs a warmup pass

Both env vars MUST be set before trellis is imported.

Deploy (from this folder, or Beam uploads your whole drive):
    beam deploy trellis_beam.py:generate

Meshes land on the vicecoast-meshes volume as .glb.
"""

import base64
import json
import os
import sys
import time

from beam import Image, Volume, endpoint

TRELLIS_DIR = "/trellis"
OUT_DIR = "/meshes"
REPO = "/opt/TRELLIS"

weights = Volume(name="trellis-weights", mount_path=TRELLIS_DIR)
meshes = Volume(name="vicecoast-meshes", mount_path=OUT_DIR)

image = (
    Image(python_version="python3.11")
    .add_commands([
        "apt-get update -y && apt-get install -y git build-essential ninja-build "
        "libgl1 libglib2.0-0 libegl1 libgles2 libglvnd-dev libgl1-mesa-dev libegl1-mesa-dev",

        # Same cu126 pin as the Klein app - Beam's 4090 hosts run driver 12.8 and
        # an unpinned resolve grabs a CUDA 13 build that cannot initialise.
        "pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 "
        "--index-url https://download.pytorch.org/whl/cu126",

        # -U matters: these already exist in the base image, so without it pip says
        # 'already satisfied' and leaves a stale setuptools/packaging pair behind.
        # --no-build-isolation then builds against them, and modern setuptools
        # calls canonicalize_version(strip_trailing_zero=...) which needs packaging>=24.
        "pip install --no-cache-dir -U ninja wheel 'setuptools>=70' 'packaging>=24.1'",

        # Tell us what the base image actually has, so the next failure is
        # diagnosable instead of guesswork.
        "echo '--- probe ---' && (which nvcc || echo NO_NVCC) && "
        "(ls -d /usr/local/cuda* 2>/dev/null || echo NO_CUDA_DIR) && echo '--- /probe ---'",

        # torch here bundles only the CUDA runtime, not the toolkit, so there is
        # no nvcc for the extensions to compile with. Pull a minimal 12.6
        # toolkit matching the pinned torch build.
        "apt-get install -y wget && "
        "wget -q https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb "
        "-O /tmp/ck.deb && dpkg -i /tmp/ck.deb && apt-get update -y && "
        "apt-get install -y --no-install-recommends cuda-nvcc-12-6 cuda-cudart-dev-12-6 "
        "cuda-nvrtc-dev-12-6 libcurand-dev-12-6 && rm -f /tmp/ck.deb",

        # xformers must match the torch build exactly, so take it from the same index
        "pip install --no-cache-dir xformers --index-url https://download.pytorch.org/whl/cu126",

        "pip install --no-cache-dir spconv-cu126",

        # TRELLIS source, plus its two rasteriser extensions
        f"git clone --recurse-submodules https://github.com/microsoft/TRELLIS.git {REPO}",
        # --no-build-isolation: these read torch's CUDA config at BUILD time and
        # pip's isolated env has no torch in it.
        # TORCH_CUDA_ARCH_LIST: Beam builds on a machine with NO GPU, so torch's
        # arch autodetect returns an empty list and dies on arch_list[-1]. 8.9 is
        # Ada, which is the RTX 4090 these run on.
        "CUDA_HOME=/usr/local/cuda-12.6 PATH=/usr/local/cuda-12.6/bin:$PATH TORCH_CUDA_ARCH_LIST=8.9+PTX FORCE_CUDA=1 "
        "pip install --no-cache-dir --no-build-isolation git+https://github.com/NVlabs/nvdiffrast.git",
        "CUDA_HOME=/usr/local/cuda-12.6 PATH=/usr/local/cuda-12.6/bin:$PATH TORCH_CUDA_ARCH_LIST=8.9+PTX FORCE_CUDA=1 "
        "pip install --no-cache-dir --no-build-isolation git+https://github.com/JeffreyXiang/diffoctreerast.git",
        f"CUDA_HOME=/usr/local/cuda-12.6 PATH=/usr/local/cuda-12.6/bin:$PATH TORCH_CUDA_ARCH_LIST=8.9+PTX FORCE_CUDA=1 "
        f"pip install --no-cache-dir --no-build-isolation {REPO}/extensions/vox2seq",

        "pip install --no-cache-dir "
        "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8",
    ])
    .add_python_packages([
        "pillow", "imageio", "imageio-ffmpeg", "tqdm", "easydict",
        "opencv-python-headless", "scipy", "einops", "transformers",
        "trimesh", "xatlas", "pyvista", "pymeshfix", "igraph",
        "rembg", "onnxruntime", "huggingface_hub[hf_transfer]", "safetensors",
    ])
)


def load_model():
    # These two must land before trellis is imported anywhere.
    os.environ["ATTN_BACKEND"] = "xformers"
    os.environ["SPCONV_ALGO"] = "native"
    os.environ["HF_HOME"] = "/tmp/hf"          # volumes have no flock
    os.environ["HF_HUB_CACHE"] = os.path.join(TRELLIS_DIR, "hub")

    sys.path.insert(0, REPO)

    import torch
    from trellis.pipelines import TrellisImageTo3DPipeline

    t0 = time.perf_counter()
    pipe = TrellisImageTo3DPipeline.from_pretrained("microsoft/TRELLIS-image-large")
    pipe.cuda()
    print(f"[on_start] TRELLIS ready in {time.perf_counter() - t0:.1f}s "
          f"on {torch.cuda.get_device_name(0)}")
    return pipe


@endpoint(
    name="vicecoast-trellis",
    image=image,
    volumes=[weights, meshes],
    gpu="RTX4090",
    cpu=8,
    memory="48Gi",
    on_start=load_model,
    keep_warm_seconds=300,
    timeout=3600,
)
def generate(context, **inputs):
    from PIL import Image as PILImage
    import io as _io

    pipe = context.on_start_value

    jobs = inputs.get("jobs") or []
    if not jobs:
        return {"error": "no jobs supplied"}

    out_name = inputs.get("out", "v1")
    # Low step counts on purpose. At 25k triangles for the whole city, extra
    # sampling detail is thrown away by the decimator anyway.
    ss_steps = int(inputs.get("ss_steps", 12))
    slat_steps = int(inputs.get("slat_steps", 12))
    simplify = float(inputs.get("simplify", 0.95))
    tex_size = int(inputs.get("texture_size", 1024))

    target = os.path.join(OUT_DIR, out_name)
    os.makedirs(target, exist_ok=True)

    sys.path.insert(0, REPO)
    from trellis.utils import postprocessing_utils

    manifest = []
    t_start = time.perf_counter()

    for i, job in enumerate(jobs):
        jid = job.get("id") or f"mesh_{i:03d}"
        img = PILImage.open(_io.BytesIO(base64.b64decode(job["image_b64"]))).convert("RGB")

        t0 = time.perf_counter()
        out = pipe.run(
            img,
            seed=int(job.get("seed", 1)),
            formats=["mesh", "gaussian"],
            sparse_structure_sampler_params={"steps": ss_steps, "cfg_strength": 7.5},
            slat_sampler_params={"steps": slat_steps, "cfg_strength": 3.0},
        )
        t_gen = time.perf_counter() - t0

        t1 = time.perf_counter()
        glb = postprocessing_utils.to_glb(
            out["gaussian"][0], out["mesh"][0],
            simplify=simplify, texture_size=tex_size, verbose=False,
        )
        path = os.path.join(target, f"{jid}.glb")
        glb.export(path)
        t_bake = time.perf_counter() - t1

        size_kb = os.path.getsize(path) / 1024
        manifest.append({"id": jid, "file": f"{jid}.glb", "kb": round(size_kb, 1),
                         "gen_s": round(t_gen, 2), "bake_s": round(t_bake, 2)})
        print(f"[{i+1}/{len(jobs)}] {jid}: gen {t_gen:.1f}s bake {t_bake:.1f}s {size_kb:.0f}KB")

    total = time.perf_counter() - t_start
    with open(os.path.join(target, "manifest.json"), "w") as f:
        json.dump({"out": out_name, "meshes": manifest,
                   "total_seconds": round(total, 2)}, f, indent=2)

    return {"count": len(manifest), "out": out_name,
            "total_seconds": round(total, 2), "meshes": manifest}
