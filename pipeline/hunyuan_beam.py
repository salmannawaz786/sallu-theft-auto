"""
Hunyuan3D-2 mini image-to-3D on Beam. Replaces the TRELLIS attempt.

WHY THE SWITCH
--------------
Five TRELLIS builds died in nvdiffrast, for three different reasons (no torch in
the isolated build env, no nvcc, stale packaging, then GPU-less arch detection).
nvdiffrast exists in TRELLIS only to BAKE TEXTURES - and we do not want textured
cars. Vice Coast tints vehicles across eight colours at runtime, which is what
makes "a red car" mean something to the witness system. A baked texture would
fight that.

So: shape only. Hunyuan3D-2 mini's shape pipeline is a 0.6B flow-matching model
in plain PyTorch. No custom CUDA extensions, no rasteriser, nothing to compile.
We never import hy3dgen.texgen, which is the half that needs a compiler.

Runs as a TASK QUEUE, not a synchronous endpoint. Submitting returns a task id
straight away, so nothing has to hold an HTTP connection open while the node
pulls the image and boots the container - which is what was killing every
request before (tasks sat PENDING, the gateway closed the socket, client saw a
timeout or a connection reset).

Results land on the vicecoast-meshes volume; the client polls for the files.

Deploy (from this folder):
    beam deploy hunyuan_beam.py:generate
"""

import base64
import json
import os
import sys
import time

from beam import Image, Volume, task_queue

CACHE = "/hy3d"
OUT_DIR = "/meshes"
REPO = "/opt/Hunyuan3D-2"

weights = Volume(name="hunyuan3d-weights", mount_path=CACHE)
meshes = Volume(name="vicecoast-meshes", mount_path=OUT_DIR)

image = (
    Image(python_version="python3.11")
    .add_commands([
        "apt-get update -y && apt-get install -y git libgl1 libglib2.0-0",

        # Same cu126 pin as the Klein app - Beam's 4090 hosts run driver 12.8.
        "pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 "
        "--index-url https://download.pytorch.org/whl/cu126",

        # Source only. We deliberately do NOT pip install the repo, because its
        # setup builds the texture rasteriser we are avoiding.
        f"git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git {REPO}",
    ])
    .add_python_packages([
        # hy3dgen predates transformers 5.x / hub 1.x; the unpinned build pulled
        # transformers 5.15 and huggingface_hub 1.28, which change APIs it uses.
        "diffusers>=0.31,<0.36", "transformers>=4.46,<5", "huggingface_hub<1.0",
        "accelerate", "safetensors",
        "einops", "omegaconf", "trimesh<5", "scikit-image", "scipy", "numpy",
        "pillow", "tqdm", "sentencepiece", "protobuf",
        "fast-simplification",          # trimesh's quadric decimator backend
        # hy3dgen.shapegen imports its postprocessors at module load, and those
        # need pymeshlab. Without it the whole package fails to import.
        "pymeshlab",
        # From the repo's own requirements.txt rather than memory - which is how
        # pymeshlab and cv2 both got missed. shapegen/preprocessors.py imports
        # cv2 at module level; pygltflib and xatlas back the GLB export path.
        "opencv-python-headless", "pygltflib", "xatlas",
        # rembg/onnxruntime deliberately omitted. They pull numba and several GB
        # of runtime, and the whole point of them - isolating the subject on a
        # plain background - is already true of our Klein references. A fat image
        # meant tasks sat PENDING for minutes while the node pulled it, which is
        # what was actually killing every request.
        "hf_transfer",
    ])
)


_PIPE = None


def get_pipe():
    """Loaded on first request, not at container start.

    `beam logs` fails on Windows with an SSL error, so a crash inside an
    on_start hook is completely invisible - the task just shows CANCELLED with
    no container. Loading here means any failure comes back in the HTTP
    response where we can actually read it."""
    global _PIPE
    if _PIPE is not None:
        return _PIPE

    os.environ["HF_HOME"] = "/tmp/hf"            # volumes have no flock
    os.environ["HF_HUB_CACHE"] = os.path.join(CACHE, "hub")

    sys.path.insert(0, REPO)

    import torch
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

    t0 = time.perf_counter()
    _PIPE = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        "tencent/Hunyuan3D-2mini",
        subfolder="hunyuan3d-dit-v2-mini-turbo",
        use_safetensors=True,
        device="cuda",
    )
    print(f"pipeline ready in {time.perf_counter() - t0:.1f}s "
          f"on {torch.cuda.get_device_name(0)}")
    return _PIPE


