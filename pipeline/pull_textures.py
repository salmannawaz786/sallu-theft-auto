"""
Download generated textures off the Beam volume.

Works around an upstream Windows bug in beam-client 0.2.203: RemotePath.path
and RemotePath.__truediv__ both use os.path.join, which emits backslashes on
Windows. The gateway splits remote paths on "/", so it sees the whole thing as
a volume name and reports "unable to find volume". Any `beam cp` DOWNLOAD of a
path containing a subdirectory fails on Windows because of this.

We patch both to POSIX joins, then hand off to the normal CLI.

    python pull_textures.py                 # pulls trial_v1
    python pull_textures.py batch_v2        # pulls another output dir
"""

import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")

import beta9.multipart as mp

_VOL = "vicecoast-textures"
HERE = os.path.dirname(os.path.abspath(__file__))


def _posix_path(self):
    if self.volume_path == "":
        return self.volume_name + "/"
    return f"{self.volume_name}/{self.volume_path}".replace("\\", "/").replace("//", "/")


def _posix_join(self, other):
    path = other if isinstance(other, str) else other.volume_path
    joined = f"{self.volume_path}/{path}".replace("\\", "/").replace("//", "/").lstrip("/")
    return mp.RemotePath(
        self.scheme,
        self.volume_name,
        joined,
        other.is_dir if isinstance(other, mp.RemotePath) else self.is_dir,
    )


mp.RemotePath.path = property(_posix_path)
mp.RemotePath.__truediv__ = _posix_join

from beam.cli import main  # noqa: E402  (import after the patch lands)

def pull(remote, dest):
    sys.argv = ["beam", "cp", remote, dest]
    try:
        main.cli()
    except SystemExit:
        pass


if __name__ == "__main__":
    import json

    out_dir = sys.argv[1] if len(sys.argv) > 1 else "trial_v1"
    dest = os.path.join(HERE, "out", out_dir)
    os.makedirs(dest, exist_ok=True)

    # Directory downloads mis-detect as files, so pull each file by name.
    sheet_name = sys.argv[2] if len(sys.argv) > 2 else "prompts_trial.json"
    sheet = os.path.join(HERE, sheet_name)
    with open(sheet, encoding="utf-8") as f:
        ids = [j["id"] for j in json.load(f)["jobs"]]

    names = [f"{i}.png" for i in ids] + ["manifest.json"]
    print(f"Pulling {len(names)} files from beam://{_VOL}/{out_dir}/ -> {dest}")
    for n in names:
        pull(f"beam://{_VOL}/{out_dir}/{n}", os.path.join(dest, n))

    got = [f for f in os.listdir(dest)]
    print(f"{len(got)} files landed in {dest}")