@task_queue(
    name="vicecoast-hunyuan",
    image=image,
    volumes=[weights, meshes],
    gpu="RTX4090",
    cpu=8,
    memory="32Gi",
    keep_warm_seconds=600,
    timeout=3600,
)
def generate(**inputs):
    import io as _io
    import traceback

    # Probe mode: confirm imports and versions without touching the GPU.
    if inputs.get("probe"):
        info = {}
        for mod in ("torch", "transformers", "huggingface_hub", "diffusers", "trimesh"):
            try:
                info[mod] = __import__(mod).__version__
            except Exception as e:
                info[mod] = f"ERR {e}"
        info["repo_exists"] = os.path.isdir(REPO)
        try:
            sys.path.insert(0, REPO)
            import hy3dgen.shapegen  # noqa: F401
            info["hy3dgen_import"] = "ok"
        except Exception:
            info["hy3dgen_import"] = traceback.format_exc()[-1500:]
        return info

    def report(name, text):
        """beam logs is broken on this machine and a task queue never returns its
        value to the caller, so failures have to be written somewhere readable.
        The output volume is the one channel we can always inspect."""
        try:
            os.makedirs(OUT_DIR, exist_ok=True)
            with open(os.path.join(OUT_DIR, name), "w") as fh:
                fh.write(text)
        except Exception:
            pass
        print(text)

    try:
        pipe = get_pipe()
    except Exception:
        tb = traceback.format_exc()
        report("_error_load.txt", tb)
        return {"error": "pipeline load failed", "traceback": tb[-3000:]}

    import torch
    import trimesh
    from PIL import Image as PILImage

    sys.path.insert(0, REPO)
    from hy3dgen.shapegen import FloaterRemover, DegenerateFaceRemover

    jobs = inputs.get("jobs") or []
    if not jobs:
        return {"error": "no jobs supplied"}

    out_name = inputs.get("out", "v1")
    steps = int(inputs.get("steps", 12))
    octree = int(inputs.get("octree_resolution", 256))
    # Vice Coast renders its whole city in ~37k triangles, so a car gets a
    # strict budget. Anything finer is thrown away by the decimator anyway.
    budget = int(inputs.get("face_budget", 1800))

    target = os.path.join(OUT_DIR, out_name)
    os.makedirs(target, exist_ok=True)

    manifest = []
    t_start = time.perf_counter()

    try:
        _run(pipe, jobs, target, steps, octree, budget, manifest, report)
    except Exception:
        tb = traceback.format_exc()
        report("_error_run.txt", tb)
        return {"error": "generation failed", "traceback": tb[-3000:],
                "completed": len(manifest)}

    total = time.perf_counter() - t_start
    with open(os.path.join(target, "manifest.json"), "w") as f:
        json.dump({"out": out_name, "meshes": manifest,
                   "total_seconds": round(total, 2)}, f, indent=2)
    return {"count": len(manifest), "out": out_name,
            "total_seconds": round(total, 2), "meshes": manifest}


def _run(pipe, jobs, target, steps, octree, budget, manifest, report):
    import io as _io
    import torch
    import numpy as np
    from PIL import Image as PILImage

    def clean(mesh):
        """hy3dgen's FloaterRemover/DegenerateFaceRemover round-trip the mesh
        through a temp .ply and pymeshlab, and this pymeshlab wheel has no PLY
        IO plugin ("Unknown format for load: ply"). trimesh does both jobs
        in-memory, so we skip pymeshlab on the hot path entirely."""
        # drop degenerate faces and any vertices left orphaned by that
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.remove_unreferenced_vertices()
        # keep only the largest connected component - that is the vehicle,
        # everything else is reconstruction noise floating around it
        parts = mesh.split(only_watertight=False)
        if len(parts) > 1:
            mesh = max(parts, key=lambda m: len(m.faces))
        return mesh

    for i, job in enumerate(jobs):
        jid = job.get("id") or f"mesh_{i:03d}"
        img = PILImage.open(_io.BytesIO(base64.b64decode(job["image_b64"]))).convert("RGB")

        t0 = time.perf_counter()
        mesh = pipe(
            image=img,
            num_inference_steps=int(job.get("steps", steps)),
            octree_resolution=int(job.get("octree_resolution", octree)),
            num_chunks=20000,
            generator=torch.manual_seed(int(job.get("seed", 42))),
            output_type="trimesh",
        )[0]
        t_gen = time.perf_counter() - t0

        t1 = time.perf_counter()
        mesh = clean(mesh)

        raw_faces = len(mesh.faces)
        # per-job budget: the car you drive can afford detail, a parked car
        # forty metres away cannot. A single global budget is what turned the
        # first batch into blobs (650k faces crushed to 1800 = 0.3% kept).
        b = int(job.get("face_budget", budget))
        if raw_faces > b:
            mesh = mesh.simplify_quadric_decimation(face_count=b)

        # normalise to a unit-ish size so the engine can scale predictably
        mesh.apply_translation(-mesh.bounding_box.centroid)
        scale = 1.0 / max(mesh.extents)
        mesh.apply_scale(scale)

        # Export to /tmp first, then copy. Beam volumes do not support flock,
        # and trimesh.export() opening a file directly on the volume raises
        # BlockingIOError: Resource temporarily unavailable.
        import shutil
        tmp_path = f"/tmp/{jid}.glb"
        mesh.export(tmp_path)
        path = os.path.join(target, f"{jid}.glb")
        shutil.copyfile(tmp_path, path)
        os.remove(tmp_path)
        t_post = time.perf_counter() - t1

        kb = os.path.getsize(path) / 1024
        manifest.append({"id": jid, "file": f"{jid}.glb", "kb": round(kb, 1),
                         "faces_raw": raw_faces, "faces": len(mesh.faces),
                         "gen_s": round(t_gen, 2), "post_s": round(t_post, 2)})
        print(f"[{i+1}/{len(jobs)}] {jid}: {raw_faces}->{len(mesh.faces)} faces, "
              f"gen {t_gen:.1f}s post {t_post:.1f}s, {kb:.0f}KB")

